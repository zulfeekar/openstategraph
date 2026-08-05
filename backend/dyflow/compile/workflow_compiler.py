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

#: Port types that carry **control flow**. Everything else is a binding.
CONTROL_PORT_TYPES = frozenset({"text", "result"})

#: Port types that bind a capability to a node rather than sequencing it.
BINDING_PORT_TYPES = frozenset({"tool", "skill"})

ROUTER_TYPE = "route.classifier"
GRADER_TYPE = "route.grader"


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
    ) -> Any:
        """Assembles the graph.

        `node_factory` supplies the callable for each node, so the compiler owns
        *topology* and knows nothing about models, prompts or tools. That split is
        what lets the whole structure be tested without an API key.
        """
        plan = self.plan(document)
        nodes = {n["id"]: n for n in document.get("nodes", [])}
        builder = StateGraph(state_schema)

        for node_id in plan.nodes:
            builder.add_node(safe_name(node_id), node_factory(node_id, nodes[node_id], plan))

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

        for node_id in plan.entry:
            builder.add_edge(START, safe_name(node_id))
        for node_id in plan.exits:
            builder.add_edge(safe_name(node_id), END)

        return builder.compile() if compile_graph else builder

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
