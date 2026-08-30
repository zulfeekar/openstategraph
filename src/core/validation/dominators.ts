import type { NodeId } from '@core/model/contracts/node';

/**
 * Which nodes lie on **every** path from a root — the dominator tree, built in
 * one pass and then read as a chain per node.
 *
 * `the-cost-of-one-more/21`. `concurrentProducers.ts` asked *"what still runs
 * when this branching node is deleted"* once per branching node, and each
 * answer was a walk of the whole document. `03` had already removed the *per
 * edge* factor from that loop and recorded the remaining one as the thing a
 * dominator pass would flatten; the counter `19` put on the gesture priced it
 * exactly — walks linear in the document, the nodes those walks visit ×3.98
 * per doubling.
 *
 * The identity that removes it: **a branching node `O` gates node `n` exactly
 * when `O` dominates `n`.** "Still reachable from the roots with `O` deleted"
 * and "not on every path from a root" are the same sentence read from two
 * ends. One dominator tree answers it for every pair at once, so a question
 * that cost a walk each costs a chain walk per *producer* — of which there are
 * as many as there are links on the port, not as many as there are routers.
 *
 * Deliberately **DAG-only**, and it says so by returning `null` rather than by
 * assuming. The general algorithm (Cooper–Harvey–Kennedy iterating to a fixed
 * point) handles cycles, and would have been the wrong trade here: this
 * index's caller also needs *"can this branch target reach the producer with
 * the owner deleted"*, and that question collapses to plain reachability only
 * because a successor of `O` cannot reach `O` again in an acyclic graph. Half
 * an answer to a cyclic document is worse than none — the caller keeps the
 * walks for that case, where they are exact — so the cycle is detected here,
 * for free, as the topological sort failing to cover what the roots reach.
 */

/**
 * Immediate dominators, keyed by node. `null` marks a node the roots reach
 * directly with nothing above it; a node **absent** from the map is one the
 * roots cannot reach at all, which is a different answer and not a smaller
 * one — see `dominatorsOf`.
 */
export type DominatorTree = ReadonlyMap<NodeId, NodeId | null>;

/**
 * The tree, or `null` when the graph the roots reach contains a cycle.
 *
 * `roots` must be exactly the nodes with no incoming edge, which is what
 * `ControlFlowGraph` computes: every node of in-degree zero is one, so Kahn's
 * queue starts complete and anything it fails to reach is on a cycle.
 */
export function dominatorTree(
  roots: readonly NodeId[],
  successors: ReadonlyMap<NodeId, readonly NodeId[]>,
): DominatorTree | null {
  const predecessors = new Map<NodeId, NodeId[]>();
  const remaining = new Map<NodeId, number>();
  const reached = new Set<NodeId>(roots);
  const pending: NodeId[] = [...roots];
  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined) continue;
    for (const next of successors.get(current) ?? []) {
      const into = predecessors.get(next);
      if (into) into.push(current);
      else predecessors.set(next, [current]);
      remaining.set(next, (remaining.get(next) ?? 0) + 1);
      if (reached.has(next)) continue;
      reached.add(next);
      pending.push(next);
    }
  }

  // Kahn, in queue order, which is a topological order of what the roots
  // reach. Every predecessor of a node is therefore numbered before it, and
  // the intersection below can be a single pass rather than a fixed point.
  const order: NodeId[] = [];
  const rank = new Map<NodeId, number>();
  const queue: NodeId[] = [...roots];
  for (const root of roots) {
    rank.set(root, order.length);
    order.push(root);
  }
  for (let head = 0; head < queue.length; head += 1) {
    const current = queue[head];
    if (current === undefined) continue;
    for (const next of successors.get(current) ?? []) {
      const left = (remaining.get(next) ?? 0) - 1;
      remaining.set(next, left);
      if (left !== 0) continue;
      rank.set(next, order.length);
      order.push(next);
      queue.push(next);
    }
  }
  if (order.length !== reached.size) return null;

  const idom = new Map<NodeId, NodeId | null>();
  /**
   * The nearest node that dominates both — walk the two chains upward, always
   * moving the one that sits later in the order, until they meet. `null` when
   * they meet nowhere, which means the two arrive from different roots and
   * only the (imaginary) node above all roots dominates them.
   */
  const meet = (left: NodeId, right: NodeId): NodeId | null => {
    let a: NodeId | null = left;
    let b: NodeId | null = right;
    while (a !== null && b !== null && a !== b) {
      if ((rank.get(a) ?? 0) > (rank.get(b) ?? 0)) a = idom.get(a) ?? null;
      else b = idom.get(b) ?? null;
    }
    return a !== null && b !== null ? a : null;
  };

  for (const node of order) {
    let common: NodeId | null = null;
    let first = true;
    for (const predecessor of predecessors.get(node) ?? []) {
      if (first) {
        common = predecessor;
        first = false;
        continue;
      }
      if (common === null) break;
      common = meet(common, predecessor);
    }
    idom.set(node, common);
  }
  return idom;
}

/**
 * Every node on all paths from a root to `node`, `node` itself excluded.
 *
 * `null` when the tree cannot answer for this node: it is not one the roots
 * reach, so it sits in a component fed only by itself. Saying "dominated by
 * nothing" there would be wrong in the unsafe direction — the walks call such
 * a node gated by everything — so the caller is told to ask them instead.
 */
export function dominatorsOf(tree: DominatorTree, node: NodeId): ReadonlySet<NodeId> | null {
  if (!tree.has(node)) return null;
  const chain = new Set<NodeId>();
  let above = tree.get(node) ?? null;
  while (above !== null && !chain.has(above)) {
    chain.add(above);
    above = tree.get(above) ?? null;
  }
  return chain;
}
