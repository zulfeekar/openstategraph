import {
  distanceToSegment,
  rectCenter,
  rectOf,
  unionRects,
  type Rect,
} from '@core/kernel/geometry';
import type { AbstractNodeModel } from './AbstractNodeModel';
import type { EdgeModel } from './EdgeModel';
import type { EdgeId, IEdgeModel } from './contracts/workflow';
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

/**
 * Which of `candidates` actually lie **on** a cycle, using only edges
 * between candidates.
 *
 * The companion to `topologicalOrder`, and the reason it needs one:
 * Kahn's leftover set is every node whose in-degree never reached zero,
 * which over-includes everything merely *downstream* of a cycle. Narrowing
 * it by asking "can this node reach itself?" of each member in turn is a
 * full traversal per member — O(V·(V+E)) precisely when a cycle exists,
 * which for this product is the ordinary case rather than the exceptional
 * one (a revision loop is a drawn feature).
 *
 * One Tarjan pass answers it for every member at once, in O(V+E): a node is
 * on a cycle exactly when its strongly-connected component has more than
 * one member, or when it has an edge to itself. Iterative rather than
 * recursive — a chain of 1600 nodes is a document someone can draw, and it
 * is also a 1600-deep call stack.
 *
 * Takes a successor *function* rather than an edge list so the caller can
 * feed it `WorkflowModel.edgesOf` (which reads `AdjacencyIndex`, the
 * incidence structure that exists for exactly this) without this file
 * learning what an edge is.
 */
export function cyclicMembers(
  candidates: ReadonlySet<NodeId>,
  successors: (nodeId: NodeId) => Iterable<NodeId>,
): Set<NodeId> {
  // Materialised once, restricted to candidates: `successors` is asked
  // exactly once per candidate, which is the property the scaling test pins.
  const outgoing = new Map<NodeId, NodeId[]>();
  for (const id of candidates) {
    const next: NodeId[] = [];
    for (const target of successors(id)) if (candidates.has(target)) next.push(target);
    outgoing.set(id, next);
  }

  const index = new Map<NodeId, number>();
  const lowlink = new Map<NodeId, number>();
  const onStack = new Set<NodeId>();
  const stack: NodeId[] = [];
  const cyclic = new Set<NodeId>();
  let counter = 0;

  const discover = (id: NodeId): void => {
    index.set(id, counter);
    lowlink.set(id, counter);
    counter += 1;
    stack.push(id);
    onStack.add(id);
  };
  const lowOf = (id: NodeId): number => lowlink.get(id) ?? 0;
  const indexOf = (id: NodeId): number => index.get(id) ?? 0;

  for (const root of candidates) {
    if (index.has(root)) continue;
    discover(root);
    // `at` is how far into this node's successors the walk has got — the
    // resumption point a recursive implementation would keep on the stack.
    const frames: { readonly id: NodeId; at: number }[] = [{ id: root, at: 0 }];

    while (frames.length > 0) {
      const frame = frames[frames.length - 1];
      if (!frame) break;
      const next = outgoing.get(frame.id) ?? [];

      if (frame.at < next.length) {
        const child = next[frame.at];
        frame.at += 1;
        if (child === undefined) continue;
        if (!index.has(child)) {
          discover(child);
          frames.push({ id: child, at: 0 });
        } else if (onStack.has(child)) {
          lowlink.set(frame.id, Math.min(lowOf(frame.id), indexOf(child)));
        }
        continue;
      }

      frames.pop();
      const parent = frames[frames.length - 1];
      if (parent) lowlink.set(parent.id, Math.min(lowOf(parent.id), lowOf(frame.id)));

      if (lowOf(frame.id) !== indexOf(frame.id)) continue;

      // `frame.id` is the root of a component; everything above it on the
      // stack is a member.
      const members: NodeId[] = [];
      for (;;) {
        const member = stack.pop();
        if (member === undefined) break;
        onStack.delete(member);
        members.push(member);
        if (member === frame.id) break;
      }
      // A single-member component is a cycle only through a self-edge.
      const isCycle = members.length > 1 || next.includes(frame.id);
      if (isCycle) for (const member of members) cyclic.add(member);
    }
  }

  return cyclic;
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

/**
 * The edge whose endpoints' node-centre-to-node-centre line passes closest
 * to `point`, within `maxDistance` — or `null` if none does.
 *
 * Used for ticket 25's splice-insert drop gesture: "is this drop near an
 * existing link." A deliberate approximation, not the rendered curve's
 * exact geometry — JointJS may route a link with bends, and hit-testing
 * that precisely belongs to the canvas layer, not this framework-free
 * model. Node-centre-to-node-centre is close enough for "did the user aim
 * at this connection," and keeps the gesture testable against plain model
 * data with no live paper.
 */
export function closestEdgeToPoint(
  nodes: (id: NodeId) => AbstractNodeModel | undefined,
  edges: Iterable<IEdgeModel>,
  point: { readonly x: number; readonly y: number },
  maxDistance: number,
): EdgeId | null {
  let best: { id: EdgeId; distance: number } | null = null;
  for (const edge of edges) {
    const source = nodes(edge.source.nodeId);
    const target = nodes(edge.target.nodeId);
    if (!source || !target) continue;
    const a = rectCenter(rectOf(source.position, source.size));
    const b = rectCenter(rectOf(target.position, target.size));
    const distance = distanceToSegment(point, a, b);
    if (distance <= maxDistance && (!best || distance < best.distance)) {
      best = { id: edge.id, distance };
    }
  }
  return best?.id ?? null;
}
