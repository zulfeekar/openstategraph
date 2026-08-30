import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { NodeId } from '@core/model/contracts/node';
import { ControlFlowGraph, type BranchPort, type IControlFlowGraph } from './controlFlowGraph';

/**
 * How many of a port's incoming links can carry a value in the **same run**.
 *
 * `workflow-gallery/64`. `maxConnections` on an input exists because a slot
 * holds one value: two producers writing it in one superstep is the ambiguity
 * the cap forbids. But it was counting *edges drawn*, and those are not the
 * same number. A router takes exactly one of its branches, so three branches
 * converging on one agent's `prompt` is three edges and one producer — while
 * two unrelated agents into that same prompt is two edges and two producers,
 * which is the case the cap is actually for (ticket 14).
 *
 * The distinction has to be structural, and it is: a `branch` output is
 * declared by its port as "one of several mutually exclusive ways out", and a
 * node whose branches are *not* exclusive says so (`INodeModel.branchesAreExclusive`
 * — a Router set to *run every match, in parallel* is exactly that node, and
 * discovering it is why this is asked of the node rather than read off the
 * port flag).
 *
 * Deliberately **conservative in one direction only**: where it cannot prove
 * two producers are exclusive it calls them concurrent, so the answer is never
 * smaller than the truth and the cap is never relaxed on a guess.
 */

/**
 * Which of a branching node's branches have to have been taken for `edge` to
 * carry a value, or `null` when this branching node does not decide that at
 * all — one row per branching node, one entry per edge.
 *
 * Two facts are needed per (branching node, edge) pair, and the whole of
 * `the-cost-of-one-more/21` is where they come from:
 *
 *  - **is the producer gated by this branching node at all** — it must be
 *    unreachable when the branching node is deleted. Without this, a node that
 *    can also be reached by a path going nowhere near the router would be
 *    treated as if the router gated it, and two genuinely concurrent producers
 *    would be called exclusive on the strength of a branch neither of them
 *    needs.
 *  - **which branches reach it**, which is what the constraint set names.
 *
 * Neither depends on the edge beyond its source, which is what `03` fixed.
 * Both were still answered by walking the whole document once per branching
 * node, which is what this pair of implementations fixes.
 */
type ConstraintRows = (Set<string> | null)[][];

/** The edge leaves the branching node itself: it carries exactly that branch. */
function branchLeavingOwner(branching: readonly BranchPort[], portId: string): Set<string> | null {
  const owner = branching[0]?.nodeId;
  if (owner === undefined) return null;
  const key = `${owner}#${portId}`;
  return branching.some((branch) => `${branch.nodeId}#${branch.portId}` === key)
    ? new Set([key])
    : null;
}

/**
 * The fast answer: one dominator pass, then set lookups.
 *
 * `null` when the index declines to answer for any producer — a control-flow
 * cycle, or a producer the roots cannot reach — in which case the caller falls
 * back to the walks, which are exact for those shapes too.
 *
 * **The invariant this rests on, named because `03` left it unnamed.** The
 * gating question is *"is the producer still reachable from the roots with the
 * owner deleted"*, and that is dominance: `owner` gates `producer` exactly when
 * it lies on every path to it. Dominance is a property of the **document**, not
 * of the branching node asking — so it is resolved once and read by every gate.
 *
 * The branch question keeps one thing from the walks and drops the rest. It
 * asks whether a branch target reaches the producer, and the walks ask that
 * *with the owner deleted*. The deletion is what stops a walk leaving by one
 * branch, looping back through the owner and arriving down another. It cannot
 * happen here: the index is `null` unless the graph the roots reach is
 * **acyclic**, and in an acyclic graph a successor of the owner has no path
 * back to it. So "reaches the producer" and "reaches the producer without the
 * owner" are the same set, and the producer's own ancestors — one walk per
 * *link on the port*, which `03` already paid for as its upstream filter —
 * answer it for every branching node at once.
 */
function constraintsByDominance(
  graph: IControlFlowGraph,
  edges: readonly { readonly source: { readonly nodeId: NodeId; readonly portId: string } }[],
): ConstraintRows | null {
  const gatedBy = new Map<NodeId, ReadonlySet<NodeId>>();
  const reaching = new Map<NodeId, ReadonlySet<NodeId>>();
  for (const producer of new Set(edges.map((edge) => edge.source.nodeId))) {
    const dominators = graph.dominatorsOf(producer);
    if (dominators === null) return null;
    gatedBy.set(producer, dominators);
    reaching.set(producer, graph.ancestorsOf(producer));
  }

  const rows: ConstraintRows = [];
  for (const branching of graph.branchingNodes) {
    const owner = branching[0]?.nodeId;
    if (owner === undefined) continue;
    // Resolved once per branching node rather than once per edge, which is
    // `03`'s rule applied to the two cheap questions this path has left.
    const branches = branching.map((branch) => ({
      key: `${branch.nodeId}#${branch.portId}`,
      targets: graph.targetsFrom(branch),
    }));
    const row = edges.map((edge) => {
      const producer = edge.source.nodeId;
      if (producer === owner) return branchLeavingOwner(branching, edge.source.portId);
      if (!(gatedBy.get(producer)?.has(owner) ?? false)) return null;
      const reaches = reaching.get(producer);
      const taken = new Set<string>();
      for (const branch of branches) {
        if (branch.targets.some((target) => reaches?.has(target) ?? false)) taken.add(branch.key);
      }
      return taken.size > 0 ? taken : null;
    });
    if (row.some((entry) => entry !== null)) rows.push(row);
  }
  return rows;
}

