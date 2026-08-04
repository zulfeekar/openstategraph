import { EventBus } from '@core/kernel/EventBus';
import type { Unsubscribe } from '@core/kernel/Disposable';
import type { NodeId } from '@core/model/contracts/node';
import type { EdgeId } from '@core/model/contracts/workflow';

interface SelectionEvents extends Record<string, unknown> {
  changed: { nodes: readonly NodeId[]; edges: readonly EdgeId[] };
}

export type SelectionMode = 'replace' | 'add' | 'toggle' | 'subtract';

/**
 * What the user currently has selected.
 *
 * Deliberately separate from the document: selection is view state, it is
 * not undoable, and it must not be serialized. Keeping it out of
 * `WorkflowModel` is what stops "select a node" from landing in the undo
 * history.
 *
 * Nodes and edges are tracked separately because the actions available
 * differ — you can group nodes and label edges, not the other way round.
 */
export class SelectionModel {
  private readonly bus = new EventBus<SelectionEvents>();
  private nodeIds = new Set<NodeId>();
  private edgeIds = new Set<EdgeId>();

  get nodes(): readonly NodeId[] {
    return [...this.nodeIds];
  }

  get edges(): readonly EdgeId[] {
    return [...this.edgeIds];
  }

  get size(): number {
    return this.nodeIds.size + this.edgeIds.size;
  }

  get isEmpty(): boolean {
    return this.size === 0;
  }

  /** The single selected node, or null when zero or several are selected. */
  get soleNode(): NodeId | null {
    return this.nodeIds.size === 1 && this.edgeIds.size === 0 ? (this.nodes[0] ?? null) : null;
  }

  hasNode(id: NodeId): boolean {
    return this.nodeIds.has(id);
  }

  hasEdge(id: EdgeId): boolean {
    return this.edgeIds.has(id);
  }

  selectNodes(ids: readonly NodeId[], mode: SelectionMode = 'replace'): void {
    const next = this.applyMode(this.nodeIds, ids, mode);
    // Selecting nodes clears any edge selection: the two are alternative
    // contexts for the inspector and the context toolbar.
    this.commit(next, mode === 'replace' ? new Set() : this.edgeIds);
  }

  selectEdges(ids: readonly EdgeId[], mode: SelectionMode = 'replace'): void {
    const next = this.applyMode(this.edgeIds, ids, mode);
    this.commit(mode === 'replace' ? new Set() : this.nodeIds, next);
  }

  set(nodes: readonly NodeId[], edges: readonly EdgeId[]): void {
    this.commit(new Set(nodes), new Set(edges));
  }

  clear(): void {
    this.commit(new Set(), new Set());
  }

  /**
   * Drops ids that no longer exist. Called after a deletion or an import so
   * the selection can't keep a removed node alive through a stale
   * reference.
   */
  prune(nodeExists: (id: NodeId) => boolean, edgeExists: (id: EdgeId) => boolean): void {
    const nodes = new Set([...this.nodeIds].filter(nodeExists));
    const edges = new Set([...this.edgeIds].filter(edgeExists));
    if (nodes.size === this.nodeIds.size && edges.size === this.edgeIds.size) return;
    this.commit(nodes, edges);
  }

  on(handler: (payload: SelectionEvents['changed']) => void): Unsubscribe {
    return this.bus.on('changed', handler);
  }

  dispose(): void {
    this.bus.dispose();
  }

  private applyMode<T>(current: Set<T>, ids: readonly T[], mode: SelectionMode): Set<T> {
    switch (mode) {
      case 'replace':
        return new Set(ids);
      case 'add': {
        const next = new Set(current);
        for (const id of ids) next.add(id);
        return next;
      }
      case 'subtract': {
        const next = new Set(current);
        for (const id of ids) next.delete(id);
        return next;
      }
      case 'toggle': {
        const next = new Set(current);
        for (const id of ids) {
          if (next.has(id)) next.delete(id);
          else next.add(id);
        }
        return next;
      }
    }
  }

  private commit(nodes: Set<NodeId>, edges: Set<EdgeId>): void {
    if (sameSet(nodes, this.nodeIds) && sameSet(edges, this.edgeIds)) return;
    this.nodeIds = nodes;
    this.edgeIds = edges;
    this.bus.emit('changed', { nodes: this.nodes, edges: this.edges });
  }
}

function sameSet<T>(a: Set<T>, b: Set<T>): boolean {
  if (a.size !== b.size) return false;
  for (const value of a) if (!b.has(value)) return false;
  return true;
}
