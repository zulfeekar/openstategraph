"""``workflow.json`` → a LangGraph ``StateGraph``.

This is the compile seam, and it is **one-directional** (ticket 23): the document
flows in, a runnable graph comes out, and nothing reads runtime objects back into
the editor's model.

The single most important thing this file knows: **not every edge is a graph
edge.** A canvas edge means different things depending on the port it lands on.

| Target port type | Meaning | Becomes |
| --- | --- | --- |
| `tool` | this tool is available to that agent | a **binding**, no graph edge |
| `skill` | this text shapes the agent's prompt | a **binding**, no graph edge |
| `text`, `result` | control flow | `add_edge` |
| `feedback` | a grader's rejection returning upstream | part of a **conditional** edge |

Getting that wrong is not a subtle bug: treating a tool link as control flow would
put the tool node *in the execution order*, so it would run once on its own before
the agent ever called it — and the agent would then also call it, silently doubling
the work. Treating a feedback link as an ordinary edge would create an all-static
cycle, which can never terminate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from dyflow.abc.orchestrator import archetype_key

#: `TimeoutPolicy` was added in `langgraph>=1.2`.
try:
    from langgraph.types import TimeoutPolicy
except ImportError:
    TimeoutPolicy = None  # type: ignore[misc,assignment]

#: `NodeError` was added in `langgraph>=1.2`; gracefully degrade if absent.
try:
    from langgraph.errors import NodeError
except ImportError:
    NodeError = None  # type: ignore[misc,assignment]

#: Port types that carry **control flow**. Everything else is a binding.
CONTROL_PORT_TYPES = frozenset({"text", "result"})

#: Port types that bind a capability to a node rather than sequencing it.
BINDING_PORT_TYPES = frozenset({"tool", "skill"})

ROUTER_TYPE = "route.classifier"
GRADER_TYPE = "route.grader"
ORCHESTRATOR_TYPE = "orchestrate.supervisor"
WORKER_TYPE = "orchestrate.worker"
#: Ticket "human-in-the-loop": pauses via `interrupt()` and dispatches on a
#: human decision, the same node-decides/edge-dispatches split as the router
#: and the grader — see the conditional-edge handling below.
HUMAN_APPROVAL_TYPE = "human.approval"

#: The port type that marks a fan-out declaration rather than control flow or a
#: capability binding. An edge landing on a `worker`-typed port means "this is
#: the node Send() dispatches to," not "this runs next."
WORKER_PORT_TYPE = "worker"


def _default_error_handler(state: dict[str, Any], error: NodeError) -> dict[str, Any]:
    """Runs once a node's retries are exhausted. Recovers, never crashes.

    The `error: NodeError` annotation is **load-bearing**, not documentation:
    current langgraph injects the failure context only into a parameter that
    is both *named* `error` and *annotated* `NodeError` (class or the literal
    string — this module's `from __future__ import annotations` makes it the
    string, which the matcher accepts). An untyped `error` parameter is not
    injected at all, and the handler then dies on arity — found when a
    langgraph upgrade silently broke every fault-tolerance test.

    Deliberately returns a plain state update rather than a `Command`: with
    no `goto`, LangGraph continues along the node's own already-declared
    edges exactly as if it had returned this value normally — no routing
    knowledge is needed here, which matters because this handler is generic
    across every node type a workflow might contain.

    Writing the failure into `outputs[node]` (the same channel every node
    factory already writes its result to — see `node_runtime.py`) means a
    failed node still produces *something* a downstream node or the final
    report can read, instead of the whole run aborting because one Chinook
    tool call or one dispatched worker had a bad day. This is the graph-
    assembly-level version of `_grader`'s own rule: a candidate that failed
    is still evidence, not a reason to discard the run.
    """
    exc = getattr(error, "error", error)
    node = getattr(error, "node", "unknown")
    message = f"{type(exc).__name__}: {exc}"
    return {"outputs": {node: f"[{node} failed after retries: {message}]"}}


def _node_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """`add_node` kwargs for one node's own retry/timeout override, if set.

    `set_node_defaults` (in `build`, below) already gives every node the
    same graph-wide retry policy — this is the *per-node* override the
    canvas's `maxRetries`/`timeoutSeconds` fields expose (declared once in
    `ModelRegistry.defineNode` on the TS side, inherited by every executable
    node type). Per LangGraph's own docs: "Per-node values still take
    precedence" over `set_node_defaults`, so passing these as `add_node`
    kwargs is the correct override mechanism, not a parallel one.

    Both fields are blank strings by default (`FieldValue` has no `None`
    default for a `text` field of this shape) — blank means "no override,
    use the graph default", not "zero" or "unbounded". A non-numeric or
    non-positive value is treated the same as blank: the frontend's own
    `validate` already rejects those before a document can be saved with
    one, so reaching this function with garbage means the value predates
    validation being added, not a case to crash on.
    """
    overrides: dict[str, Any] = {}

    max_retries = str(data.get("maxRetries") or "").strip()
    if max_retries:
        try:
            n = int(max_retries)
            if n > 0:
                overrides["retry_policy"] = RetryPolicy(
                    max_attempts=n, initial_interval=1.0, backoff_factor=2.0
                )
        except ValueError:
            pass

    timeout_seconds = str(data.get("timeoutSeconds") or "").strip()
    if timeout_seconds and TimeoutPolicy is not None:
        try:
            seconds = float(timeout_seconds)
            if seconds > 0:
                overrides["timeout"] = TimeoutPolicy(run_timeout=seconds)
        except ValueError:
            pass

    return overrides


def safe_name(node_id: str) -> str:
    """A graph-legal name for a workflow node id.

    LangGraph **reserves `:`** in node names, and our ids look like
    `node:agent.llm-1`, so they cannot be used verbatim — `add_node` raises. Found
    by compiling a document actually exported from the canvas; every hand-written
    fixture had used simple ids and sailed past it.

    Derived from the id rather than the label, because LangGraph treats a node
    name as identity: renaming a node would otherwise break an interrupted
    thread (ticket 04).
    """
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in node_id)


@dataclass(frozen=True)
class PortSpec:
    """What the compiler needs to know about one port."""

    type: str
    direction: str


#: Port types per node type.
#:
#: **Known duplication, deliberately visible.** The authoritative definitions
#: live in the TypeScript node catalogue, and CLAUDE.md forbids hand-mirroring a
#: type across the boundary. This table exists so the compiler works today and is
#: **injectable** (see `port_resolver`) so it can be replaced by generated output
#: without touching the compiler. Ticket 02 owns that generation; until then, a
#: node type added in TypeScript and not added here compiles as an opaque node
#: with control-flow edges, which is the safe default rather than a crash.
DEFAULT_PORT_SPECS: dict[str, dict[str, PortSpec]] = {
    "input.text": {"text": PortSpec("text", "out")},
    "input.markdown": {"skill": PortSpec("skill", "out")},
    "agent.llm": {
        "prompt": PortSpec("text", "in"),
        "skill": PortSpec("skill", "in"),
        "tools": PortSpec("tool", "in"),
        "feedback": PortSpec("feedback", "in"),
        "result": PortSpec("result", "out"),
    },
    "output.formatted": {"result": PortSpec("result", "in")},
    GRADER_TYPE: {
        "candidate": PortSpec("result", "in"),
        "pass": PortSpec("result", "out"),
        "revise": PortSpec("feedback", "out"),
    },
    ROUTER_TYPE: {"question": PortSpec("text", "in")},
    ORCHESTRATOR_TYPE: {
        "instruction": PortSpec("text", "in"),
        # The other half of the only legal cycle (ticket 09): a grader's
        # `revise` may close a loop here too, so a failed report can send the
        # orchestrator back to re-plan with more subtasks — a strictly harder
        # case than looping over one agent node, since the cycle re-enters a
        # fan-out/join subgraph rather than a single call.
        "feedback": PortSpec("feedback", "in"),
        "workers": PortSpec(WORKER_PORT_TYPE, "out"),
    },
    WORKER_TYPE: {
        "dispatch": PortSpec(WORKER_PORT_TYPE, "in"),
        # Found live: these two were missing entirely, so an edge into either
        # fell through `default_port_resolver`'s "unknown port" fallback and
        # was treated as ordinary control flow rather than a binding — a
        # worker with tools wired on the canvas silently ran with none,
        # because `plan.tool_bindings` never saw the edge. `lc_tools` came
        # back empty, `default_prompt` fell back to `""`, and the model
        # answered from parametric knowledge with nothing to ground it.
        "skill": PortSpec("skill", "in"),
        "tools": PortSpec("tool", "in"),
        "result": PortSpec("result", "out"),
    },
    "function.format_report": {
        "candidate": PortSpec("result", "in"),
        "report": PortSpec("result", "out"),
    },
    HUMAN_APPROVAL_TYPE: {
        "candidate": PortSpec("result", "in"),
        "approved": PortSpec("result", "out"),
        "rejected": PortSpec("feedback", "out"),
    },
}


def default_port_resolver(node_type: str, port_id: str) -> PortSpec:
    """Best-effort port lookup.

    A router's outputs are `branch:<slug>` and generated from config, so they are
    matched by prefix rather than enumerated.
    """
    if node_type == ROUTER_TYPE and port_id.startswith("branch:"):
        return PortSpec("text", "out")
    spec = DEFAULT_PORT_SPECS.get(node_type, {}).get(port_id)
    if spec is not None:
        return spec
    # Unknown port on a known-or-unknown type: assume control flow. Wrong in the
    # safe direction — an extra sequencing edge is visible in the Mermaid preview,
    # whereas a missed one silently drops a step.
    return PortSpec("text", "in" if port_id != "result" else "out")


@dataclass
class CompiledPlan:
    """What the compiler decided, before a `StateGraph` is built.

    Separated from the graph so it can be asserted directly in a test, inspected
    in the editor, and reused by the code generator — the generator and the
    interpreter must agree, and sharing this plan is what makes that true by
    construction rather than by discipline.
    """

    nodes: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    #: source node -> {branch label: destination node}
    conditional: dict[str, dict[str, str]] = field(default_factory=dict)
    #: agent node -> tool node names bound to it (not sequenced)
    tool_bindings: dict[str, list[str]] = field(default_factory=dict)
    #: agent node -> skill node names feeding its prompt
    skill_bindings: dict[str, list[str]] = field(default_factory=dict)
    #: Nodes that compile into a binding rather than a step, so are not graph nodes.
    bound_only: list[str] = field(default_factory=list)
    #: orchestrator node id -> the worker archetype nodes it dispatches
    #: `Send` to, in canvas edge order (ticket 37).
    #:
    #: A list per orchestrator, one entry per wired archetype — but still a
    #: *static* declaration: each entry is one node that absorbs however many
    #: dynamic task instances get labelled for it at runtime. LangGraph has no
    #: concept of a node that exists N times, only tasks dispatched N times
    #: against one node. Edge order matters: the first wired archetype is the
    #: default dispatch target when no card claims `default`.
    fan_out: dict[str, list[str]] = field(default_factory=dict)
    entry: list[str] = field(default_factory=list)
    exits: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class WorkflowCompiler:
    """Turns a stored document into a plan, then into a graph.

    Node *names* are the workflow's node ids, deliberately. LangGraph treats node
    names as identity — renaming one hard-breaks an interrupted thread, and
    subgraph checkpoint namespaces are assigned by call order (ticket 04). Ids are
    stable across renames and re-layouts; labels are not.
    """

    def __init__(
        self,
        *,
        port_resolver: Callable[[str, str], PortSpec] = default_port_resolver,
    ) -> None:
        self._port = port_resolver

    # ------------------------------------------------------------------ #
    # Planning
    # ------------------------------------------------------------------ #

    def plan(self, document: dict[str, Any]) -> CompiledPlan:
        plan = CompiledPlan()
        nodes = {n["id"]: n for n in document.get("nodes", [])}

        # Annotations and containers never execute, so they are not graph nodes.
        executable = {
            node_id: node
            for node_id, node in nodes.items()
            if not str(node.get("type", "")).startswith("annotate.")
        }

        has_incoming: set[str] = set()
        has_outgoing: set[str] = set()
        #: Nodes whose only participation is being *bound* to another node.
        bound_only: set[str] = set()
        #: Nodes that take part in control flow, and so are real graph nodes.
        in_control_flow: set[str] = set()

        for edge in document.get("edges", []):
            src, dst = edge.get("source") or {}, edge.get("target") or {}
            src_id, dst_id = src.get("nodeId"), dst.get("nodeId")
            if src_id not in executable or dst_id not in executable:
                plan.warnings.append(f"Dropped an edge with an unknown endpoint: {src_id} -> {dst_id}")
                continue

            src_type = str(executable[src_id].get("type", ""))
            dst_type = str(executable[dst_id].get("type", ""))
            dst_port = self._port(dst_type, dst.get("portId", ""))
            src_port = self._port(src_type, src.get("portId", ""))

            # --- fan-out: a dispatch target, not a step and not a binding ---
            #
            # Checked before BINDING_PORT_TYPES because a worker's "dispatch"
            # port is its own type, not a tool/skill capability — conflating
            # them would make the worker bind to the orchestrator as if it were
            # a tool, which is a different (and wrong) relationship.
            if dst_port.type == WORKER_PORT_TYPE:
                targets = plan.fan_out.setdefault(src_id, [])
                if dst_id not in targets:
                    targets.append(dst_id)
                has_outgoing.add(src_id)
                # The worker has no *static* incoming edge — LangGraph dispatches
                # it dynamically via Send — but it is reached, so it must not be
                # treated as an entry and wired from START. Same precedent as the
                # grader's `revise` edge.
                has_incoming.add(dst_id)
                in_control_flow.update((src_id, dst_id))
                continue

            # --- bindings: capability, not sequence ---
            if dst_port.type in BINDING_PORT_TYPES:
                bucket = (
                    plan.tool_bindings if dst_port.type == "tool" else plan.skill_bindings
                )
                bucket.setdefault(dst_id, []).append(src_id)
                # A bound node is **not a graph node at all**. It compiles into
                # the agent's tool list, not into a step.
                #
                # Getting this half-right is worse than getting it wrong: an
                # earlier version only excluded it from `exits`, so it still had
                # no incoming edge, became an `entry`, and got wired from START —
                # meaning the tool ran once on its own at graph start *and* again
                # when the agent called it. Exactly the doubling this whole
                # distinction exists to prevent, and the unit tests missed it
                # because they only asserted `exits`.
                bound_only.add(src_id)
                continue

            # --- the router: one conditional edge per branch ---
            if src_type == ROUTER_TYPE:
                branch = src.get("portId", "").removeprefix("branch:")
                plan.conditional.setdefault(src_id, {})[branch] = dst_id
                has_outgoing.add(src_id)
                has_incoming.add(dst_id)
                in_control_flow.update((src_id, dst_id))
                continue

            # --- the grader: pass continues, revise loops back ---
            if src_type == GRADER_TYPE:
                label = "revise" if src_port.type == "feedback" else "pass"
                plan.conditional.setdefault(src_id, {})[label] = dst_id
                has_outgoing.add(src_id)
                # A revise edge deliberately does **not** mark its destination as
                # having an incoming edge: the loop target is usually the entry
                # node, and counting it would leave the graph with no entry at
                # all and nothing wired to START.
                if label == "pass":
                    has_incoming.add(dst_id)
                in_control_flow.update((src_id, dst_id))
                continue

            # --- human approval: same node-decides/edge-dispatches split as
            # the grader, just with a human's decision instead of an LLM's.
            # Labels are the literal port ids ("approved"/"rejected"), not
            # translated to "pass"/"revise" — a rejection here does not loop
            # back to a retry the way a grader's revise does, it takes a
            # different, deliberately-wired path (e.g. straight to an
            # explanatory Output), so borrowing the grader's own vocabulary
            # would misdescribe what actually happens on this edge.
            if src_type == HUMAN_APPROVAL_TYPE:
                label = src_port_id if (src_port_id := src.get("portId", "")) else "approved"
                plan.conditional.setdefault(src_id, {})[label] = dst_id
                has_outgoing.add(src_id)
                has_incoming.add(dst_id)
                in_control_flow.update((src_id, dst_id))
                continue

            # --- ordinary control flow ---
            plan.edges.append((src_id, dst_id))
            has_outgoing.add(src_id)
            has_incoming.add(dst_id)
            in_control_flow.update((src_id, dst_id))

        # A node that is only ever bound is excluded; an isolated node is kept,
        # because a lone node on a fresh canvas should still be runnable.
        plan.nodes = sorted(
            node_id
            for node_id in executable
            if node_id not in bound_only or node_id in in_control_flow
        )
        plan.bound_only = sorted(bound_only - in_control_flow)

        plan.edges.sort()
        plan.entry = sorted(n for n in plan.nodes if n not in has_incoming)
        plan.exits = sorted(n for n in plan.nodes if n not in has_outgoing)

        if not plan.entry and plan.nodes:
            plan.warnings.append("No entry node: every node has an incoming edge")

        # Two archetypes with one dispatch key cannot both be reachable — the
        # later one silently shadows the earlier in the dispatch map. Warn at
        # plan time, where the collision is a document fact, not a run fact.
        for orchestrator_id, worker_ids in plan.fan_out.items():
            if len(worker_ids) < 2:
                continue
            keys = [archetype_key(nodes[w]) for w in worker_ids if w in nodes]
            duplicates = {k for k in keys if keys.count(k) > 1}
            if duplicates:
                plan.warnings.append(
                    f"Orchestrator {orchestrator_id!r} has workers sharing an "
                    f"archetype key ({', '.join(sorted(duplicates))}); retitle "
                    "the workers so every archetype is dispatchable"
                )
        return plan

    # ------------------------------------------------------------------ #
    # Building
    # ------------------------------------------------------------------ #

    def build(
        self,
        document: dict[str, Any],
        state_schema: type,
        node_factory: Callable[[str, dict[str, Any], CompiledPlan], Any],
        *,
        compile_graph: bool = True,
        checkpointer: Any = None,
    ) -> Any:
        """Assembles the graph.

        `node_factory` supplies the callable for each node, so the compiler owns
        *topology* and knows nothing about models, prompts or tools. That split is
        what lets the whole structure be tested without an API key.

        `checkpointer` is what makes a `human.approval` node's `interrupt()`
        actually able to pause: LangGraph raises at compile time if a graph
        containing an interrupt has no checkpointer at all. Optional and
        `None` by default — a graph with no human-in-the-loop node has
        nothing to checkpoint, and passing one unconditionally would give
        every run persisted state it never asked for.
        """
        plan = self.plan(document)
        nodes = {n["id"]: n for n in document.get("nodes", [])}
        builder = StateGraph(state_schema)

        # Graph-assembly parameters, never a node concern (CLAUDE.md): every
        # node gets the same retry/error-recovery policy from one place,
        # rather than each node factory reimplementing its own backoff loop.
        # `max_attempts=3` with exponential backoff is not a theoretical
        # nicety here — a live run this session hit a real, transient
        # `ollama._types.ResponseError` (a cloud-provider 500) that a bare
        # retry resolved on the next attempt. `default_retry_on` (the
        # library default) already excludes programming errors
        # (`ValueError`, `TypeError`, ...), so this does not mask a bug by
        # retrying it into a timeout.
        default_retry = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0)
        has_graph_defaults = hasattr(builder, "set_node_defaults")
        if has_graph_defaults:
            builder.set_node_defaults(
                retry_policy=default_retry,
                error_handler=_default_error_handler,
            )

        for node_id in plan.nodes:
            overrides = _node_overrides(nodes[node_id].get("data") or {})
            if not has_graph_defaults and "retry_policy" not in overrides:
                # `langgraph<1.2` has no graph-wide defaults, and the earlier
                # fallback comment here claimed `_node_overrides` covered it —
                # it does not: overrides only exist when a card sets
                # `maxRetries`. That left every node retry-less, so one
                # transient Ollama 500 emptied a fan-out worker's result or
                # 502'd the whole run (found live, ticket 61). The default is
                # applied per node instead; an explicit override still wins.
                overrides = {**overrides, "retry_policy": default_retry}
            builder.add_node(
                safe_name(node_id), node_factory(node_id, nodes[node_id], plan), **overrides
            )

        for src, dst in plan.edges:
            builder.add_edge(safe_name(src), safe_name(dst))

        for src, destinations in plan.conditional.items():
            if not destinations:
                continue
            builder.add_conditional_edges(
                safe_name(src),
                self._router_for(src, destinations),
                # The complete declared destination set. Without it every
                # renderer must assume the router reaches any node (ticket 03).
                {label: safe_name(dst) for label, dst in destinations.items()},
            )

        for orchestrator_id, worker_ids in plan.fan_out.items():
            # key -> graph node name. First writer wins on a collision, which
            # matches the plan-time warning above: the shadowed worker is
            # unreachable and the developer was told.
            archetype_map: dict[str, str] = {}
            for worker_id in worker_ids:
                worker_node = nodes.get(worker_id) or {}
                archetype_map.setdefault(archetype_key(worker_node), safe_name(worker_id))
            # Exactly one default is the validated shape; the first card
            # claiming it wins here so a mis-authored document still runs,
            # and with none claimed the first wired archetype is the default.
            default_worker = next(
                (
                    w
                    for w in worker_ids
                    if ((nodes.get(w) or {}).get("data") or {}).get("default")
                ),
                worker_ids[0],
            )
            builder.add_conditional_edges(
                safe_name(orchestrator_id),
                self._fan_out_router(orchestrator_id, archetype_map, safe_name(default_worker)),
                # The complete declared destination set: every wired archetype.
                # Still static — N dynamic tasks per archetype node (ticket 27).
                [safe_name(w) for w in worker_ids],
            )

        for node_id in plan.entry:
            builder.add_edge(START, safe_name(node_id))
        for node_id in plan.exits:
            builder.add_edge(safe_name(node_id), END)

        if not compile_graph:
            return builder
        return builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()

    @staticmethod
    def _fan_out_router(
        orchestrator_id: str,
        archetype_map: dict[str, str],
        default_worker: str,
    ) -> Callable[[Any], list[Any]]:
        """Reads the orchestrator's plan and dispatches one `Send` per subtask.

        Hybrid routing (ticket 37): each subtask carries the archetype key the
        orchestrator labelled it with, and the key resolves to that archetype's
        node through `archetype_map`. A key that resolves to nothing — the
        model invented a label, or labelling failed and left `""` — dispatches
        to `default_worker` rather than raising: a misroute degrades to the
        single-archetype behaviour this graph had before archetypes existed.

        This is the one place `Send` is constructed, deliberately outside the
        orchestrator node itself. The node writes *what to do*
        (`state["subtasks"][id]`); this reads it and decides *how many times to
        do it* — the same node-decides / edge-dispatches split already used for
        the router and the grader, so all three "which branch" mechanisms share
        one shape.

        **The payload is the worker's entire visible state — nothing more.**
        Verified directly against the installed langgraph: a `Send` payload does
        **not** merge with the parent graph state, it *replaces* what the
        dispatched node sees. So every worker instance receives exactly
        `task_id` and `task_instruction` and nothing else — no question, no
        schema hint, no upstream output — unless the orchestrator explicitly
        packs it into the subtask. This is stricter isolation than a
        tool-subagent, which at least receives the whole task description in
        its ToolMessage; here the isolation is structural, not a convention.
        """

        def route(state: Any) -> list[Any]:
            subtasks = (state.get("subtasks") or {}).get(orchestrator_id) or []
            return [
                Send(
                    archetype_map.get(task.get("archetype") or "", default_worker),
                    {"task_id": task["id"], "task_instruction": task["instruction"]},
                )
                for task in subtasks
            ]

        return route

    @staticmethod
    def _router_for(node_id: str, destinations: dict[str, str]) -> Callable[[Any], str]:
        """The `path` function for one conditional edge.

        Reads the decision a node already wrote to state rather than deciding
        again. A router node writes `branch`; a grader writes `verdict`. Falling
        back to the first declared destination keeps a run alive when a decision
        is missing — a stall here would be a hang, not an error.
        """
        default = next(iter(destinations))

        def route(state: Any) -> str:
            decisions = state.get("decisions") or {} if hasattr(state, "get") else {}
            chosen = decisions.get(node_id)
            if chosen in destinations:
                return chosen
            return default

        return route


__all__ = [
    "BINDING_PORT_TYPES",
    "CONTROL_PORT_TYPES",
    "CompiledPlan",
    "PortSpec",
    "WorkflowCompiler",
    "default_port_resolver",
    "safe_name",
]
