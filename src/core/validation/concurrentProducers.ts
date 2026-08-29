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

/** One branching node's reachability, resolved once and read per edge. */
interface Gate {
  readonly owner: NodeId;
  /** What still runs when the branching node is deleted. */
  readonly ungated: ReadonlySet<NodeId>;
  readonly branches: readonly { readonly key: string; readonly reached: ReadonlySet<NodeId> }[];
}

/**
 * Which of the gate's branches have to have been taken for `edge` to carry a
 * value, or `null` when this branching node does not decide that at all.
 *
 * Two conditions, and the second is the one that is easy to forget: the source
 * must be reachable from at least one branch, **and** it must be unreachable
 * when the branching node is deleted. Without the second, a node that can also
 * be reached by a path going nowhere near the router would be treated as if
 * the router gated it, and two genuinely concurrent producers would be called
 * exclusive on the strength of a branch neither of them needs.
 *
 * Both reachability sets are the gate's, not this edge's — which is the whole
 * of ticket `the-cost-of-one-more/03`. They were recomputed here, with
 * identical arguments, once per edge on the port.
 */
function constraintsOf(
  gate: Gate,
  edge: { readonly source: { readonly nodeId: NodeId; readonly portId: string } },
): Set<string> | null {
  // The edge leaves the branching node itself: it carries exactly that branch,
  // and no reachability question arises.
  if (edge.source.nodeId === gate.owner) {
    const key = `${gate.owner}#${edge.source.portId}`;
    return gate.branches.some((branch) => branch.key === key) ? new Set([key]) : null;
  }
  const nodeId = edge.source.nodeId;
  if (gate.ungated.has(nodeId)) return null;

  const taken = new Set<string>();
  for (const branch of gate.branches) {
    if (branch.reached.has(nodeId)) taken.add(branch.key);
  }
  return taken.size > 0 ? taken : null;
}

function gateFor(graph: IControlFlowGraph, branching: readonly BranchPort[]): Gate | null {
  const owner = branching[0]?.nodeId;
  if (owner === undefined) return null;
  return {
    owner,
    ungated: graph.reachable(graph.roots, { without: owner }),
    branches: branching.map((branch) => ({
      key: `${branch.nodeId}#${branch.portId}`,
      reached: graph.reachable(graph.targetsFrom(branch), { without: owner }),
    })),
  };
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

  // A branching node can only gate a producer it can *reach*: `constraintsOf`
  // returns non-null only when some branch of it reaches the edge's source, and
  // a branch target is downstream of its owner by construction. So the
  // branching nodes upstream of no producer answer `null` for every edge, and
  // asking them costs a walk of the whole document for a foregone conclusion.
  // On the swap gesture that is every router in the document.
  const upstream = new Set<NodeId>();
  for (const nodeId of new Set(edges.map((edge) => edge.source.nodeId))) {
    for (const ancestor of graph.ancestorsOf(nodeId)) upstream.add(ancestor);
  }

  const gates: Gate[] = [];
  for (const branching of graph.branchingNodes) {
    const owner = branching[0]?.nodeId;
    if (owner === undefined || !upstream.has(owner)) continue;
    const gate = gateFor(graph, branching);
    if (gate) gates.push(gate);
  }
  if (gates.length === 0) return edges.length;

  const constraints = gates.map((gate) => edges.map((edge) => constraintsOf(gate, edge)));

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