/**
 * The exact answer for a document the index declines: a walk of the whole
 * graph per branching node, plus one per branch it opens.
 *
 * This is `03`'s implementation, kept rather than replaced. It is quadratic in
 * the document and it is *correct on every shape*, including the cyclic ones
 * where reachability-with-a-node-deleted genuinely differs from reachability.
 * A control-flow cycle is drawable — `acyclicGraphRule` calls an escapable
 * loop a correct graph — so this path is reachable, and
 * `dominanceAgreesWithWalking.test.ts` runs the two against each other rather
 * than trusting the argument above.
 */
function constraintsByWalking(
  graph: IControlFlowGraph,
  edges: readonly { readonly source: { readonly nodeId: NodeId; readonly portId: string } }[],
): ConstraintRows {
  // A branching node can only gate a producer it can *reach*: a branch target
  // is downstream of its owner by construction, so the branching nodes
  // upstream of no producer answer `null` for every edge, and asking them
  // costs a walk of the whole document for a foregone conclusion. On the swap
  // gesture that is every router in the document.
  const upstream = new Set<NodeId>();
  for (const nodeId of new Set(edges.map((edge) => edge.source.nodeId))) {
    for (const ancestor of graph.ancestorsOf(nodeId)) upstream.add(ancestor);
  }

  const rows: ConstraintRows = [];
  for (const branching of graph.branchingNodes) {
    const owner = branching[0]?.nodeId;
    if (owner === undefined || !upstream.has(owner)) continue;
    const ungated = graph.reachable(graph.roots, { without: owner });
    const branches = branching.map((branch) => ({
      key: `${branch.nodeId}#${branch.portId}`,
      reached: graph.reachable(graph.targetsFrom(branch), { without: owner }),
    }));
    rows.push(
      edges.map((edge) => {
        const producer = edge.source.nodeId;
        if (producer === owner) return branchLeavingOwner(branching, edge.source.portId);
        if (ungated.has(producer)) return null;
        const taken = new Set<string>();
        for (const branch of branches) {
          if (branch.reached.has(producer)) taken.add(branch.key);
        }
        return taken.size > 0 ? taken : null;
      }),
    );
  }
  return rows;
}

/**
 * The largest number of these edges that can carry a value in one run.
 *
 * Exclusivity is a pairwise fact, and the largest set of *mutually* concurrent
 * edges is a maximum clique — so this returns the size of the largest connected
 * component of the "can coexist" graph instead, which is an upper bound on it.
 * Over-counting keeps a link refused or replaced that might have been allowed;
 * under-counting would let two values race into one slot. Only one of those is
 * survivable, and for the shapes this product actually draws — a router's
 * branches, a grader's verdicts — exclusivity is total and the bound is exact.
 */
export function concurrentProducerCountOn(
  graph: IControlFlowGraph,
  edges: readonly { readonly source: { readonly nodeId: NodeId; readonly portId: string } }[],
): number {
  if (edges.length < 2) return edges.length;
  if (graph.branchingNodes.length === 0) return edges.length;

  const constraints = constraintsByDominance(graph, edges) ?? constraintsByWalking(graph, edges);
  if (constraints.length === 0) return edges.length;

  const exclusive = (a: number, b: number): boolean =>
    constraints.some((perEdge) => {
      const left = perEdge[a];
      const right = perEdge[b];
      if (!left || !right) return false;
      return [...left].every((key) => !right.has(key));
    });

  // Connected components of "not proven exclusive".
  const component = edges.map((_, index) => index);
  const find = (index: number): number => {
    let root = index;
    while (component[root] !== root) root = component[root]!;
    return root;
  };
  for (let a = 0; a < edges.length; a += 1) {
    for (let b = a + 1; b < edges.length; b += 1) {
      if (exclusive(a, b)) continue;
      const rootA = find(a);
      const rootB = find(b);
      if (rootA !== rootB) component[rootB] = rootA;
    }
  }
  const sizes = new Map<number, number>();
  for (let index = 0; index < edges.length; index += 1) {
    const root = find(index);
    sizes.set(root, (sizes.get(root) ?? 0) + 1);
  }
  return Math.max(...sizes.values());
}

/**
 * The same question, asked of a document.
 *
 * Builds the control-flow skeleton and throws it away again: its lifetime is
 * this call, so there is nothing to invalidate. `capacityRule` asks this on
 * every pointer-move over a full port, and the model does not change during a
 * drag — a memo spanning the gesture would be faster still, and would need an
 * owner and an invalidation rule that no collaborator here has. That is a
 * different ticket, and only worth filing if this one is not enough.
 */
export function concurrentProducerCount(
  model: WorkflowModel,
  _registry: ModelRegistry,
  edges: readonly { readonly source: { readonly nodeId: NodeId; readonly portId: string } }[],
): number {
  if (edges.length < 2) return edges.length;
  return concurrentProducerCountOn(new ControlFlowGraph(model), edges);
}
