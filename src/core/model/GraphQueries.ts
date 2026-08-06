import type { Rect } from '@core/kernel/geometry';
import type { AdjacencyIndex } from './AdjacencyIndex';
import type { AbstractNodeModel } from './AbstractNodeModel';
import type { EdgeModel } from './EdgeModel';
import type { NodeId, NodeTypeId } from './contracts/node';
import { portRefEquals, type PortRef } from './contracts/ports';
import type { EdgeId } from './contracts/workflow';
import * as topology from './topology';

/**
 * Read-only graph algorithms: neighbours, ancestry, scheduling order, bounds.
 *
 * Pulled out of `WorkflowModel` (ticket 17) as the other half of the split
 * `AdjacencyIndex` started — that class only maintains *which ids touch
 * which*; this class answers questions *about* that structure. Neither
 * concern needed the other's internals, and keeping them apart means either
 * can be tested (as here) with a handful of nodes and edges, not a whole
 * document.
 *
 * Takes the underlying maps directly rather than a `WorkflowModel` — a
 * circular dependency would otherwise exist (the model owns queries, and
 * queries would own the model back), and this is *never* meant to be
 * constructed by anything other than `WorkflowModel` itself. It is an
 * implementation detail of the aggregate, not a second public surface a
 * developer is expected to reach for — `WorkflowModel`'s own public methods
 * still answer these questions; they just delegate here.
 */
export class GraphQueries {
  constructor(
    private readonly nodeMap: ReadonlyMap<NodeId, AbstractNodeModel>,
    private readonly edgeMap: ReadonlyMap<EdgeId, EdgeModel>,
    private readonly adjacency: AdjacencyIndex,
  ) {}

  edgesOf(nodeId: NodeId): readonly EdgeModel[] {
    const result: EdgeModel[] = [];
    for (const id of this.adjacency.edgeIdsOf(nodeId)) {
      const edge = this.edgeMap.get(id);
      if (edge) result.push(edge);
    }
    return result;
  }

  edgesInto(ref: PortRef): readonly EdgeModel[] {
    return this.edgesOf(ref.nodeId).filter((edge) => portRefEquals(edge.target, ref));
  }

  edgesFrom(ref: PortRef): readonly EdgeModel[] {
    return this.edgesOf(ref.nodeId).filter((edge) => portRefEquals(edge.source, ref));
  }

  childrenOf(nodeId: NodeId): readonly AbstractNodeModel[] {
    const result: AbstractNodeModel[] = [];
    for (const id of this.adjacency.childIdsOf(nodeId)) {
      const node = this.nodeMap.get(id);
      if (node) result.push(node);
    }
    return result;
  }

  /** Children, grandchildren and so on. */
  descendantsOf(nodeId: NodeId): readonly AbstractNodeModel[] {
    const result: AbstractNodeModel[] = [];
    const queue = [...this.childrenOf(nodeId)];
    while (queue.length > 0) {
      const node = queue.shift();
      if (!node) continue;
      result.push(node);
      queue.push(...this.childrenOf(node.id));
    }
    return result;
  }

  predecessorsOf(nodeId: NodeId): readonly AbstractNodeModel[] {
    const seen = new Set<NodeId>();
    const result: AbstractNodeModel[] = [];
    for (const edge of this.edgesOf(nodeId)) {
      if (edge.target.nodeId !== nodeId) continue;
      const id = edge.source.nodeId;
      if (seen.has(id)) continue;
      seen.add(id);
      const node = this.nodeMap.get(id);
      if (node) result.push(node);
    }
    return result;
  }

  successorsOf(nodeId: NodeId): readonly AbstractNodeModel[] {
    const seen = new Set<NodeId>();
    const result: AbstractNodeModel[] = [];
    for (const edge of this.edgesOf(nodeId)) {
      if (edge.source.nodeId !== nodeId) continue;
      const id = edge.target.nodeId;
      if (seen.has(id)) continue;
      seen.add(id);
      const node = this.nodeMap.get(id);
      if (node) result.push(node);
    }
    return result;
  }

  countOfType(type: NodeTypeId): number {
    let count = 0;
    for (const node of this.nodeMap.values()) if (node.type === type) count += 1;
    return count;
  }

  /** True when `ancestorId` is a strict ancestor of `nodeId` via `parentId` chains. */
  isAncestorOf(ancestorId: NodeId, nodeId: NodeId): boolean {
    let current = this.nodeMap.get(nodeId)?.parentId ?? null;
    while (current) {
      if (current === ancestorId) return true;
      current = this.nodeMap.get(current)?.parentId ?? null;
    }
    return false;
  }

  /** Kahn's algorithm over executable nodes. See `topology.topologicalOrder`. */
  topologicalOrder(): { order: readonly NodeId[]; cycle: readonly NodeId[] | null } {
    return topology.topologicalOrder(this.nodeMap.values(), this.edgeMap.values());
  }

  bounds(): Rect | null {
    return topology.bounds(this.nodeMap.values());
  }
}
