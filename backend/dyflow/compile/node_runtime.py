"""Node behaviour: what each node *does* once the compiler has decided the shape.

The split with `workflow_compiler` is deliberate and load-bearing. The compiler
owns **topology** and knows nothing about models, prompts or tools; this file owns
**behaviour** and knows nothing about edges or entry points. That is what lets the
entire graph structure be tested with no API key, and it is why a new node type is
a factory entry here rather than a change to the compiler.

Routing decisions are written to `state["decisions"][node_id]`, which the
compiler's `path` function reads. So a router node *decides* and the conditional
edge *dispatches* — two responsibilities, two places, and neither has to know how
the other works.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph.message import add_messages

from dyflow.abc.grader import Grader
from dyflow.abc.orchestrator import Orchestrator
from dyflow.abc.router import Router
from dyflow.compile.workflow_compiler import CompiledPlan


def merge_decisions(left: dict, right: dict) -> dict:
    """Reducer for the decisions channel.

    A named merge rather than last-write-wins, because two nodes can decide in the
    same superstep during a fan-out and one silently clobbering the other would be
    invisible. (CLAUDE.md: reducers are a named enum, never arbitrary functions —
    this is the `merge` member.)
    """
    return {**left, **right}


def keep_max(left: int, right: int) -> int:
    """Reducer for `attempts` — a counter with more than one legitimate writer.

    `_agent` and `_orchestrator` each bump `attempts` for their own retry/
    replan budget, and both can be live in the same graph (an agent branch's
    revise loop alongside a dataquery branch's orchestrator). As a bare
    scalar this is the identical hazard CLAUDE.md already documents for
    `answer`: safe in every test where only one writer happened to fire per
    step, until a graph shape lets two fire in the same step and LangGraph
    raises `InvalidUpdateError: At key 'attempts': Can receive only one value
    per step`. `max` matches the field's meaning — a budget counter should
    only ever grow, so the higher of two concurrent writes is correct
    regardless of which node produced it.
    """
    return max(left, right)


def keep_latest_nonempty(left: str, right: str) -> str:
    """Reducer for `answer` — a scalar with more than one legitimate writer.

    `_agent`, `_format_report_function` and `_output` can each produce a final
    answer, depending on the graph's shape. As a bare `LastValue` field this
    looked safe in every hand-built test, because none of them happened to run
    in the same tick — until a **real** graph (router + orchestrator + tools,
    two `Send`-dispatched workers with real tool loops) did exactly that and
    LangGraph raised `InvalidUpdateError: At key 'answer': Can receive only one
    value per step`.
    
    The fix is not to make the collision impossible — two nodes legitimately
    writing an answer candidate in the same step is a real shape a developer
    can build — but to make it resolvable: keep whichever write is non-empty,
    preferring the later one when both are. This is the `merge` reducer member
    CLAUDE.md requires for any state two nodes might write concurrently; a bare
    scalar field is only safe for state exactly one node type can ever produce.
    """
    return right or left


class RunState(TypedDict, total=False):
    """The shared state schema for a compiled workflow."""

    messages: Annotated[list, add_messages]
    question: str
    #: node id -> branch label chosen. Read by the compiler's `path` functions.
    decisions: Annotated[dict, merge_decisions]
    #: node id -> that node's textual output, so a downstream node can read it.
    outputs: Annotated[dict, merge_decisions]
    answer: Annotated[str, keep_latest_nonempty]
    #: Same hazard, same fix as `answer`: this document alone has four
    #: `_grader` instances (one per intent), each writing `feedback` on
    #: every step — "" on pass, real text on revise. Found live: two
    #: graders landed in the same superstep and LangGraph raised
    #: `InvalidUpdateError: At key 'feedback': Can receive only one value
    #: per step`, with the raw error then rendered into the chat panel as
    #: if it were the model's own answer.
    feedback: Annotated[str, keep_latest_nonempty]
    attempts: Annotated[int, keep_max]
    #: orchestrator node id -> the subtasks it planned. Read by the compiler's
    #: fan-out routing function to build the `Send` list.
    subtasks: Annotated[dict, merge_decisions]
    #: task id -> that worker instance's output. Joined by whatever reads it.
    #:
    #: Deliberately **not** keyed by node id: many dynamic worker *instances*
    #: share one static worker *node*, so node id would collide every one of
    #: them onto a single key. The task id — unique per dispatched Send — is
    #: what keeps every instance's result addressable.
    worker_results: Annotated[dict, merge_decisions]
    #: Set only inside a dispatched worker instance, from the Send payload.
    #: Absent everywhere else — a worker cannot see the parent's other state,
    #: only what the orchestrator explicitly packed into its Send (see below).
    task_id: str
    task_instruction: str


#: Maps a tool node type to the Python tool that implements it.
#:
#: Injectable, because tool discovery is workflow-scoped (ticket 18) and the
#: shared catalogue must not accumulate every workflow's tools. Passing an empty
#: registry is valid: the agent simply gets no tools, which is a degraded run
#: rather than a crash.
ToolRegistry = dict[str, Any]


def chinook_tool_registry() -> ToolRegistry:
    """The Chinook workflow's tools, keyed by node type."""
    from tools.chinook import ExecuteSqlTool, GetTableSchemaTool, ListTablesTool

    return {
        "tool.chinook-get-schema": GetTableSchemaTool(),
        "tool.chinook-get-all-tables": ListTablesTool(),
        "tool.chinook-execute-sql": ExecuteSqlTool(),
    }


class _DeepAgentAsChatModel:
    """Makes a compiled deep agent look like the chat model `BaseGrader.grade()`
    expects — a bare `.invoke(messages) -> object with .content`.

    `BaseGrader` (`dyflow/abc/grader.py`) is deliberately model-agnostic: it
    knows nothing about `create_deep_agent`, tiers, or LangChain harness
    tiers, and should not have to. So the adaptation lives here, at the
    compiler/runtime boundary, rather than teaching the grader ladder about a
    concrete agent construction — the same boundary rule CLAUDE.md states for
    cross-family concerns (a collaborator, not a shared ancestor).

    Built fresh **per grading call**, not once at compile time, because the
    system prompt — `messages[0]` — varies with the question being judged
    (`BaseGrader.resolve_system_prompt` appends it as context). Mirrors the
    worker's own fix for the identical shape of problem: `create_agent`'s
    `system_prompt=` construction parameter is the proven-working way to
    deliver a directive prompt, not a hand-assembled message list.
    """

    def __init__(self, model: Any, name: str) -> None:
        self._model = model
        self._name = name

    def invoke(self, messages: list[Any]) -> Any:
        from deepagents import create_deep_agent

        system_prompt = messages[0].content if messages else ""
        candidate_message = messages[-1]
        agent = create_deep_agent(
            model=self._model,
            tools=[],
            system_prompt=system_prompt,
            name=self._name,
        )
        result = agent.invoke({"messages": [candidate_message]})
        out = result.get("messages") or []
        text = out[-1].content if out else ""
        return SimpleNamespace(content=text if isinstance(text, str) else str(text))


def _text(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key)
    return value if isinstance(value, str) else default


def _branch_entries(raw: Any) -> list[Any]:
    """The router's branch table, in either of its two saved forms.

    v1 documents store a newline-separated string of names; v2 (ticket 20)
    stores ``[{id, name}]`` so edges survive renames. Anything unusable
    collapses to a single ``"default"`` branch rather than raising — a router
    is the entry point, and refusing to compile is a total outage where a
    misroute is recoverable. `Branch.of` handles per-entry normalisation.
    """
    if isinstance(raw, str):
        names = [line.strip() for line in raw.split("\n") if line.strip()]
        return names or ["default"]
    if isinstance(raw, list):
        entries = [entry for entry in raw if isinstance(entry, (str, dict))]
        return entries or ["default"]
    return ["default"]


def _upstream_text(state: RunState, node_ids: list[str]) -> str:
    outputs = state.get("outputs") or {}
    return "\n".join(outputs[n] for n in node_ids if n in outputs)


class NodeRuntime:
    """Builds the callable for each node type.

    A registry keyed by node type rather than an if-chain, so adding a node type
    is a registration and `core` stays closed for modification.
    """

    def __init__(
        self,
        *,
        model: Any = None,
        tools: ToolRegistry | None = None,
        functions: dict[str, Any] | None = None,
        document_loader: Callable[[str], dict[str, Any]] | None = None,
        max_attempts: int = 3,
        _ancestry: tuple[str, ...] = (),
    ) -> None:
        self.model = model
        self.tools = tools or {}
        #: `function.<name>` -> callable — deterministic graph steps
        #: discovered from the workflow's `functions/` (ticket 35).
        self.functions = functions or {}
        #: Loads another workflow's document by slug, for `workflow.subgraph`
        #: nodes (ticket 34). None means subgraphs cannot resolve — recorded
        #: loudly in `unresolved_subgraphs`, never silently.
        self.document_loader = document_loader
        #: The chain of subgraph slugs above this runtime — how a workflow
        #: that (transitively) includes itself is refused at build time
        #: instead of recursing forever at run time.
        self._ancestry = _ancestry
        self.max_attempts = max_attempts
        #: Per-node model overrides, keyed by the resolved LangChain model
        #: string — cached so ten agents on the same non-default model share
        #: one client instance rather than each cold-starting its own.
        self._model_cache: dict[str, Any] = {}
        #: node id -> node type, populated by `factory()`.
        self._types: dict[str, str] = {}
        #: node id -> raw node dict, populated by `factory()`. A tool
        #: binding is resolved by *type* against `self.tools`, which has no
        #: access to that specific bound node's own `data` — this is how a
        #: tool factory (e.g. `tool.chinook-execute-sql`'s row cap) reads a
        #: per-node config value rather than only ever seeing its type.
        self._nodes: dict[str, dict[str, Any]] = {}
        #: Tool nodes wired on the canvas with no implementation available.
        #:
        #: Surfaced rather than swallowed. An agent that silently loses its tools
        #: does not fail — it answers from parametric knowledge, confidently and
        #: wrongly. Observed exactly that: a Reddit tool node wired to an agent
        #: produced an authoritative-sounding answer about global music revenue
        #: instead of querying anything. A visible warning beats a plausible lie.
        self.unresolved_tools: list[str] = []
        #: Function node types wired on the canvas with no discovered callable,
        #: and subgraph nodes whose workflow could not be loaded. Same loudness
        #: rule as tools: a silently-degraded step reads as "covered" when it
        #: was not.
        self.unresolved_functions: list[str] = []
        self.unresolved_subgraphs: list[str] = []
        self._builders: dict[str, Callable[..., Any]] = {
            "input.text": self._input,
            "input.markdown": self._input,
            "agent.llm": self._agent,
            "route.classifier": self._router,
            "route.grader": self._grader,
            "human.approval": self._human_approval,
            "orchestrate.supervisor": self._orchestrator,
            "orchestrate.worker": self._worker,
            "function.format_report": self._format_report_function,
            "output.formatted": self._output,
        }

    def factory(
        self, document: dict[str, Any]
    ) -> Callable[[str, dict[str, Any], CompiledPlan], Any]:
        """The `node_factory` the compiler expects.

        Takes the whole document because a node's behaviour can depend on
        *another* node: an agent needs the **type** of each tool bound to it in
        order to resolve the implementation, and the plan carries only ids.
        """
        self._types = {
            n["id"]: str(n.get("type", "")) for n in document.get("nodes", [])
        }
        self._nodes = {n["id"]: n for n in document.get("nodes", [])}

        def build(node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
            node_type = str(node.get("type", ""))
            builder = self._builders.get(node_type)
            if builder is not None:
                return builder(node_id, node, plan)
            # Discovered capabilities resolve by convention, after the
            # explicitly-registered builders so a built-in like
            # `function.format_report` can never be shadowed by accident.
            if node_type in ("workflow.subgraph", "team.workflow"):
                return self._subgraph(node_id, node, plan)
            if node_type.startswith("function."):
                return self._discovered_function(node_id, node, plan)
            return self._passthrough(node_id, node, plan)

        return build

    def _resolve_model(self, data: dict[str, Any]) -> Any:
        """This node's own model, falling back to the graph's shared default.

        Found via a TS-schema-vs-Python-factory diff: every model-calling
        node's card lets a developer pick its own model
        (`AgentNode.ts`'s `model` field, the same select `RouterNode.ts`/
        `GraderNode.ts` use), but this class only ever accepted one `model`
        for the *entire graph* — the canvas visibly showed three different
        AI Agent cards set to three different models while every one of
        them, run through the backend, used whichever single model the
        `/api/runs` request happened to resolve. This is the fix: read the
        node's own selection first, the shared default only when it has
        none.

        `data.get("model")` is the canvas's `provider/modelId` string
        (`ProviderRegistry.selectionFor`) — slash-separated, because that is
        the frontend's own format; `init_chat_model` expects a colon. Mock
        has no backend equivalent (it is a frontend-only deterministic
        simulator for the local canvas preview, not a real chat model), so a
        node configured for it falls back to the shared default exactly like
        a node with no override at all, rather than erroring.
        """
        selection = _text(data, "model")
        if not selection:
            return self.model
        provider, _, model_id = selection.partition("/")
        if not model_id or provider == "mock":
            return self.model
        key = f"{provider}:{model_id}"
        if key not in self._model_cache:
            from langchain.chat_models import init_chat_model

            try:
                self._model_cache[key] = init_chat_model(key)
            except Exception:
                # An unconfigured provider (no API key) or an unrecognised
                # model id must not take the whole run down — the shared
                # default still produces an answer, just not the node's own
                # choice. Cached too, so one bad selection does not retry
                # (and re-fail) on every node that shares it.
                self._model_cache[key] = self.model
        return self._model_cache[key]

    # -- node kinds ------------------------------------------------------- #

    def _input(self, node_id: str, node: dict[str, Any], _plan: CompiledPlan) -> Any:
        """Seeds its configured text, or the caller's question if it has none.

        Preferring the question means a saved workflow answers *this* run rather
        than replaying whatever prompt was typed when it was saved.
        """
        configured = _text(node.get("data") or {}, "prompt") or _text(
            node.get("data") or {}, "instruction"
        )

        def run(state: RunState) -> dict[str, Any]:
            text = state.get("question") or configured
            return {"outputs": {node_id: text}}

        return run

    def _bound_tool(self, tool_node_id: str) -> Any | None:
        """Resolves one bound tool node to the implementation it should use.

        The shared registry (`self.tools`) is keyed by *type*, one instance
        per type for the whole document — right for a stateless tool, wrong
        the moment a canvas field varies the instance's own behaviour.
        `tool.chinook-execute-sql`'s "Max rows" is exactly that case (found
        by a TS-schema-vs-Python-factory diff: the field was fully inert on
        the backend, always using the bare class default regardless of what
        a developer configured). Building a *fresh* instance here rather
        than mutating the shared one matters the moment a document has two
        SQL-tool nodes with two different row caps bound to two different
        agents — mutating the one shared object would let the second bind
        clobber the first's ceiling.
        """
        tool_type = self._types.get(tool_node_id, "")
        tool = self.tools.get(tool_type)
        if tool is None:
            if tool_type not in self.unresolved_tools:
                self.unresolved_tools.append(tool_type)
            return None

        data = self._nodes.get(tool_node_id, {}).get("data") or {}
        configure = getattr(tool, "configure", None)
        if configure is None or not data:
            return tool
        # `configure` returns a fresh instance when config matters (the
        # BaseTool contract), so the shared registry instance is never
        # mutated — the row-cap special case that used to live here is now
        # each tool's own business.
        return configure(data)

    def _agent(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """An agent-family loop with the tools the canvas bound to it.

        Construction is delegated to the ladder in `dyflow.abc.agent` — the
        node's `tier` picks the class, `resolve_prompt()` is the single place
        the authored `systemPrompt` and the wired skill text become a prompt,
        and `resolve_middleware()` flattens into the library's own
        `create_agent(middleware=...)` seam. This factory keeps only the
        state plumbing: what flows in, what update flows out.

        The agent is built **per skill value**, not once at compile time,
        because the skill port's text arrives through state — the same reason
        `_worker` rebuilds per invocation. A memo keeps the common case (no
        skill wired, context never changes) at one construction total.
        """
        from dyflow.abc import agent as agent_family
        from langchain_core.messages import HumanMessage

        # Resolved by the *type* of each bound node, so wiring a tool on the
        # canvas is exactly what gives the agent that capability.
        lc_tools = []
        for tool_node_id in plan.tool_bindings.get(node_id, []):
            tool = self._bound_tool(tool_node_id)
            if tool is not None:
                lc_tools.append(tool.as_langchain_tool())

        data = node.get("data") or {}
        model = self._resolve_model(data)
        #: Exposed so a test can assert the wiring produced the tools, without
        #: needing a model to prove it.
        self.last_bound_tools = [t.name for t in lc_tools]

        skills = plan.skill_bindings.get(node_id, [])
        upstream = [src for src, dst in plan.edges if dst == node_id]
        built: dict[str, Any] = {}

        def agent_for(skill: str) -> Any:
            if skill not in built:
                tier_cls = agent_family.agent_node_for_tier(_text(data, "tier"))
                built[skill] = tier_cls(
                    name=f"agent_{node_id}",
                    model=model,
                    tools=lc_tools,
                    rules=_text(data, "systemPrompt"),
                    context=skill,
                ).build()
            return built[skill]

        def run(state: RunState) -> dict[str, Any]:
            prompt = _upstream_text(state, upstream) or state.get("question", "")
            skill = _upstream_text(state, skills)
            feedback = state.get("feedback", "")
            if feedback:
                # The retry carries *why*, or the agent repeats itself and the
                # loop is pure cost.
                prompt = f"{prompt}\n\nYour previous answer was rejected: {feedback}"

            agent = agent_for(skill) if model is not None else None
            if agent is None:
                return {
                    "outputs": {node_id: ""},
                    "attempts": state.get("attempts", 0) + 1,
                }

            payload = [HumanMessage(content=prompt)]
            result = agent.invoke({"messages": payload})
            messages = result.get("messages") or []
            text = messages[-1].content if messages else ""
            answer = text if isinstance(text, str) else str(text)
            return {
                "outputs": {node_id: answer},
                "answer": answer,
                "attempts": state.get("attempts", 0) + 1,
                "messages": messages[-1:],
            }

        return run

    def _router(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Classifies, and writes the branch for the conditional edge to read.

        `tier` (react/deep/custom) was declared on `RouterNode.ts` but never
        read here — found by the same field diff that caught the grader's
        equivalent gap before this file's own `_DeepAgentAsChatModel` comment
        was written. `tier: "deep"` now does exactly what it already does
        for the grader: wraps the classifying model in a compiled deep agent
        rather than teaching `BaseRouter` about one.
        """
        data = node.get("data") or {}
        branches = _branch_entries(data.get("branches"))
        base_model = self._resolve_model(data)
        classifying_model = base_model
        if _text(data, "tier") == "deep" and base_model is not None:
            classifying_model = _DeepAgentAsChatModel(base_model, name=f"router_{node_id}")
        router = Router(
            branches,
            fallback=_text(data, "fallback") or None,
            rules=_text(data, "rules"),
            model=classifying_model,
        )
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            question = _upstream_text(state, upstream) or state.get("question", "")
            decision = router.classify(question)
            return {
                # The conditional edge dispatches on the *stable id* — the
                # `branch:<id>` port the canvas edge actually leaves from —
                # while the model classified by human-readable *name*.
                # `route_key` is the one place that mapping lives.
                "decisions": {node_id: router.route_key(decision.branch)},
                "outputs": {node_id: question},
            }

        return run

    def _grader(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Judges, and chooses `pass` or `revise`.

        The card's `tier` field (react/deep/custom) previously did nothing on
        this side — `Grader.grade()` always made one bare chat-model call
        regardless of what a developer picked. `tier: "deep"` now actually
        builds a `create_deep_agent` for the judgement, via
        `_DeepAgentAsChatModel` rather than by teaching `BaseGrader` about
        deep agents.
        """
        data = node.get("data") or {}
        base_model = self._resolve_model(data)
        grading_model = base_model
        if _text(data, "tier") == "deep" and base_model is not None:
            grading_model = _DeepAgentAsChatModel(base_model, name=f"grader_{node_id}")
        grader = Grader(
            criteria=_text(data, "criteria"),
            replace_defaults=_text(data, "criteriaMode") == "replace",
            model=grading_model,
        )
        cap = int(data.get("maxAttempts") or self.max_attempts)
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            candidate = _upstream_text(state, upstream) or state.get("answer", "")
            verdict = grader.grade(candidate, question=state.get("question", ""))

            # Budget check before routing: a grader that keeps rejecting must
            # still let the run finish with an honest answer rather than spin.
            exhausted = state.get("attempts", 0) >= cap
            branch = "pass" if verdict.passed or exhausted else "revise"
            return {
                "decisions": {node_id: branch},
                "feedback": "" if branch == "pass" else verdict.feedback,
                "outputs": {node_id: candidate},
            }

        return run

    def _human_approval(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Pauses the run and waits for a person, via LangGraph's own `interrupt()`.

        Same node-decides/edge-dispatches split as the router and the
        grader — this node *decides* `approved`/`rejected`, and the
        compiler's conditional edge (`workflow_compiler.py`) *dispatches* on
        whichever label it wrote to `state["decisions"]`. The difference
        from the grader is only *who* decides: a human, resumed via
        `Command(resume=...)`, instead of an LLM's own judgement.

        `interrupt()` requires the compiled graph to have a checkpointer
        (`WorkflowCompiler.build`'s `checkpointer` param) — without one,
        LangGraph raises before this ever pauses. Calling it more than once
        per node invocation is the documented anti-pattern (a resume re-runs
        the node from its own start), which is exactly why this calls it
        **exactly once**, unconditionally, rather than inside a retry loop.
        """
        data = node.get("data") or {}
        message = _text(data, "message") or "Approve this result?"
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            from langgraph.types import interrupt

            candidate = _upstream_text(state, upstream) or state.get("answer", "")
            decision = interrupt({"message": message, "candidate": candidate})

            approved = isinstance(decision, dict) and decision.get("decision") == "approve"
            feedback = ""
            if not approved:
                feedback = (decision or {}).get("feedback", "") if isinstance(decision, dict) else ""
            return {
                "decisions": {node_id: "approved" if approved else "rejected"},
                "feedback": feedback,
                "outputs": {node_id: candidate},
            }

        return run

    def _orchestrator(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Splits its instruction into subtasks and writes the plan to state.

        Does **not** dispatch. Dispatch is the compiler's `_fan_out_router`,
        reading exactly what this writes — the same node-decides /
        edge-dispatches split as the router and the grader.
        """
        from dyflow.abc.orchestrator import Archetype, archetype_key

        data = node.get("data") or {}
        cap = int(data.get("maxSubtasks") or 8)
        # The model is for archetype labelling (ticket 37's hybrid routing);
        # decomposition itself stays deterministic. With one wired archetype
        # no labelling call is ever made, so the pre-archetype shape costs
        # nothing extra.
        orchestrator = Orchestrator(max_subtasks=cap, model=self._resolve_model(data))
        # The wired worker archetypes, in edge order — the same roster the
        # compiler's dispatch map is built from, keyed by the same
        # `archetype_key`, so a label the planning prompt offered is exactly
        # a key the fan-out router can resolve.
        archetypes = []
        for worker_id in plan.fan_out.get(node_id, []):
            worker_node = self._nodes.get(worker_id) or {}
            worker_data = worker_node.get("data") or {}
            archetypes.append(
                Archetype(
                    key=archetype_key(worker_node),
                    name=str(worker_node.get("title") or "").strip() or worker_id,
                    description=_text(worker_data, "role"),
                )
            )
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            instruction = _upstream_text(state, upstream) or state.get("question", "")
            feedback = state.get("feedback", "")
            generation = state.get("attempts", 0)
            subtasks = orchestrator.plan(
                instruction, generation=generation, archetypes=archetypes
            )
            if feedback:
                # Refines every subtask the *original* instruction split
                # into — it does not add one of its own.
                #
                # Found live: an earlier version appended feedback as a new
                # semicolon-delimited clause to the instruction *before*
                # splitting, reasoning that `Orchestrator.split()` is
                # deterministic and needs a structural separator to
                # "incorporate" anything. That reasoning was backwards — a
                # semicolon there does not revise a subtask, it hands the
                # deterministic splitter one MORE clause to split on, so the
                # grader's own rejection text became its own independent
                # `Subtask` and got dispatched to a worker as if it were a
                # fresh user question. On a single-subtask instruction ("who
                # is the best artist of all time?") this produced two
                # workers answering two unrelated things — one the real
                # question, one literally the feedback sentence — joined
                # into one self-contradictory report. Appending to each
                # subtask's own instruction *after* splitting keeps the
                # subtask count exactly what the split of the real
                # instruction implies, with the "why it was rejected"
                # context carried into the retry rather than dispatched as
                # a task of its own.
                subtasks = [
                    t.model_copy(
                        update={
                            "instruction": f"{t.instruction}\n\nYour previous attempt was rejected: {feedback}"
                        }
                    )
                    for t in subtasks
                ]
            return {
                "subtasks": {node_id: [t.model_dump() for t in subtasks]},
                "outputs": {node_id: f"Planned {len(subtasks)} subtask(s)."},
                "attempts": generation + 1,
            }

        return run

    def _worker(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """One dispatched instance of the static worker node.

        Every `Send` targets this same node id, so this factory runs **once**
        at compile time and the closure it returns runs **once per dispatched
        task** — the tools it binds are shared by every instance, which is
        correct: they are the worker archetype's capabilities, not a
        per-instance choice.

        Reads only `task_id` / `task_instruction` from state, because a `Send`
        payload does not inherit the parent's other state keys (verified
        against the installed langgraph — see `_fan_out_router`). If a worker
        needed the original question too, the orchestrator would have to pack
        it into every subtask's instruction explicitly; there is no other way
        for it to arrive.

        **Ships a default system prompt, unlike a bare tool-bound agent.**
        Found live: a worker given SQL tools but no instruction to use them
        answered a Chinook question from general knowledge about the
        entertainment industry rather than querying the database — the tools
        were resolved and available, the model simply had no reason to reach
        for them over its own training data. `_agent` has the same exposure
        whenever no skill is wired to it; a worker has no equivalent skill
        input at all, so it needs a floor. The skill binding, when present,
        still wins — this default only fills the gap when nobody supplied one.

        **The prompt is passed as `create_agent(system_prompt=...)`, not
        prepended as a message.** The first version of this fix kept the
        prompt text but delivered it as a `SystemMessage` stitched into the
        per-invocation `messages` list, on an agent built once with no
        `system_prompt` at all — unlike `workflows/chinook-nl-to-sql/agents.py`'s
        `build_sql_agent`, the one place this exact directive style was
        already proven to work, which passes its prompt as `create_agent`'s
        own `system_prompt` parameter. Matching that shape (agent built fresh
        per invocation, since the skill text can vary by run) rather than
        approximating it with a hand-assembled message list removes a
        variable between the working case and this one.
        """
        from langchain_core.messages import HumanMessage

        lc_tools = []
        for tool_node_id in plan.tool_bindings.get(node_id, []):
            tool = self._bound_tool(tool_node_id)
            if tool is not None:
                lc_tools.append(tool.as_langchain_tool())

        skills = plan.skill_bindings.get(node_id, [])
        # Directive, not a nudge. A weaker version of this ("use tools if
        # available") was tried live first and the model answered a database
        # question from general industry knowledge anyway — a vague
        # instruction competes with a large model's confident training-data
        # recall and loses. Naming the tools and the exact sequence, the way
        # the proven-reliable Chinook skill text does, is what actually
        # changes the behaviour; a preference stated in the abstract does not.
        default_prompt = (
            "You have tools that give you the REAL, current answer — you do "
            "not have this information memorised, and any figure you recall "
            "without calling a tool is almost certainly wrong for this "
            "specific dataset. Always work in this order:\n"
            "1. Call the list-tables tool to see what exists.\n"
            "2. Call the schema tool on the tables you need.\n"
            "3. Call the SQL tool with a single query that answers the question.\n"
            "Only after that sequence, answer using the numbers the tools "
            "returned. Do not answer from general knowledge, and do not "
            "invent a table or column name the schema tool did not show you."
            if lc_tools
            else ""
        )

        def run(state: RunState) -> dict[str, Any]:
            task_id = state.get("task_id", "")
            instruction = state.get("task_instruction", "")

            if self.model is None:
                return {"worker_results": {task_id: ""}}

            system_prompt = _upstream_text(state, skills) or default_prompt
            # Same ladder as `_agent`: the family owns construction, this
            # factory owns state plumbing. The worker's directive is its
            # *rules* — the editable half of the prompt — with no context.
            from dyflow.abc import agent as agent_family

            agent = agent_family.ReactAgentNode(
                name=f"worker_{node_id}",
                model=self.model,
                tools=lc_tools,
                rules=system_prompt,
            ).build()
            result = agent.invoke({"messages": [HumanMessage(content=instruction)]})
            out = result.get("messages") or []
            text = out[-1].content if out else ""
            return {"worker_results": {task_id: text if isinstance(text, str) else str(text)}}

        return run

    def _format_report_function(
        self, node_id: str, node: dict[str, Any], plan: CompiledPlan
    ) -> Any:
        """A deterministic **function** node — distinct from a *tool*.

        The distinction the cookbook (ticket 27) drew and this makes concrete: a
        *tool* is model-callable, chosen by an agent mid-loop; a *function* is a
        graph step the compiler always runs, with no model in the decision. This
        one has nothing to decide — it joins whatever worker results exist into
        one report, in task-id order, with no LLM call and therefore no
        variance. Determinism here is a feature: the same worker results always
        produce the same report text, which is what makes the graph-engineering
        proof below assertable byte-for-byte.
        """
        # The TS field schema (`FormatReportNode.ts`) calls this key
        # `reportTitle`, not `title` — found via a TS-schema-vs-Python-factory
        # diff, not live: a canvas-authored document could never have reached
        # this field at all, since every real document produces `reportTitle`
        # and this read silently fell through to the "Report" default every
        # time.
        title = (node.get("data") or {}).get("reportTitle") or "Report"

        def run(state: RunState) -> dict[str, Any]:
            results = state.get("worker_results") or {}
            # Scoped to ids the *current* plan(s) declared, not every id ever
            # written across every past attempt. `subtasks[orchestrator_id]` is
            # overwritten (not accumulated) on each replan, so this discards
            # stale results from a rejected attempt rather than silently
            # blending them into a report about the latest one.
            current_ids = {
                task["id"]
                for plan_list in (state.get("subtasks") or {}).values()
                for task in plan_list
            }
            scoped = {k: v for k, v in results.items() if k in current_ids}
            body = "\n\n".join(
                f"### {task_id}\n{text}" for task_id, text in sorted(scoped.items())
            )
            report = f"# {title}\n\n{body}" if body else f"# {title}\n\n_No results._"
            return {"outputs": {node_id: report}, "answer": report}

        return run

    def _discovered_function(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """A workflow-discovered function as a deterministic graph step.

        The signature contract is `fn(text: str) -> str` — a transform of the
        node's upstream text, no model, no state access (ticket 35: code is
        referenced by name, never given the raw state to hide control flow
        in). A raised exception becomes readable output — the same
        errors-are-data rule `BaseTool.run` applies: retrying a deterministic
        function reproduces the same failure, so the useful move is to carry
        the message downstream where a grader or a person can read it.
        """
        node_type = str(node.get("type", ""))
        fn = self.functions.get(node_type)
        if fn is None:
            if node_type not in self.unresolved_functions:
                self.unresolved_functions.append(node_type)
            return self._passthrough(node_id, node, plan)

        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            text = _upstream_text(state, upstream) or state.get("question", "")
            try:
                result = fn(text)
            except Exception as exc:
                return {"outputs": {node_id: f"[{node_id} failed: {type(exc).__name__}: {exc}]"}}
            output = result if isinstance(result, str) else str(result)
            return {"outputs": {node_id: output}, "answer": output}

        return run

    def _subgraph(self, node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Another workflow, compiled and invoked as one node of this graph.

        This is what makes "workflow composition = subgraphs" real (ticket
        34). The child is compiled **at build time** — so a workflow that
        (transitively) includes itself is refused with a readable error
        instead of recursing at run time — and invoked with an explicit
        state mapping: the parent's upstream text becomes the child's
        question, and only the child's final answer flows back. The child
        never sees the parent's other state keys, mirroring the
        subagent-isolation rule: a subgraph receives a task and reports a
        result.
        """
        from dyflow.compile.workflow_compiler import WorkflowCompiler

        data = node.get("data") or {}
        slug = _text(data, "workflow").strip()
        upstream = [src for src, dst in plan.edges if dst == node_id]
        # A subgraph fed by a grader's `pass` (or an approval's `approved`)
        # arrives over a *conditional* edge, which `plan.edges` does not
        # carry — same situation `_output` already handles. Without this, a
        # review subgraph placed after a grader would receive the original
        # question instead of the candidate it is supposed to review
        # (found while wiring ticket 43's code-workshop, not hypothetically).
        conditional_upstream = [
            src for src, dests in plan.conditional.items() if node_id in dests.values()
        ]

        if slug and slug in self._ancestry:
            chain = " -> ".join((*self._ancestry, slug))
            raise ValueError(
                f"Workflow {slug!r} includes itself through its subgraphs ({chain}); "
                "a subgraph cycle can never terminate"
            )

        child_graph = None
        if slug and self.document_loader is not None:
            try:
                child_document = self.document_loader(slug)
            except Exception:
                child_document = None
            if child_document is not None:
                child_runtime = NodeRuntime(
                    model=self.model,
                    tools=self.tools,
                    functions=self.functions,
                    document_loader=self.document_loader,
                    max_attempts=self.max_attempts,
                    _ancestry=(*self._ancestry, slug),
                )
                child_graph = WorkflowCompiler().build(
                    child_document, RunState, child_runtime.factory(child_document)
                )

        if child_graph is None:
            label = slug or "(no workflow selected)"
            if label not in self.unresolved_subgraphs:
                self.unresolved_subgraphs.append(label)
            captured = None
        else:
            captured = child_graph

        def run(state: RunState) -> dict[str, Any]:
            if captured is None:
                return {"outputs": {node_id: ""}}
            question = (
                _upstream_text(state, upstream + conditional_upstream)
                or state.get("answer", "")
                or state.get("question", "")
            )
            final = captured.invoke(
                {"question": question, "attempts": 0, "decisions": {}, "outputs": {}}
            )
            answer = final.get("answer", "")
            # The child's loop cost is part of the parent's story: without
            # this, a Team that revised twice reports attempts=0 (ticket 60).
            update: dict[str, Any] = {"outputs": {node_id: answer}, "answer": answer}
            child_attempts = final.get("attempts")
            if isinstance(child_attempts, int) and child_attempts > 0:
                update["attempts"] = child_attempts
            return update

        return run

    def _output(self, node_id: str, _node: dict[str, Any], plan: CompiledPlan) -> Any:
        """Collects whatever reached it as the run's answer."""
        upstream = [src for src, dst in plan.edges if dst == node_id]
        conditional_upstream = [
            src for src, dests in plan.conditional.items() if node_id in dests.values()
        ]

        def run(state: RunState) -> dict[str, Any]:
            text = _upstream_text(state, upstream + conditional_upstream)
            return {"answer": text or state.get("answer", ""), "outputs": {node_id: text}}

        return run

    def _passthrough(self, node_id: str, _node: dict[str, Any], plan: CompiledPlan) -> Any:
        """An unknown node type forwards its input unchanged.

        Better than raising: a workflow containing one node this build does not
        know still runs, and the gap is visible as an unchanged value rather than
        a dead endpoint.
        """
        upstream = [src for src, dst in plan.edges if dst == node_id]

        def run(state: RunState) -> dict[str, Any]:
            return {"outputs": {node_id: _upstream_text(state, upstream)}}

        return run


__all__ = ["NodeRuntime", "RunState", "ToolRegistry", "chinook_tool_registry", "merge_decisions"]
