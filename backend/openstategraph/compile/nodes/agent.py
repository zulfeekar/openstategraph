"""`agent.llm` — the loop, and the one node type that is a compiled graph.

`CLAUDE.md`'s tier table is this module's subject: an Agent node compiles to
`create_agent`, LangChain's minimal configurable harness, which returns a
compiled LangGraph and therefore drops into the `StateGraph` as a node. It is
the only family here whose *step* is itself a graph.

`_async_task_middleware` lives beside it rather than in a module of its own
because it is not a second reason to change: it is how this family declares
one of its middleware slots, and the subagents it launches inherit this
node's model and tools precisely because there is no remote server for them to
have their own. The isolation rule `CLAUDE.md` states — a subagent receives a
task and reports a result, never the parent's state or messages — is asserted
on that launcher's own arguments in
`tests/test_an_async_subagent_is_isolated.py`.

What is deliberately **not** here is everything the family shares with the
others: model resolution, reasoning effort, tool binding and the middleware
slot table stay on `NodeRuntime`, because they are declared once for every
family and `CLAUDE.md`'s anti-duplication rule is what says so.

`compile/nodes/__init__.py` carries the argument for the package and the
binding mechanism.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal

from openstategraph import injection
from openstategraph.async_tasks import ASYNC_TASKS_KEY, ASYNC_TASKS_SLOT
from openstategraph.compile.context import (
    advisor_context,
    branch_context,
    held_tools_context,
    retry_inventory,
    revision_request,
    _text,
)
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.fields import _replaces_rules, _summarizes
from openstategraph.compile.reporting import _final_text, tool_report
from openstategraph.compile.subagents import async_subagent_specs, subagent_specs
from openstategraph.run_identity import run_identity

from openstategraph.compile.state import RunState, _upstream_text, _wired_skill
from openstategraph.compile.workflow_compiler import CompiledPlan

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


# ---------------------------------------------------------------------------
# Summarization, and the one node that discloses nothing.
#
# These four came out of `node_runtime.py` with `_agent` (`docs-and-gaps/03`)
# because `_agent` is their only reader — and a constant read by exactly one
# builder is that builder's, not the engine's.
# ---------------------------------------------------------------------------

#: The share of a model's own context window at which it summarizes. The
#: owner's number (2026-08-15); the library's own opinionated stack —
#: deepagents' — uses 0.85, so this is the more conservative of the two.
SUMMARIZE_FRACTION = 0.8

#: The absolute threshold, for every model that cannot answer the fraction.
#: `fraction` resolves against `model.profile["max_input_tokens"]`, which only
#: exists where the integration package ships profile data — and our standing
#: default provider does not: `ChatOllama(model="gpt-oss:120b-cloud").profile`
#: is `None`, verified on this machine. A fraction-only trigger would never
#: fire on the default install, which is this feature's own bug repeated one
#: layer up.
#:
#: 100,000 rather than deepagents' 170,000 fallback: that number is chosen for
#: frontier context windows, and on the models this product actually defaults
#: to the provider would refuse the call long before it was reached.
SUMMARIZE_TOKENS = 100_000


def _summarize_trigger(model: Any) -> list[Any]:
    """The OR list this model can actually be given.

    **The fraction clause is omitted when the model has no profile, and that is
    not an optimisation — it is the difference between working and raising.**
    The research for this wave read `_should_summarize`, which treats an
    unavailable profile as a clause that is simply not met, and concluded a
    plain `[("fraction", 0.8), ("tokens", N)]` was safe everywhere. It is not:
    `SummarizationMiddleware.__init__` (langchain 1.3.14) validates first and
    raises `ValueError` when any clause names `fraction` and the profile is
    absent — so the constant that was meant to close this bug would instead
    have failed the compile of every agent on the default provider.

    The intent is unchanged and the shape is the library's own: the fraction
    fires where a profile exists, the absolute fires everywhere else. Only the
    layer that enforces it moved, from evaluation to construction.

    Profile detection mirrors the library's own `_get_profile_limits` rather
    than guessing, so the two cannot disagree about what "has a profile" means.
    """
    trigger: list[Any] = []
    try:
        profile = getattr(model, "profile", None)
    except Exception:  # pragma: no cover - integrations may raise on access
        profile = None
    if isinstance(profile, Mapping) and isinstance(profile.get("max_input_tokens"), int):
        trigger.append(("fraction", SUMMARIZE_FRACTION))
    trigger.append(("tokens", SUMMARIZE_TOKENS))
    return trigger

#: How much survives. The library's own default, pinned rather than inherited:
#: what "keeps its recent tail" means is behaviour a user notices, and a
#: library default that moved would move it silently. Message-counted on
#: purpose — a `fraction` here would need the same model profile the trigger
#: cannot rely on.
SUMMARIZE_KEEP: tuple[Literal["messages"], int] = ("messages", 20)


#: What a node that discloses nothing gets: no slots filled, no store to
#: point a tier at, and `discover_skills`' flat concatenation kept. Spelled
#: here rather than imported as `DeepTierDisclosure()` because that class
#: lives beside `deepagents`, which is an optional extra — a react-tier agent
#: on an install without it must still compile, and an import for the *empty*
#: answer would take that away.
_NO_DISCLOSURE = SimpleNamespace(contributions={}, backend=None, disclosed=())


def _agent(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """An agent-family loop with the tools the canvas bound to it.

    Construction is delegated to the ladder in `openstategraph.abc.agent` — the
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
    from openstategraph.abc import agent as agent_family
    from langchain_core.messages import HumanMessage

    lc_tools = self._bind_tools(node_id, plan)

    #: The tools **this canvas** wired to the node, snapshotted before the
    #: ambient ones are appended below. `capability_door` reads it to tell
    #: a tool-less workflow from one whose tools went untouched, and a
    #: memory store binds `save_memory` to every agent alive — so counting
    #: the finished list would have meant almost nothing was tool-less.
    #: Found in the browser: a rubric workflow that wires no tool at all
    #: drew the build card on a perfectly good answer
    #: (`every-workflow-green` 35).
    wired = [t.name for t in lc_tools]

    # A store's presence turns on the prebuilt memory tools for every
    # agent (ticket 65) — capability by configuration, no per-workflow
    # wiring, matching the minimum-viable-prebuilt rule.
    if self.services.memory_store is not None:
        from openstategraph.memory import memory_tools

        lc_tools.extend(memory_tools(self.services.memory))

    # Same rule for knowledge: a non-empty knowledge/ in this workflow's
    # package auto-binds the lookup tool. Deduped by tool name, so an
    # explicitly wired Knowledge atom plus the ambient rule is one tool,
    # never two.
    self._attach_ambient_knowledge(lc_tools)

    data = node.get("data") or {}
    # The other half of production-ready 88 (ticket 89): the run is right
    # because `held_tools_context` overrules the stale sentence, which is
    # precisely why nothing would ever prompt the author to fix it.
    self._report_stale_tool_denial(node_id, data, wired)
    model = self._resolve_model(data, node_id)
    #: Exposed so a test can assert the wiring produced the tools, without
    #: needing a model to prove it.
    self.last_bound_tools = [t.name for t in lc_tools]

    skills = plan.skill_bindings.get(node_id, [])
    upstream = [src for src, dst in plan.edges if dst == node_id]
    # An agent fed by a grader's `pass` or an approval's `approved` port
    # arrives over a *conditional* edge, which `plan.edges` does not
    # carry — the same gap `_subgraph` and `_output` already close. Found
    # live by the page-analytics dispatcher: an agent placed after
    # human.approval received the original question instead of the
    # approved report, and either fabricated figures or refused. Router
    # sources are excluded exactly as in `_subgraph`: a routed agent
    # keeps answering the user's question, not the router's rendering.
    conditional_upstream = [
        src
        for src, dests in plan.conditional.items()
        if node_id in dests.values() and self._types.get(src) != "route.classifier"
    ]
    # `feedback` is `keep_latest_nonempty`, so a grader's rejection text
    # survives in state even after the same grader later passes — the ""
    # written on pass can never clear it (that reducer exists to survive
    # two graders in one superstep). An agent must therefore not trust
    # the *presence* of feedback, only feedback whose deciding node still
    # stands by it: the ones whose revise/rejected edge targets this
    # agent AND whose latest decision is still that label. Found live:
    # the page-analytics dispatcher ran after one grader-revise lap and
    # received "Your previous answer was rejected" instead of the
    # human-approved report.
    feedback_sources = self._feedback_sources(node_id, plan)
    # Whether THIS node produced the text the rejecting node judged
    # (`organisms-first-class` 54). A `revise` edge may legally land
    # upstream of the producer — LangChain's agentic-RAG rewrites the
    # *question* — and `revision_request`'s preamble was written for the
    # evaluator-optimizer case where receiver and producer are one node.
    # Delivered to a rewriter it says "this is the answer that was
    # rejected ... revise it" about text the rewriter never wrote.
    #
    # Derived, never declared: a per-node config field would be a fifth
    # knob for a fact already in the plan, and a developer who set it
    # wrong would get this bug back. The rule is edge shape alone, so the
    # Orchestrator's `feedback` port and a human approval's `rejected`
    # edge are covered by the same sentence rather than by a name check.
    # Three roles, not two — the third was found by asking which shipped
    # packages this changes. `support-triage`'s holding-note agent sits on
    # a human approval's `rejected` edge, neither authoring the draft nor
    # feeding the gate: telling it "your last output produced this" would
    # swap one false sentence for another. So: direct producer, else a
    # node that can reach the rejector at all, else a bystander.
    def _role_towards(rejector: str) -> str:
        direct = {s for s, dst in plan.edges if dst == rejector}
        if node_id in direct:
            return "author"
        seen: set[str] = set()
        frontier = list(direct)
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(s for s, dst in plan.edges if dst == current)
        return "upstream" if node_id in seen else "bystander"

    rejector_roles = {src: _role_towards(src) for src in feedback_sources}
    built: dict[tuple[str, str], Any] = {}
    # `launch-readiness/106`: the `NarrationMiddleware` instance behind
    # each built agent, kept here because this is the compiler that made
    # it — exactly as `rubric` and `summarization` above are built here
    # and nowhere else. A retry reads this dict rather than the node,
    # so the node's public surface never grows for it. Keyed identically
    # to `built`; `None` where narration was silenced for this key.
    narration_by_key: dict[tuple[str, str], Any] = {}

    def agent_for(skill: str, run_ctx: str = "") -> Any:
        # Keyed by the run-context block as well as the wired skill
        # (`organisms-first-class/72`). One compiled graph serves many
        # runs, and this cache outlives all of them — keying on `skill`
        # alone would have handed the second caller the first caller's
        # tenant, which is the precise leak this ticket exists to prevent.
        key = (skill, run_ctx)
        if key not in built:
            contributions: dict[str, Any] = dict(self.services.workflow_middleware)
            # Prompt-injection screening, if this workflow asked for it and
            # the extra is installed (guardrails ticket 04). A *workflow*
            # setting rather than a field on this card: the dangerous
            # injection arrives mid-loop in a tool result, so it reaches
            # every agent or none, and a per-agent checkbox would be the
            # duplication the Guardrail node exists to abolish. Absent, the
            # run proceeds and the developer channel says so in one line —
            # refusing to run because an optional extra is missing would
            # turn a dependency gap into an outage.
            screening, screening_gap = injection.contribution(
                requested=injection.requested(self._settings)
            )
            contributions.update(screening)
            if screening_gap is not None:
                self.diagnostics.record(
                    Finding.CAPABILITY_FAILED, screening_gap.message
                )
            if _text(data, "rubric").strip() and model is not None:
                # deepagents' own LLM-as-judge (beta, >=0.6.5): a grader
                # sub-agent inside the agent, iterating until the rubric
                # is satisfied or max_iterations. The rubric *text* rides
                # on invocation state (per the docs), so one middleware
                # serves every question. This is the agent-internal atom;
                # the Grader *node* stays the graph-level organism.
                from openstategraph._extras import require_extra

                RubricMiddleware = require_extra(
                    "deepagents", "deep", "an agent node with a rubric"
                ).RubricMiddleware

                contributions["rubric"] = RubricMiddleware(
                    model=model, max_iterations=3
                )
            if _summarizes(data) and model is not None:
                # LangChain's own prebuilt, never hand-rolled (ticket 66):
                # summarizes older turns when the context bloats, keeping
                # the recent tail verbatim.
                #
                # Built **here** and never on `AbstractAgentNode`, which
                # only declares the slot. A base-filled slot would need a
                # model at construction (`resolve_model()` may legitimately
                # return `None`), would reach `CustomGraphNode`, which has
                # no composition to receive — and would *downgrade*
                # `DeepAgentNode`: `create_deep_agent` already carries a
                # tuned `SummarizationMiddleware`, and a `middleware=`
                # instance whose `.name` matches a built-in replaces that
                # default in place. This is the compiler, which is the one
                # place this node type's config becomes middleware.
                from langchain.agents.middleware import SummarizationMiddleware

                contributions["summarization"] = SummarizationMiddleware(
                    model=model,
                    # A *list*, and that is load-bearing: the library reads
                    # a tuple as one threshold and a list as OR across
                    # several. A tuple of tuples is accepted and means
                    # something else entirely.
                    trigger=_summarize_trigger(model),
                    keep=SUMMARIZE_KEEP,
                )
            # `launch-readiness/106`: built here, the same way `rubric`
            # and `summarization` are — never on the node — so this
            # compiler keeps the one reference a retry needs. A workflow
            # that already named "narration" in `contributions` (the
            # declared way to silence or replace the slot) is left alone;
            # this only fills the slot when nothing already has.
            if "narration" not in contributions:
                from openstategraph.abc.narration import build_narration_middleware

                contributions["narration"] = build_narration_middleware()
            narration_mw = contributions.get("narration")
            tier_cls = agent_family.agent_node_for_tier(_text(data, "tier"))
            # Delegation (`organisms-first-class/84`). The pass-through has
            # existed since `DeepAgentNode` was written and nothing ever
            # filled it, so every deep agent could delegate to exactly one
            # anonymous `general-purpose` worker. Only the deep tier has a
            # parameter to reach — a declaration on any other tier is a
            # `plan.warnings` problem raised at plan time, never a silent
            # drop here, because a pass-through that appears wired and does
            # nothing is what 81 measured `skills=` doing.
            tier_kwargs: dict[str, Any] = {}
            if tier_cls is agent_family.DeepAgentNode:
                specs = subagent_specs(data)
                if specs:
                    tier_kwargs["subagents"] = specs
            # The other half of delegation (`async-first/08`): a row whose
            # `mode` is `async` becomes a **background worker** the agent
            # launches and collects later, not a blocking one. The slot is
            # filled here and only here, and only when a document asked for
            # it — an agent that declares none carries none of the five
            # tools, which is the narrow-interface rule taken literally.
            #
            # Built by the compiler for the same reason `rubric`,
            # `summarization` and `narration` above are: this is the one
            # place this node's config becomes middleware. The base declares
            # the slot and owns its order; it never fills it.
            async_specs = (
                async_subagent_specs(data)
                if tier_cls is agent_family.DeepAgentNode
                else []
            )
            if async_specs:
                contributions[ASYNC_TASKS_SLOT] = self._async_task_middleware(
                    node_id, async_specs, model, lc_tools
                )
            # Progressive skill disclosure and tool-result offload
            # (`launch-readiness/111`, carrying `101` and `102`). **One
            # decision, not two**, and its default is the node's tool
            # surface rather than a setting somebody has to find: both
            # middlewares hand the model a *path*, so both are worthless —
            # worse than worthless, because the failure is a plausible
            # answer rather than an error — on an agent that cannot read a
            # file from the store this seam writes to.
            #
            # `shares_backend` is the half a name check would miss. Only
            # the deep tier's constructor takes `backend=`, so only there
            # can the harness' own `read_file`/`grep` be pointed at what
            # was written; a workflow's own tool called `read_file` reads
            # its own store and a pointer into ours means nothing to it.
            #
            # Built HERE, like `rubric` and `summarization` above and for
            # the same reason: this is the one place this node's config
            # becomes middleware. The base declares the slots and owns
            # their order; it never fills them.
            #
            # Imported inside the branch that can use it: `deepagents` is
            # an optional extra, and a react-tier agent on an install
            # without it must still compile.
            tier_is_deep = tier_cls is agent_family.DeepAgentNode
            wired_names = tuple(sorted({t.name for t in lc_tools}))
            disclosure: Any = _NO_DISCLOSURE
            if tier_is_deep:
                from openstategraph.abc import deep_tier_offload

                disclosure = deep_tier_offload.plan_disclosure(
                    package_dir=self.services.skills_package_dir,
                    tool_surface=(
                        wired_names + deep_tier_offload.DEEP_TIER_FILE_TOOLS
                    ),
                    shares_backend=True,
                    # Prefix-filtered, never blanket (`102`): the tools
                    # this canvas wired, and never the harness' own file
                    # tools — offloading a `read_file` result to a file
                    # and pointing at it is a loop, not a saving.
                    offload_prefixes=wired_names,
                )
            for slot, middleware in disclosure.contributions.items():
                # A workflow that named the slot itself keeps it, exactly
                # as `narration` above: `middlewares/<slot>.py` is the
                # declared way to replace a tier's slot, and a compiler
                # that overwrote it would make that door decorative.
                contributions.setdefault(slot, middleware)
            if disclosure.backend is not None and tier_is_deep:
                tier_kwargs["backend"] = disclosure.backend
            # What is left to inject flat: everything the disclosure did
            # not take. Per skill, not per package — a skill the library
            # will not list (no `description` in its frontmatter, which is
            # two of the three this repository ships) must keep its body in
            # the prompt rather than disappear from it.
            skills_context = self.services.skills_context
            if disclosure.disclosed:
                from openstategraph.api.capability_discovery import discover_skills

                from pathlib import Path as _Path

                skills_context = discover_skills(
                    _Path(self.services.skills_package_dir),
                    exclude=disclosure.disclosed,
                )
            node_instance = tier_cls(
                name=f"agent_{node_id}",
                model=model,
                tools=lc_tools,
                rules=_text(data, "systemPrompt"),
                # The wired skill is a RULES layer, above the inline
                # `systemPrompt` and below the locked output contract
                # (`docs/decisions/skill-layer.md`). It used to ride in
                # `context` with the ambient package skills, which put the
                # deliberate customisation *underneath* the prompt it was
                # wired to customise — and later text wins ties, so the
                # inline prompt quietly beat it every time.
                skill=skill,
                replace_rules=_replaces_rules(data),
                context="\n\n".join(
                    part
                    for part in (
                        # Ambient, package-wide `skills/*.md`: house style
                        # for every agent here, not a choice about this
                        # node. Context, and it stays context.
                        #
                        # Minus whatever was disclosed above — otherwise
                        # a disclosed skill would arrive twice and the
                        # whole saving this seam exists for would be paid
                        # anyway (`launch-readiness/111`). With nothing
                        # disclosed this is exactly what it always was, so
                        # the state that needs no decision loses nothing.
                        skills_context,
                        # The branches this agent's own classifier can
                        # reach (ticket 11) — generated context, so an
                        # agent's suggestions are grounded in the graph
                        # rather than in what its prompt author guessed
                        # the graph contained.
                        branch_context(node_id, plan, self._nodes),
                        # What it *holds*, beside what could be *added*
                        # (production-ready 88). The pair has to travel
                        # together: an agent told only what it lacks, whose
                        # authored rules deny holding anything, answers
                        # "this workflow doesn't include that capability"
                        # about a tool sitting in its own schema.
                        held_tools_context(lc_tools),
                        advisor_context(node_id, self.services.advisor_catalog),
                        # What this *run* was started with, for the fields
                        # the author opted in (`organisms-first-class/72`).
                        # Generated, so it is context and never rules, and
                        # the locked output contract still renders last.
                        run_ctx,
                    )
                    if part
                ),
                middleware=contributions,
                **tier_kwargs,
            )
            built[key] = node_instance.build()
            narration_by_key[key] = narration_mw
        return built[key]

    # **`async def`, and the first family to be** (`async-first/06`).
    # Not a style choice and not throughput: on the installed
    # `langgraph 1.2.10` an `async def` node body is the *only* place a
    # run can be cancelled. Measured twice by two independent routes
    # (`async-first/09`) — under `astream`, cancelling the driving task
    # leaves a `def` body running to completion in its worker thread and
    # stops an `async def` one outright; and `add_node(timeout=...)`, the
    # one construct that interrupts a node mid-flight, is rejected at
    # compile time for sync nodes. So the order of Phase D is by how long
    # a node *runs*, never by how simple it is, and this is the longest.
    #
    # Sync and async node bodies coexist — LangGraph wraps a `def` node in
    # `RunnableLambda` — so the half-migrated graph this leaves behind is
    # not a broken graph. Proven rather than assumed, in
    # `tests/test_a_half_migrated_graph_still_runs.py`, which also pins
    # that narration still reaches the wire from in here: it travels on
    # `get_stream_writer()`, which is context-local, and a migration that
    # dropped it would look exactly like `launch-readiness/110` did — a
    # blank panel, nothing in the logs, both suites green.
    async def run(state: RunState) -> dict[str, Any]:
        prompt = _upstream_text(state, upstream + conditional_upstream) or state.get(
            "question", ""
        )
        skill = _wired_skill(state, skills, self.static_sources)
        decisions = state.get("decisions") or {}
        feedback = state.get("feedback", "")
        if not any(decisions.get(src) in ("revise", "rejected") for src in feedback_sources):
            feedback = ""

        agent = (
            agent_for(skill, self._run_context_section())
            if model is not None
            else None
        )
        if agent is None:
            return {
                "outputs": {node_id: ""},
                "attempts": state.get("attempts", 0) + 1,
            }

        # Conversation memory (ticket 73, generalised): the thread record
        # is written centrally — the input node logs each user turn, the
        # output node logs each answer — so EVERY path accumulates
        # history, and this agent simply speaks into it. A rejection
        # becomes its own turn (the retry carries *why*); a prompt that
        # differs from the recorded turn (an upstream transform) is
        # appended; a fresh thread reduces to single-shot exactly as
        # before. Long threads are bounded by the summarize toggle.
        payload = list(state.get("messages") or [])
        if feedback:
            # The text the rejecting node actually judged, taken from the
            # sources still standing by their rejection — never from
            # `prompt`, which falls back to the question when the
            # candidate was empty, and never from `state["answer"]`, which
            # in a multi-agent document may belong to somebody else.
            standing = [
                src
                for src in feedback_sources
                if decisions.get(src) in ("revise", "rejected")
            ]
            rejected = _upstream_text(state, standing)
            # The strongest claim any standing rejector supports, never
            # the weakest: one rejector this node authored for makes it
            # the author, whatever the others say. Claiming more than the
            # graph shows would be a false statement in a preamble no
            # developer can edit — which is the defect itself.
            roles = [rejector_roles[src] for src in standing]
            role = next(
                (r for r in ("author", "upstream", "bystander") if r in roles),
                "author",
            )
            payload.append(
                HumanMessage(
                    content=revision_request(rejected, feedback, role=role)
                )
            )
            # `launch-readiness/106`: a retry gets pointed at what this
            # run's own findings store already holds, not merely at what
            # was wrong. `narration_by_key` holds the exact instance this
            # compiler built for this skill/run-context key — never a
            # fresh one, and never one fetched back off the agent — so
            # the inventory reflects the store the retry's own tool calls
            # will read and write.
            retry_narration_mw = narration_by_key.get(
                (skill, self._run_context_section())
            )
            inventory_fn = getattr(retry_narration_mw, "findings_inventory", None)
            if inventory_fn is not None:
                thread_id = run_identity().get("thread_id", "")
                if thread_id:
                    inventory_text = retry_inventory(inventory_fn(thread_id))
                    if inventory_text:
                        payload.append(HumanMessage(content=inventory_text))
        elif not payload or payload[-1].type != "human" or payload[-1].content != prompt:
            payload.append(HumanMessage(content=prompt))
        invocation: dict[str, Any] = {"messages": payload}
        rubric_text = _text(data, "rubric").strip()
        if rubric_text:
            invocation["rubric"] = rubric_text
        # `launch-readiness/106`: a `DeepAgentNode`'s compiled agent is a
        # bare `Runnable`, invoked here with no config and no
        # checkpointer of its own — its `StateBackend` keeps `files` in
        # *that* invocation's state only, so without this the agent's own
        # `ls`/`write_file` tools saw a blank store on every call,
        # including a retry lap of this same node in the same turn (the
        # write always landed in a dict nobody read again). `agent_files`
        # on the outer `RunState` — which the workflow's own checkpointer
        # does persist — is the store both calls actually share: seed the
        # sub-agent's `files` from what this node wrote last time, then
        # write back whatever it holds after this call.
        prior_files = (state.get("agent_files") or {}).get(node_id) or {}
        if prior_files:
            invocation["files"] = dict(prior_files)
        # The same threading for the same reason, one channel over
        # (`async-first/08`). A task id that lived only in the agent's own
        # state would be gone the moment this node returned, so the turn
        # that *collects* a background answer would have nothing to look it
        # up by — and a child that outlives the turn is the whole ticket.
        tracked_tasks = state.get(ASYNC_TASKS_KEY) or {}
        prior_tasks = (
            tracked_tasks.get(node_id) or {} if isinstance(tracked_tasks, dict) else {}
        )
        if prior_tasks:
            invocation[ASYNC_TASKS_KEY] = dict(prior_tasks)
        # `ainvoke`, and the `await` is the whole point of the migration:
        # an `async def` body that then blocked on `invoke()` would be
        # *worse* than the `def` body it replaced — it would hold the
        # event loop instead of a pool thread, and still be uncancellable.
        result = await agent.ainvoke(invocation)
        # `_final_text`, not `messages[-1]`: a loop can legitimately end on
        # a message with no content — a dangling tool call, or a provider
        # blip the retry swallowed — and the last message is then "" while
        # the answer sits one message back. `_worker` and `_ModelShim`
        # already read it this way; this node did not, which is how a
        # correct Chinook answer reached a grader as "the answer is empty"
        # and spent the whole retry budget re-asking an answered question.
        text = _final_text(result.get("messages") or [])
        answer = text if isinstance(text, str) else str(text)
        # What this agent was given, used and was refused. The extraction
        # is `tool_report` because `_worker` needs the identical thing and,
        # for one ticket, did not have it (36). `bound` and `ran` are the
        # shape `capability_door` reads when the model said nothing about
        # being blocked (`every-workflow-green` 35).
        new_files = result.get("files")
        return {
            "outputs": {node_id: answer},
            "answer": answer,
            "attempts": state.get("attempts", 0) + 1,
            **({"agent_files": {node_id: new_files}} if new_files else {}),
            **(
                {ASYNC_TASKS_KEY: {node_id: new_tasks}}
                if (new_tasks := result.get(ASYNC_TASKS_KEY))
                else {}
            ),
            **tool_report(
                node_id,
                result.get("messages") or [],
                wired,
                self._unbound_capabilities.get(node_id, ()),
            ),
        }

    return run


