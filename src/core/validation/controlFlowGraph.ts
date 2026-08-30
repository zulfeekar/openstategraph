import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { IEdgeModel } from '@core/model/contracts/workflow';
import type { INodeModel, NodeId } from '@core/model/contracts/node';

/**
 * The document's control-flow skeleton, resolved **once** and then asked
 * many times.
 *
 * `concurrentProducerCount` used to ask the model the same three questions —
 * *is this edge control flow*, *what are this node's out-edges*, *where do
 * these roots reach* — from inside two nested loops, so the whole document was
 * re-walked once per branching node **per edge on the port**. One ordinary
 * swap gesture on a 516-node document cost 153 ms inside a single pointer-move
 * (`the-cost-of-one-more/03`).
 *
 * Nothing about that walk depends on the edge, so this collaborator holds the
 * edge-independent part. Its lifetime is deliberately **one
 * `concurrentProducerCount` call**: it is built from the model, it answers,
 * and it dies. A longer-lived one would be faster still and would need an
 * invalidation story the model does not offer — `launch-readiness/113`
 * declined a cache for exactly that reason after measuring, and `182` is the
 * open leak from a memo that outlived its key.
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
export interface BranchPort {
  readonly nodeId: NodeId;
  readonly portId: string;
}

/** The questions `concurrentProducerCount` asks about control flow, and no others. */
export interface IControlFlowGraph {
  /** Where control flow can begin: nodes with no incoming control-flow edge. */
  readonly roots: readonly NodeId[];
  /** Each node that decides between mutually exclusive branches, with its branch ports. */
  readonly branchingNodes: readonly (readonly BranchPort[])[];
  /** The control-flow targets of one branch port. */
  targetsFrom(branch: BranchPort): readonly NodeId[];
  /** Every node reachable over control-flow edges from the given starting nodes. */
  reachable(from: readonly NodeId[], options?: { readonly without?: NodeId }): Set<NodeId>;
  /** Every node that can reach `node` over control-flow edges, `node` included. */
  ancestorsOf(node: NodeId): Set<NodeId>;
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
function isControlFlow(model: WorkflowModel, edge: IEdgeModel): boolean {
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

function append(index: Map<string, NodeId[]>, key: string, value: NodeId): void {
  const existing = index.get(key);
  if (existing) existing.push(value);
  else index.set(key, [value]);
}

/** Breadth-first over an adjacency index. Never `shift()`: that is O(n) per step. */
function walk(
  adjacency: Map<string, NodeId[]>,
  from: readonly NodeId[],
  without: NodeId | undefined,
): Set<NodeId> {
  const seen = new Set<NodeId>();
  const queue: NodeId[] = [];
  for (const start of from) {
    if (start === without || seen.has(start)) continue;
    seen.add(start);
    queue.push(start);
  }
  for (let head = 0; head < queue.length; head += 1) {
    const current = queue[head];
    if (current === undefined) continue;
    for (const next of adjacency.get(current) ?? []) {
      if (next === without || seen.has(next)) continue;
      seen.add(next);
      queue.push(next);
    }
  }
  return seen;
}

/**
 * One pass over the document, then constant-time answers.
 *
 * The roots are computed on the whole graph *before* any branching node is
 * hypothetically removed. Recomputing them afterwards would promote every node
 * the removal orphaned into a root, and then nothing would ever be gated by
 * anything.
 */
export class ControlFlowGraph implements IControlFlowGraph {
  readonly roots: readonly NodeId[];
  readonly branchingNodes: readonly (readonly BranchPort[])[];
  private readonly successors = new Map<string, NodeId[]>();
  private readonly predecessors = new Map<string, NodeId[]>();
  private readonly branchTargets = new Map<string, NodeId[]>();

  constructor(model: WorkflowModel) {
    const fed = new Set<NodeId>();
    for (const edge of model.edges()) {
      if (!isControlFlow(model, edge)) continue;
      const from = edge.source.nodeId;
      const to = edge.target.nodeId;
      append(this.successors, from, to);
      append(this.predecessors, to, from);
      append(this.branchTargets, `${from}#${edge.source.portId}`, to);
      fed.add(to);
    }
    const nodes = model.nodes();
    this.roots = nodes.map((node) => node.id).filter((id) => !fed.has(id));
    this.branchingNodes = nodes.map(exclusiveBranchesOf).filter((branches) => branches.length > 0);
  }

  targetsFrom(branch: BranchPort): readonly NodeId[] {
    return this.branchTargets.get(`${branch.nodeId}#${branch.portId}`) ?? [];
  }

  reachable(from: readonly NodeId[], options: { readonly without?: NodeId } = {}): Set<NodeId> {
    return walk(this.successors, from, options.without);
  }

  ancestorsOf(node: NodeId): Set<NodeId> {
    return walk(this.predecessors, [node], undefined);
  }
}
