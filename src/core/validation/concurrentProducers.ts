import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { EdgeModel } from '@core/model/EdgeModel';
import type { INodeModel, NodeId } from '@core/model/contracts/node';

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
 * Port types that wire *configuration*, not control flow.
 *
 * A tool, a skill and a worker declaration do not make their consumer run —
 * `worker` says so in the catalogue's own words ("a fan-out declaration, not
 * control flow"), and a `feedback` edge travels backwards in time, into the
 * next superstep rather than this one. Walking them would report an agent as
 * reachable from its own tool palette, which is how "is this node downstream
 * of that branch" gets the wrong answer.
 */
const NOT_CONTROL_FLOW: ReadonlySet<string> = new Set(['tool', 'skill', 'feedback', 'worker']);

/** A `branch` output that its owner agrees is exclusive, keyed for set maths. */
interface BranchPort {
  readonly nodeId: NodeId;
  readonly portId: string;
}

/**
 * Does this edge carry control flow — i.e. can it make its target run?
 *
 * **Both** ends are asked, and either one saying no is enough. A node type this
 * installation does not know — a package's own discovered tool, which is a
 * `workflows/<slug>/tools.py` class and therefore absent from a bare catalogue
 * — resolves to a placeholder whose port types are not the real ones, and
 * asking only the producer walked a whole tool palette into an agent's
 * upstream. The consumer is the end that is always a catalogue node here, and
 * `tools` is `tool` whoever is plugged into it.
 */
function isControlFlow(model: WorkflowModel, edge: EdgeModel): boolean {
  const from = model.node(edge.source.nodeId)?.port(edge.source.portId);
  const to = model.node(edge.target.nodeId)?.port(edge.target.portId);
  if (from === undefined || to === undefined) return false;
  return !NOT_CONTROL_FLOW.has(from.type) && !NOT_CONTROL_FLOW.has(to.type);
}

/**
 * The branch outputs of `node`, or `[]` when it has fewer than two or has
 * disclaimed exclusivity.
 *
 * `branchesAreExclusive` is optional and absent means *yes*, because that is
 * what `IPortDescriptor.branch` already declares. A family that broadcasts
 * opts out; nothing else has to know this exists.
 */
function exclusiveBranchesOf(node: INodeModel): readonly BranchPort[] {
  if (node.branchesAreExclusive === false) return [];
  const branchPorts = node.ports.filter((port) => port.direction === 'out' && port.branch);
  if (branchPorts.length < 2) return [];
  return branchPorts.map((port) => ({ nodeId: node.id, portId: port.id }));
}

/** Every node reachable over control-flow edges from the given starting nodes. */
function reachable(
  model: WorkflowModel,
  from: readonly NodeId[],
  options: { readonly without?: NodeId } = {},
): Set<NodeId> {
  const seen = new Set<NodeId>();
  const queue = [...from];
  while (queue.length > 0) {
    const current = queue.shift();
    if (current == null || current === options.without || seen.has(current)) continue;
    seen.add(current);
    for (const edge of model.edgesOf(current)) {
      if (edge.source.nodeId !== current) continue;
      if (!isControlFlow(model, edge)) continue;
      const next = edge.target.nodeId;
      if (next === options.without || seen.has(next)) continue;
      queue.push(next);
    }
  }
  return seen;
}

/**
 * Where control flow can begin: a node with no incoming control-flow edge.
 *
 * Computed on the whole graph *before* any branching node is hypothetically
 * removed. Recomputing it afterwards would promote every node the removal
 * orphaned into a root, and then nothing would ever be gated by anything.
 */
function controlFlowRoots(model: WorkflowModel): NodeId[] {
  const fed = new Set<NodeId>();
  for (const edge of model.edges()) {
    if (!isControlFlow(model, edge as EdgeModel)) continue;
    fed.add(edge.target.nodeId);
  }
  return model
    .nodes()
    .map((node) => node.id)
    .filter((id) => !fed.has(id));
}

/**
 * Which of `branching`'s branches have to have been taken for `nodeId` to run,
 * or `null` when the branching node does not decide that at all.
 *
 * Two conditions, and the second is the one that is easy to forget: the node
 * must be reachable from at least one branch, **and** it must be unreachable
 * when the branching node is deleted. Without the second, a node that can also
 * be reached by a path going nowhere near the router would be treated as if
 * the router gated it, and two genuinely concurrent producers would be called
 * exclusive on the strength of a branch neither of them needs.
 */
function gatingBranches(
  model: WorkflowModel,
  roots: readonly NodeId[],
  branching: readonly BranchPort[],
  nodeId: NodeId,
): Set<string> | null {
  const owner = branching[0]?.nodeId;
  if (owner === undefined) return null;
  if (reachable(model, roots, { without: owner }).has(nodeId)) return null;

  const taken = new Set<string>();
  for (const branch of branching) {
    const starts = model
      .edgesFrom({ nodeId: branch.nodeId, portId: branch.portId })
      .filter((edge) => isControlFlow(model, edge))
      .map((edge) => edge.target.nodeId);
    if (reachable(model, starts, { without: owner }).has(nodeId)) {
      taken.add(`${branch.nodeId}#${branch.portId}`);
    }
  }
  return taken.size > 0 ? taken : null;
}

/** The branches that must have been taken for `edge` to carry a value. */
function constraintsOf(
  model: WorkflowModel,
  roots: readonly NodeId[],
  branching: readonly BranchPort[],
  edge: { readonly source: { readonly nodeId: NodeId; readonly portId: string } },
): Set<string> | null {
  const owner = branching[0]?.nodeId;
  if (owner === undefined) return null;
  // The edge leaves the branching node itself: it carries exactly that branch,
  // and no reachability question arises.
  if (edge.source.nodeId === owner) {
    const key = `${owner}#${edge.source.portId}`;
    return branching.some((b) => `${b.nodeId}#${b.portId}` === key) ? new Set([key]) : null;
  }
  return gatingBranches(model, roots, branching, edge.source.nodeId);
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
export function concurrentProducerCount(
  model: WorkflowModel,
  _registry: ModelRegistry,
  edges: readonly { readonly source: { readonly nodeId: NodeId; readonly portId: string } }[],
): number {
  if (edges.length < 2) return edges.length;

  const branchingNodes = model
    .nodes()
    .map(exclusiveBranchesOf)
    .filter((branches) => branches.length > 0);
  if (branchingNodes.length === 0) return edges.length;

  const roots = controlFlowRoots(model);
  const constraints = branchingNodes.map((branching) =>
    edges.map((edge) => constraintsOf(model, roots, branching, edge)),
  );

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