def _async_task_middleware(
    self: "NodeRuntime",
    node_id: str,
    specs: list[dict[str, Any]],
    model: Any,
    tools: list[Any],
) -> Any:
    """The `async-tasks` slot for one deep agent (`async-first/08`).

    Each declared worker becomes a **launcher**: a coroutine that builds its
    own `create_agent` loop from the row's prompt and runs a conversation on
    it. The desk holds it; this method only says how to make one.

    **Isolation is structural here, not a rule anybody has to remember.** A
    launcher is handed a list of turn strings and nothing else — no parent
    state, no parent messages, no closure over either. There is no route by
    which the parent's conversation could reach a child even by accident,
    which is why `tests/test_an_async_subagent_is_isolated.py` can assert it
    on the launcher's own arguments.

    The child inherits the parent's **model and tools**, and that is a
    deliberate difference from the library, where an async subagent is a
    graph on a remote server with its own everything. Here there is no
    remote server to have anything, so the honest analogue of "its own tools
    and capabilities" is the surface this node was wired with. When the
    Agent Protocol desk lands, a row gains an optional `graphId` and this
    method stops being the one that answers the question.
    """
    from langchain.agents import create_agent

    from openstategraph.abc.async_task_middleware import AsyncTaskMiddleware
    from openstategraph.async_tasks import desk_for
    from openstategraph.run_identity import run_identity

    def launcher_for(prompt: str) -> Any:
        async def launch(turns: list[str], identity: dict[str, str]) -> str:
            child = create_agent(model=model, tools=list(tools), system_prompt=prompt)
            result = await child.ainvoke(
                {"messages": [{"role": "user", "content": turn} for turn in turns]},
                # The one thing that crosses. Without it a memory-scoped
                # tool inside the child resolves `workflow_slug` and
                # `thread_id` to nothing, and `memory.workflow_scope_slug`
                # says a nameless run **shares a key** — so two
                # conversations' children would write one namespace, which
                # is the opposite of the isolation this is built around.
                {"configurable": dict(identity)} if identity else None,
            )
            text = _final_text(result.get("messages") or [])
            return text if isinstance(text, str) else str(text)

        return launch

    launchers = {
        str(spec["name"]): launcher_for(str(spec.get("system_prompt") or ""))
        for spec in specs
    }

    def desk_factory() -> Any:
        # Keyed by workflow **and** node, resolved from the run rather than
        # from the compile: two documents in one process can both hold an
        # `agent_1`, and one agent **node** must never be able to reach
        # another node's tasks. Two *conversations* on this same node do
        # share this desk — that is deliberate, and the filtering happens on
        # the read (`abc/async_task_middleware._announce`).
        # `run_identity()` answers `{}` outside a run, which keys a
        # scripted call under `":<node id>"` — deliberate, and the only
        # honest key available when nothing has said which workflow this is.
        slug = run_identity().get("workflow_slug", "")
        return desk_for(f"{slug}:{node_id}", launchers)

    return AsyncTaskMiddleware(subagents=specs, desk_factory=desk_factory)
