"""`orchestrate.supervisor` and `orchestrate.worker` — one plan, fanned out.

Two families and one reason to change: **how a plan becomes several steps and
comes back as one.** The supervisor writes `subtasks` and LangGraph's `Send`
does the fan-out; a worker writes `worker_results` under the subtask's own id
and nothing else. They are one module because the contract between them —
which channel carries what, and under whose key — is the thing that breaks,
and it breaks in the gap between two files just as readily as inside one.

`CLAUDE.md` records the failure this pair produced and why both channels carry
named reducers rather than bare scalars: a real graph combining a router,
`Send` fan-out and several tool-using workers scheduled two `answer`-writing
nodes in the same superstep, and LangGraph raised `InvalidUpdateError` on a
field every single-writer test had exercised without incident.

`compile/nodes/__init__.py` carries the argument for the package and the
binding mechanism.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openstategraph.compile.state import RunState
from openstategraph.abc.orchestrator import BaseOrchestrator, orchestrator_for
from openstategraph.compile.context import (
    _text,
    advisor_context,
    held_tools_context,
)
from openstategraph.compile.fields import _replaces_rules
from openstategraph.compile.reporting import tool_report
from openstategraph.compile.silent_turn import text_or_ask_again
from openstategraph.compile.state import (
    _thread_question,
    _upstream_text,
    _wired_skill,
)
from openstategraph.compile.workflow_compiler import CompiledPlan

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


def _orchestrator(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """Splits its instruction into subtasks and writes the plan to state.

    Does **not** dispatch. Dispatch is the compiler's `_fan_out_router`,
    reading exactly what this writes — the same node-decides /
    edge-dispatches split as the router and the grader.

    **The body is `async def`, and it was the last of Phase D's four
    families to become one** (`async-first/10`, closing `async-first/06`).
    It is the only one whose I/O does not belong to it: the closure below
    makes no model call, it calls the planner, and both calls a plan can
    make live two rungs down the published ladder. So it waited for
    `async-first/05` — and for `aplan` specifically, which awaits `asplit`
    and `alabel` rather than only itself. A `def` body ran in a worker
    thread that a stopped run cannot interrupt; an `async def` body that
    then called the synchronous `plan()` would have been worse still,
    holding the event loop for the same uninterruptible call.

    The synchronous callers are unaffected and carry nothing for it:
    `compile/node_doors.py` puts a sync door over this same body at the
    compiler's own `add_node`. That door is **not** cancellable and cannot
    be — it preserves today's behaviour rather than improving it.
    """
    from openstategraph.abc.orchestrator import (
        Archetype,
        archetype_key,
        default_worker_node,
    )

    data = node.get("data") or {}
    cap = int(data.get("maxSubtasks") or 8)
    # The model makes up to two calls: the plan itself, where the card
    # carries rules (ticket 15), and archetype labelling where more than
    # one worker is wired (ticket 37's hybrid routing). A rule-less card
    # with one archetype still makes neither, which is what keeps the
    # deterministic path free.
    supervisor_model = self._resolve_model(data, node_id)

    def planner_for(skill: str, run_ctx: str = "") -> BaseOrchestrator:
        """Built per call, and deliberately not memoised.

        `run` below already says why — the wired skill varies per run and
        `notes` is a per-run sink two concurrent runs must not share. Said
        again here because it is also the answer to
        `launch-readiness/182`'s fourth question: the agent family's memo
        was keyed on the rendered run-context block and outlived every run,
        and a reader checking whether the same defect lives in the other
        three prompted families should find the answer at the factory
        rather than have to re-derive it. Nothing here is kept.
        """
        return orchestrator_for(
            max_subtasks=cap,
            # `"rules"`, not `"instruction"`. `instruction` is this node's
            # input *port* id (`src/nodes/orchestrate/OrchestratorNode.ts`),
            # and a port id is not a data key — no card, inspector or
            # document could write it, so this argument was `""` for every
            # supervisor ever built and a developer had no way to shape
            # dispatch at all. `backend/tests/test_data_key_contract.py` is
            # the general guard that now makes the whole class of this
            # mistake fail a test.
            rules=_text(data, "rules"),
            skill=skill,
            replace_rules=_replaces_rules(data),
            model=supervisor_model,
            context=run_ctx,
        )

    # The wired worker archetypes, in edge order — the same roster the
    # compiler's dispatch map is built from, keyed by the same
    # `archetype_key`, so a label the planning prompt offered is exactly
    # a key the fan-out router can resolve.
    archetypes = []
    worker_nodes = [
        {**(self._nodes.get(worker_id) or {}), "id": worker_id}
        for worker_id in plan.fan_out.get(node_id, [])
    ]
    # Which archetype an unlabelled subtask actually reaches, resolved by
    # the same function the compiler's fan-out router uses, so the record
    # this node writes (ticket 17) cannot disagree with the dispatch.
    default_key = archetype_key(default_worker_node(worker_nodes) or {})
    for worker_node in worker_nodes:
        worker_id = str(worker_node.get("id") or "")
        worker_data = worker_node.get("data") or {}
        # A labelling model can only route what it can see: with no
        # `role` set, describe the worker by the tools actually bound to
        # it — observed live (ticket 61): four undescribed archetypes had
        # GDP routed to Wikipedia and weather to a tool-less worker.
        role = _text(worker_data, "role")
        if not role:
            described = []
            for tool_node_id in plan.tool_bindings.get(worker_id, []):
                tool_type = str((self._nodes.get(tool_node_id) or {}).get("type", ""))
                tool = self.services.tools.get(tool_type)
                described.append(
                    getattr(tool, "description", None) or tool_type or tool_node_id
                )
            role = "handles: " + "; ".join(described) if described else ""
        archetypes.append(
            Archetype(
                key=archetype_key(worker_node),
                name=str(worker_node.get("title") or "").strip() or worker_id,
                description=role,
            )
        )
    upstream = [src for src, dst in plan.edges if dst == node_id]
    # Same feedback-trust rule as `_agent` (audit 2026-08): `feedback` is
    # `keep_latest_nonempty`, so a later pass's "" can never clear it.
    # Only feedback whose deciding node's revise/rejected edge targets
    # THIS orchestrator — and whose latest decision is still that label —
    # may be folded into a replan; anything else is a stale rejection (or
    # another branch's) dispatched into every subtask as if it were live.
    feedback_sources = self._feedback_sources(node_id, plan)
    skills = plan.skill_bindings.get(node_id, [])

    async def run(state: RunState) -> dict[str, Any]:
        instruction = _upstream_text(state, upstream) or state.get("question", "")
        if instruction == state.get("question", ""):
            instruction = _thread_question(state)
        decisions = state.get("decisions") or {}
        feedback = state.get("feedback", "")
        if not any(
            decisions.get(src) in ("revise", "rejected") for src in feedback_sources
        ):
            feedback = ""
        generation = state.get("attempts", 0)
        skill = _wired_skill(state, skills, self.static_sources)
        # Rebuilt per run rather than once at compile time: the wired skill
        # text can vary by run, and `notes` below is a per-run sink that
        # must not be shared between two concurrent runs of one graph.
        planner = planner_for(skill, self._run_context_section())
        notes: list[str] = []
        # `aplan`, and not `plan` inside an `async def` — the distinction
        # `async-first/10` exists for. This closure makes no model call of
        # its own; both of the calls a plan can make are two rungs down the
        # published ladder (`PlanningOrchestrator.asplit`'s planning call,
        # `BaseOrchestrator.alabel`'s archetype labelling), which is why
        # the ladder grew **three** async verbs rather than one. Awaiting
        # only the outer verb would have moved a model call from a pool
        # thread onto the event loop — strictly worse than the `def` body
        # this replaced, and cancellable by nothing.
        subtasks = await planner.aplan(
            instruction,
            generation=generation,
            archetypes=archetypes,
            # Into the plan, not appended after it (ticket 23). A
            # deterministic splitter ignores it and behaves exactly as it
            # always has; a model-driven one can come back with a
            # different division of labour, which is the only thing that
            # makes this port's name true.
            feedback=feedback,
            notes=notes,
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
        # Which archetype each subtask was dispatched to (ticket 17). A
        # run of a two-archetype supervisor — a node whose entire
        # behaviour is a *choice* — used to return `decisions: {}`, so the
        # one thing it decided was the one thing nowhere in the result.
        #
        # `<node id>#<task id>`, flat and string-valued, because that is
        # what `decisions` is at the run/stream seam (`dict[str, str]`, in
        # Pydantic and in `RuntimeClient.ts`): a nested map here would be
        # a contract change on both. `#` and not `/` — a `/` in one of
        # these maps already means a *mount path* (`RunResult.nested`),
        # and one separator cannot mean two things.
        #
        # An unlabelled subtask records the archetype it actually reached
        # *and* says it got there by default, so the case ticket 17 calls
        # unobservable — a label the model invented, validated away, and
        # collapsed onto the default worker — reads differently from a
        # label the model chose.
        dispatch = {
            f"{node_id}#{task.id}": task.archetype
            or (f"{default_key} (default)" if default_key else "(default)")
            for task in subtasks
        }
        planned = f"Planned {len(subtasks)} subtask(s)."
        return {
            "subtasks": {node_id: [t.model_dump() for t in subtasks]},
            "decisions": dispatch,
            # The ceiling's casualties ride the node's own output because
            # that is the run-time channel every surface already renders:
            # `.warnings` is materialised at load time on the library path
            # (`loader.load_workflow`), so nothing a *run* discovers can
            # reach it without a new state key. Silence was the bug.
            "outputs": {node_id: " ".join([planned, *notes])},
            "attempts": generation + 1,
        }

    return run


def _worker(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
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
    whenever no skill is wired to it, so a worker needs a floor. The
    directive is the `default_rules` layer: a wired skill is added to it,
    and only `rulesMode: "replace"` drops it.

    **The prompt is passed as `create_agent(system_prompt=...)`, not
    prepended as a message.** The first version of this fix kept the
    prompt text but delivered it as a `SystemMessage` stitched into the
    per-invocation `messages` list, on an agent built once with no
    `system_prompt` at all — unlike `workflows/chinook-assistant/agents.py`'s
    `build_sql_agent`, the one place this exact directive style was
    already proven to work, which passes its prompt as `create_agent`'s
    own `system_prompt` parameter. Matching that shape (agent built fresh
    per invocation, since the skill text can vary by run) rather than
    approximating it with a hand-assembled message list removes a
    variable between the working case and this one.
    """
    from langchain_core.messages import HumanMessage

    lc_tools = self._bind_tools(node_id, plan)
    #: Canvas-wired only, snapshotted before the ambient tools below — see
    #: the identical line in `_agent` for why the finished list would have
    #: made almost every workflow look tool-bearing.
    wired = [t.name for t in lc_tools]

    # Workers are agents too: the ambient knowledge rule applies (deduped
    # against an explicitly wired atom, same as `_agent`).
    self._attach_ambient_knowledge(lc_tools)

    skills = plan.skill_bindings.get(node_id, [])
    # The worker is an agent too: its card carries the same `model` select
    # as every model-driven node, and `_resolve_model`'s docstring records
    # exactly this class of bug — a visible per-node choice silently
    # ignored for the graph-wide default (audit 2026-08).
    data = node.get("data") or {}
    # Same statement about a worker as about an agent (ticket 89); a
    # worker writes its prose in `role`.
    self._report_stale_tool_denial(node_id, data, wired)
    model = self._resolve_model(data, node_id)
    # **The `role` field reaches the worker itself** (ticket 16). It used
    # to reach exactly one place — `_orchestrator`, which packs it into
    # `Archetype.description` for the *supervisor's* labelling call — so
    # it described the worker to the router and said nothing to the
    # worker. A card reading "at most three short bullet points, no
    # headings" returned a ten-row Markdown table, live, and nothing was
    # wrong: the text was never sent. With a single archetype wired,
    # `label()` returns early and the field was inert entirely.
    #
    # **Context, not rules.** It is what this worker *is* — the same
    # sentence the roster shows the supervisor — so it sits above the
    # rules layers and outside what `rulesMode: replace` can delete. A
    # wired skill still customises behaviour and still wins ties; the
    # worker's identity is not something a skill should have to restate.
    role = _text(data, "role")
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

    # **`async def`, second of Phase D** (`async-first/06`), and the family
    # where the abandoned-work bill is largest: a `Send` fan-out dispatches
    # N copies of this one node, so a stop mid-fan-out abandons N model
    # calls rather than one. That is the ~75 s in `_stream_run`'s
    # `GeneratorExit` handler — seconds of model work billed after the run
    # was stopped, per `async-first/09`'s relabelling, never latency a user
    # waits through. The same reasoning as `_agent`'s: on this version of
    # LangGraph only an `async def` body can be cancelled at all.
    async def run(state: RunState) -> dict[str, Any]:
        task_id = state.get("task_id", "")
        instruction = state.get("task_instruction", "")

        if model is None:
            # `worker_results` stays empty — it is the join's input, and a
            # sentence about our configuration published there would reach
            # `format_report` as if it were the subtask's answer. The
            # record of the step goes in `outputs`, where every surface
            # already reads it, carrying the marker that tells the silent
            # channel *which* kind of nothing this is. Before this the
            # branch wrote no `outputs` entry at all, so the step was
            # invisible everywhere (`workflow-gallery` 18).
            from openstategraph.compile.workflow_compiler import NO_MODEL_MARKER

            return {
                "worker_results": {task_id: ""},
                "outputs": {f"{node_id}#{task_id}": NO_MODEL_MARKER},
            }

        # Same ladder as `_agent`: the family owns construction, this
        # factory owns state plumbing. The workflow's skills text is
        # generated *context*, and SystemPrompt owns the ordering (context
        # above rules, contract last) — concatenating it into `rules`
        # bypassed that composition (audit 2026-08).
        #
        # The tool directive is the **default_rules** layer and the wired
        # file is the **skill** layer, exactly as
        # `docs/decisions/skill-layer.md` names them — that document cites
        # this worker's directive as the archetypal `default_rules`, and
        # cites extending it as the safe direction, because the directive
        # is what stopped a worker answering a database question from
        # parametric memory. This used to be `wired or default`, i.e.
        # `replace` hardcoded: a skill silently deleted the directive, and
        # `rulesMode` was the one prompted node's switch that reached
        # nothing (ticket 05).
        from openstategraph.abc import agent as agent_family

        agent = agent_family.ReactAgentNode(
            name=f"worker_{node_id}",
            model=model,
            tools=lc_tools,
            default_rules=default_prompt,
            skill=_wired_skill(state, skills, self.static_sources),
            replace_rules=_replaces_rules(data),
            context="\n\n".join(
                part
                for part in (
                    f"Your role on this team:\n{role}" if role else "",
                    # Ambient, package-wide `skills/*.md`: house style for
                    # every model-driven node here, not a choice about
                    # this one. Context, and it stays context.
                    self.services.skills_context,
                    # And what it holds (production-ready 88). Composed
                    # here as well as in `_agent` for the reason the block
                    # below already records about `advisor_context`: a
                    # sentence that exists in one factory and not the other
                    # is a worker deserving less for no reason anybody
                    # chose.
                    held_tools_context(lc_tools),
                    # The same way out of a capability gap `_agent` has
                    # had all along, and the reason this was added
                    # (`every-workflow-green` 19): a worker with no tools
                    # wired had no way to say it was stuck, so it narrated
                    # instead — "Let's search.Let's actually run the
                    # search.Search." was published as the report on
                    # `archetype-orchestrator-report`, which wires no tool
                    # nodes at all.
                    #
                    # An agent in the identical position already answers
                    # "I don't have a tool that can do that" and emits one
                    # suggestion the editor turns into an Add & re-run
                    # card. Nothing about a worker made it deserve less;
                    # `advisor_context` was simply composed into one
                    # factory and not the other. Same call, same
                    # arguments, same position — above the rules, so
                    # `SystemPrompt` still keeps the output contract last.
                    advisor_context(node_id, self.services.advisor_catalog),
                    # And what this run was started with
                    # (`organisms-first-class/72`). Composed here as well
                    # as in `_agent` for the reason the block above already
                    # records: a sentence in one factory and not the other
                    # is a worker deserving less for no reason anybody
                    # chose.
                    self._run_context_section(),
                )
                if part
            ),
        ).build()
        result = await agent.ainvoke({"messages": [HumanMessage(content=instruction)]})
        out = result.get("messages") or []
        # The same second ask `_agent` makes, for the same measured reason
        # (`launch-readiness/185`), and this is the site whose silence
        # `silent_node_warnings` already has a sentence for: a member that
        # ran its tools and then wrote nothing leaves one section of the
        # joined report empty, and the join has no way to fill it.
        text = await text_or_ask_again(out, model)
        return {
            "worker_results": {task_id: text if isinstance(text, str) else str(text)},
            # What this worker was refused, keyed by **node** id and not by
            # task id — `suggestion_from_rejection` builds an `attachTo`
            # out of it, and a card can only be applied if it names a node
            # that is actually on the canvas. Every dispatched instance
            # shares one node id, so two subtasks refused the same tool
            # merge to one offer, which is the right number of cards
            # (ticket 36).
            **tool_report(
                node_id, out, wired, self._unbound_capabilities.get(node_id, ())
            ),
            # Which worker node ran which subtask (ticket 17). Every
            # dispatched instance shares one node id, so the task id is
            # what keeps them apart — the same reason `worker_results` is
            # keyed that way. Separate from `worker_results` because that
            # map is the join's input and this is the run's record.
            "outputs": {
                f"{node_id}#{task_id}": text if isinstance(text, str) else str(text)
            },
        }

    return run
