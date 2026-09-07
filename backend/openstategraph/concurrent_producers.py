"""How many of a port's incoming links can carry a value in the **same run**.

`osg-agent-experience/43`. `maxConnections` on an input exists because a slot
holds one value, and two producers writing it in one superstep is the ambiguity
the cap forbids. The canvas has enforced that since `workflow-gallery/64`; a
document written by anything other than the canvas — an agent composing
`workflow.json` through the MCP door, which is how the try project was built —
met no such rule, and fifteen edges arrived on a one-slot input with every
checker green.

**Why this is not a raw edge count.** A router takes exactly one of its
branches, so three branches converging on one agent's `prompt` are three links
and one value. Two of this repository's own shipped examples do exactly that
(`support-triage`'s grader `candidate`, `chinook-assistant`'s `out1.result`), so
a checker that counted links would have refused documents that are correct and
that ship.

**This mirrors `src/core/validation/concurrentProducers.ts`, and says so.**
CLAUDE.md forbids hand-mirroring a *type* across the boundary and this is not
one — it is the same question asked of a document by a runtime that has no
`WorkflowModel` to ask. Two deliberate differences from that file, both
recorded rather than discovered later:

- **Only the walking implementation is here.** The TypeScript side also has a
  dominator index, because `capacityRule` runs on every pointer-move of a drag
  and paid 153 ms for the walks on a 516-node document
  (`the-cost-of-one-more/03`). `validate` runs once, per document, per command.
  A faster implementation whose agreement with the exact one needs its own test
  is a cost with nothing here to buy.
- **The conservatism runs the other way, and it must.** On the canvas, an
  answer that is too *large* refuses a link somebody could have drawn, and an
  answer that is too small lets two values race into one slot — so that side
  over-counts on a guess. Here an answer that is too large is a **false
  accusation against a valid document**, which is the one thing a checker may
  never do (`document_checks`' own `values_outside_their_options` records the
  same rule). So this side under-counts on a guess: where the canvas asks
  `INodeModel.branchesAreExclusive` and treats a Router in *run every match, in
  parallel* as a node whose branches really can race, this treats every
  `branch` output as exclusive, because the mode is node data and the
  catalogue publishes no such fact. The gap is real and named: a parallel
  router whose branches converge on one slot is a document this will not
  report.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: Port types that wire *configuration*, not control flow — the same four
#: `controlFlowGraph.ts` names, for the same reason: walking them would report
#: an agent as reachable from its own tool palette, and a `feedback` edge
#: travels into the next superstep rather than this one.
NOT_CONTROL_FLOW = frozenset({"tool", "skill", "feedback", "worker"})

#: `(node id, port id) -> port type`, or `None` when this build cannot resolve
#: it — a package's own discovered tool, absent from a bare catalogue.
PortTypeResolver = Callable[[str, str], str | None]


@dataclass(frozen=True)
class _BranchPort:
    node_id: str
    port_id: str

    @property
    def key(self) -> str:
        return f"{self.node_id}#{self.port_id}"


@dataclass
class ControlFlow:
    """The document's control-flow skeleton, resolved once and asked many times."""

    successors: dict[str, list[str]] = field(default_factory=dict)
    branch_targets: dict[str, list[str]] = field(default_factory=dict)
    predecessors: dict[str, list[str]] = field(default_factory=dict)
    roots: tuple[str, ...] = ()
    branching_nodes: tuple[tuple[_BranchPort, ...], ...] = ()

    def targets_from(self, branch: _BranchPort) -> list[str]:
        return self.branch_targets.get(branch.key, [])

    def reachable(self, start: Iterable[str], *, without: str | None = None) -> set[str]:
        return _walk(self.successors, start, without)

    def ancestors_of(self, node_id: str) -> set[str]:
        return _walk(self.predecessors, [node_id], None)


def _walk(
    adjacency: Mapping[str, list[str]],
    start: Iterable[str],
    without: str | None,
) -> set[str]:
    seen: set[str] = set()
    queue: list[str] = []
    for node_id in start:
        if node_id == without or node_id in seen:
            continue
        seen.add(node_id)
        queue.append(node_id)
    head = 0
    while head < len(queue):
        current = queue[head]
        head += 1
        for nxt in adjacency.get(current, ()):
            if nxt == without or nxt in seen:
                continue
            seen.add(nxt)
            queue.append(nxt)
    return seen


