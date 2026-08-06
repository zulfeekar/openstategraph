import { unionRects, type Rect } from '@core/kernel/geometry';
import type { AbstractNodeModel } from './AbstractNodeModel';
import type { EdgeModel } from './EdgeModel';
import type { NodeId } from './contracts/node';

/**
 * Pure graph algorithms over `(nodes, edges)` — no class, no state, because
 * neither of these needs one. `GraphQueries` delegates to these rather than
 * implementing them inline, per the split ticket 17 settled on: this file
 * existing under this name, with `topology.test.ts` already testing it
 * (via `WorkflowModel`) before the file itself did, was the hint the seam
 * was always there.
 */

/**
 * Kahn's algorithm over executable nodes.
 *
 * Returns the surviving cycle when one exists rather than throwing — the UI
 * needs to highlight the offending nodes, and a cyclic graph is a thing a
 * user can legitimately draw on the way to a valid one.
 */
export function topologicalOrder(
  nodes: Iterable<AbstractNodeModel>,
  edges: Iterable<EdgeModel>,
): { order: readonly NodeId[]; cycle: readonly NodeId[] | null } {
  const indegree = new Map<NodeId, number>();
  const outgoing = new Map<NodeId, NodeId[]>();

  for (const node of nodes) {
    if (!node.isExecutable) continue;
    indegree.set(node.id, 0);
    outgoing.set(node.id, []);
  }

  for (const edge of edges) {
    const from = edge.source.nodeId;
    const to = edge.target.nodeId;
    // Skip edges touching non-executable nodes so annotations and
    // containers cannot stall the schedule.
    if (!indegree.has(from) || !indegree.has(to)) continue;
    outgoing.get(from)?.push(to);
    indegree.set(to, (indegree.get(to) ?? 0) + 1);
  }

  // Seed in insertion order so an unconstrained graph runs in the order the
  // user built it — surprising ordering makes runs hard to debug.
  const queue: NodeId[] = [];
  for (const [id, degree] of indegree) if (degree === 0) queue.push(id);

  const order: NodeId[] = [];
  while (queue.length > 0) {
    const id = queue.shift();
    if (id == null) continue;
    order.push(id);
    for (const next of outgoing.get(id) ?? []) {
      const remaining = (indegree.get(next) ?? 0) - 1;
      indegree.set(next, remaining);
      if (remaining === 0) queue.push(next);
    }
  }

  if (order.length === indegree.size) return { order, cycle: null };

  const cycle = [...indegree.entries()].filter(([, degree]) => degree > 0).map(([id]) => id);
  return { order, cycle };
}

/** The union of every node's rectangle, or `null` for an empty graph. */
export function bounds(nodes: Iterable<AbstractNodeModel>): Rect | null {
  const rects = [...nodes].map((node) => ({
    x: node.position.x,
    y: node.position.y,
    width: node.size.width,
    height: node.size.height,
  }));
  return unionRects(rects);
}
