import type { EdgeId } from './contracts/workflow';
import type { NodeId } from './contracts/node';
import type { IEdgeModel } from './contracts/workflow';

/**
 * Incidence bookkeeping for the graph: which edges touch a node, which
 * nodes are a container's children.
 *
 * Pulled out of `WorkflowModel` (ticket 17) because it is a genuinely
 * separate concern from graph *algorithms* — this class only ever answers
 * "what touches this id", in O(degree), and is *written* by every
 * add/remove mutation. Rebuilding it per query was measurably the hot path
 * while dragging a link across a large graph, since validation walks the
 * neighbours of every port under the pointer — which is exactly why this
 * stays incremental rather than derived on read.
 *
 * Deliberately dumb: it has no notion of a "document" or an "event", only
 * ids. `WorkflowModel` still owns emitting `node:added` etc.; this owns only
 * keeping the indices consistent with those same mutations.
 */
export class AdjacencyIndex {
  private readonly incident = new Map<NodeId, Set<EdgeId>>();
  private readonly children = new Map<NodeId, Set<NodeId>>();

  registerNode(id: NodeId): void {
    this.incident.set(id, new Set());
  }

  unregisterNode(id: NodeId): void {
    this.incident.delete(id);
    this.children.delete(id);
  }

  registerEdge(edge: IEdgeModel): void {
    this.incident.get(edge.source.nodeId)?.add(edge.id);
    this.incident.get(edge.target.nodeId)?.add(edge.id);
  }

  unregisterEdge(edge: IEdgeModel): void {
    this.incident.get(edge.source.nodeId)?.delete(edge.id);
    this.incident.get(edge.target.nodeId)?.delete(edge.id);
  }

  linkChild(parentId: NodeId, childId: NodeId): void {
    let set = this.children.get(parentId);
    if (!set) {
      set = new Set();
      this.children.set(parentId, set);
    }
    set.add(childId);
  }

  unlinkChild(parentId: NodeId, childId: NodeId): void {
    const set = this.children.get(parentId);
    set?.delete(childId);
    if (set?.size === 0) this.children.delete(parentId);
  }

  /** Edge ids touching `nodeId`, in either direction. Empty for an unknown id. */
  edgeIdsOf(nodeId: NodeId): ReadonlySet<EdgeId> {
    return this.incident.get(nodeId) ?? EMPTY_EDGE_IDS;
  }

  /** Direct child ids of a container. Empty for a leaf or unknown id. */
  childIdsOf(nodeId: NodeId): ReadonlySet<NodeId> {
    return this.children.get(nodeId) ?? EMPTY_NODE_IDS;
  }

  clear(): void {
    this.incident.clear();
    this.children.clear();
  }
}

const EMPTY_EDGE_IDS: ReadonlySet<EdgeId> = new Set();
const EMPTY_NODE_IDS: ReadonlySet<NodeId> = new Set();