def build_control_flow(
    node_ids: Sequence[str],
    edges: Sequence[Mapping[str, Any]],
    port_type: PortTypeResolver,
    branch_ports_of: Callable[[str], Sequence[str]],
) -> ControlFlow:
    """One pass over the document.

    `branch_ports_of` answers with a node's `branch` out-port ids — the
    catalogue's own `branch` flag (artifact schema 5), resolved by the caller
    because only it knows how a node's configured ports are named.

    The roots are computed on the whole graph, before any branching node is
    hypothetically deleted: recomputing them afterwards would promote every
    node the deletion orphaned into a root, and then nothing would be gated by
    anything.
    """
    flow = ControlFlow()
    fed: set[str] = set()
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(source, dict) or not isinstance(target, dict):
            continue
        src_id = str(source.get("nodeId") or "")
        dst_id = str(target.get("nodeId") or "")
        if not src_id or not dst_id:
            continue
        from_type = port_type(src_id, str(source.get("portId") or ""))
        to_type = port_type(dst_id, str(target.get("portId") or ""))
        # Both ends are asked, and either one saying no is enough — the
        # consumer is the end that is always a catalogue node, and `tools` is
        # `tool` whoever is plugged into it.
        if from_type is None or to_type is None:
            continue
        if from_type in NOT_CONTROL_FLOW or to_type in NOT_CONTROL_FLOW:
            continue
        flow.successors.setdefault(src_id, []).append(dst_id)
        flow.predecessors.setdefault(dst_id, []).append(src_id)
        flow.branch_targets.setdefault(
            f"{src_id}#{source.get('portId') or ''}", []
        ).append(dst_id)
        fed.add(dst_id)

    flow.roots = tuple(node_id for node_id in node_ids if node_id not in fed)
    branching: list[tuple[_BranchPort, ...]] = []
    for node_id in node_ids:
        ports = [_BranchPort(node_id, port_id) for port_id in branch_ports_of(node_id)]
        # Fewer than two ways out is not a choice between them.
        if len(ports) >= 2:
            branching.append(tuple(ports))
    flow.branching_nodes = tuple(branching)
    return flow


def _branch_leaving_owner(
    branching: Sequence[_BranchPort], port_id: str
) -> set[str] | None:
    """The edge leaves the branching node itself: it carries exactly that branch."""
    owner = branching[0].node_id
    key = f"{owner}#{port_id}"
    return {key} if any(branch.key == key for branch in branching) else None


def concurrent_producer_count(
    flow: ControlFlow, edges: Sequence[Mapping[str, Any]]
) -> int:
    """The largest number of `edges` that can carry a value in one run.

    Exclusivity is a pairwise fact and the largest set of *mutually* concurrent
    edges is a maximum clique, so this returns the size of the largest
    connected component of the "can coexist" graph — an upper bound on it. For
    the shapes this product draws (a router's branches, a grader's verdicts)
    exclusivity is total and the bound is exact.
    """
    if len(edges) < 2 or not flow.branching_nodes:
        return len(edges)

    producers = [str((edge.get("source") or {}).get("nodeId") or "") for edge in edges]
    ports = [str((edge.get("source") or {}).get("portId") or "") for edge in edges]

    # A branching node can only gate a producer it can reach, so the ones
    # upstream of none of them answer `None` for every edge.
    upstream: set[str] = set()
    for producer in set(producers):
        upstream |= flow.ancestors_of(producer)

    constraints: list[list[set[str] | None]] = []
    for branching in flow.branching_nodes:
        owner = branching[0].node_id
        if owner not in upstream:
            continue
        ungated = flow.reachable(flow.roots, without=owner)
        reached = {
            branch.key: flow.reachable(flow.targets_from(branch), without=owner)
            for branch in branching
        }
        row: list[set[str] | None] = []
        for producer, port_id in zip(producers, ports, strict=True):
            if producer == owner:
                row.append(_branch_leaving_owner(branching, port_id))
                continue
            if producer in ungated:
                row.append(None)
                continue
            taken = {key for key, seen in reached.items() if producer in seen}
            row.append(taken or None)
        if any(entry is not None for entry in row):
            constraints.append(row)

    if not constraints:
        return len(edges)

    def exclusive(a: int, b: int) -> bool:
        for row in constraints:
            left, right = row[a], row[b]
            if left is None or right is None:
                continue
            if left.isdisjoint(right):
                return True
        return False

    parent = list(range(len(edges)))

    def find(index: int) -> int:
        while parent[index] != index:
            index = parent[index]
        return index

    for a in range(len(edges)):
        for b in range(a + 1, len(edges)):
            if exclusive(a, b):
                continue
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[root_b] = root_a

    sizes: dict[int, int] = {}
    for index in range(len(edges)):
        root = find(index)
        sizes[root] = sizes.get(root, 0) + 1
    return max(sizes.values())


__all__ = [
    "NOT_CONTROL_FLOW",
    "ControlFlow",
    "build_control_flow",
    "concurrent_producer_count",
]
