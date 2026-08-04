import { EventBus } from '@core/kernel/EventBus';
import type { Unsubscribe } from '@core/kernel/Disposable';
import { unionRects, type Point, type Rect, type Size } from '@core/kernel/geometry';
import { sortByIdNatural } from '@core/kernel/ordering';
import type { AbstractNodeModel } from './AbstractNodeModel';
import type { EdgeModel } from './EdgeModel';
import type { FieldValue, NodeData } from './contracts/fields';
import { portRefEquals, type PortRef } from './contracts/ports';
import type {
  INodeModel,
  NodeId,
  NodeRuntimeState,
  NodeTypeId,
} from './contracts/node';
import type {
  EdgeId,
  IEdgeModel,
  IWorkflowModel,
  SerializedWorkflow,
  WorkflowEvents,
} from './contracts/workflow';

/** Current on-disk schema version. Bump alongside a migration. */
export const WORKFLOW_SCHEMA_VERSION = 1;

/**
 * The document.
 *
 * Every mutator is deliberately *primitive* — one concept, no policy. All
 * policy (what is legal, what should happen together, what can be undone)
 * lives in the command layer above. That is what lets undo be a generic
 * mechanism instead of a per-feature concern, and it keeps this class
 * small enough to reason about.
 *
 * Adjacency is maintained incrementally alongside the edge map. Rebuilding
 * it per query was measurably the hot path while dragging a link across a
 * large graph, since validation walks the neighbours of every port under
 * the pointer.
 */
export class WorkflowModel implements IWorkflowModel {
  private readonly bus = new EventBus<WorkflowEvents>();
  private readonly nodeMap = new Map<NodeId, AbstractNodeModel>();
  private readonly edgeMap = new Map<EdgeId, EdgeModel>();

  /** nodeId → edge ids touching it, for O(degree) neighbour queries. */
  private readonly incident = new Map<NodeId, Set<EdgeId>>();
  /** parentId → child ids. */
  private readonly children = new Map<NodeId, Set<NodeId>>();

  private _name: string;

  constructor(name = 'Untitled workflow') {
    this._name = name;
  }

  /* ================================================================ *
   * Queries
   * ================================================================ */

  get name(): string {
    return this._name;
  }

  nodes(): readonly INodeModel[] {
    return [...this.nodeMap.values()];
  }

  edges(): readonly IEdgeModel[] {
    return [...this.edgeMap.values()];
  }

  node(id: NodeId): AbstractNodeModel | undefined {
    return this.nodeMap.get(id);
  }

  requireNode(id: NodeId): AbstractNodeModel {
    const node = this.nodeMap.get(id);
    if (!node) throw new Error(`[workflow] no node "${id}"`);
    return node;
  }

  edge(id: EdgeId): EdgeModel | undefined {
    return this.edgeMap.get(id);
  }

  hasNode(id: NodeId): boolean {
    return this.nodeMap.has(id);
  }

  get nodeCount(): number {
    return this.nodeMap.size;
  }

  get edgeCount(): number {
    return this.edgeMap.size;
  }

  get isEmpty(): boolean {
    return this.nodeMap.size === 0;
  }

  edgesOf(nodeId: NodeId): readonly EdgeModel[] {
    const ids = this.incident.get(nodeId);
    if (!ids) return [];
    const result: EdgeModel[] = [];
    for (const id of ids) {
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
    const ids = this.children.get(nodeId);
    if (!ids) return [];
    const result: AbstractNodeModel[] = [];
    for (const id of ids) {
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

  /**
   * Kahn's algorithm over executable nodes.
   *
   * Returns the surviving cycle when one exists rather than throwing — the
   * UI needs to highlight the offending nodes, and a cyclic graph is a
   * thing a user can legitimately draw on the way to a valid one.
   */
  topologicalOrder(): { order: readonly NodeId[]; cycle: readonly NodeId[] | null } {
    const indegree = new Map<NodeId, number>();
    const outgoing = new Map<NodeId, NodeId[]>();

    for (const node of this.nodeMap.values()) {
      if (!node.isExecutable) continue;
      indegree.set(node.id, 0);
      outgoing.set(node.id, []);
    }

    for (const edge of this.edgeMap.values()) {
      const from = edge.source.nodeId;
      const to = edge.target.nodeId;
      // Skip edges touching non-executable nodes so annotations and
      // containers cannot stall the schedule.
      if (!indegree.has(from) || !indegree.has(to)) continue;
      outgoing.get(from)?.push(to);
      indegree.set(to, (indegree.get(to) ?? 0) + 1);
    }

    // Seed in insertion order so an unconstrained graph runs in the order
    // the user built it — surprising ordering makes runs hard to debug.
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

    const cycle = [...indegree.entries()]
      .filter(([, degree]) => degree > 0)
      .map(([id]) => id);
    return { order, cycle };
  }

  bounds(): Rect | null {
    const rects = [...this.nodeMap.values()].map((node) => ({
      x: node.position.x,
      y: node.position.y,
      width: node.size.width,
      height: node.size.height,
    }));
    return unionRects(rects);
  }

  /* ================================================================ *
   * Mutation — invoked by commands, never by the view
   * ================================================================ */

  addNode(node: INodeModel): void {
    const concrete = node as AbstractNodeModel;
    if (this.nodeMap.has(concrete.id)) {
      throw new Error(`[workflow] duplicate node id "${concrete.id}"`);
    }
    this.nodeMap.set(concrete.id, concrete);
    this.incident.set(concrete.id, new Set());
    if (concrete.parentId) this.linkChild(concrete.parentId, concrete.id);
    this.bus.emit('node:added', { node: concrete });
  }

  removeNode(id: NodeId): AbstractNodeModel | undefined {
    const node = this.nodeMap.get(id);
    if (!node) return undefined;

    // Detach edges first so no listener ever observes a dangling endpoint.
    for (const edge of this.edgesOf(id)) this.removeEdge(edge.id);

    // Orphaned children are promoted to the root rather than deleted; a
    // container is a grouping affordance, not an owner of its contents.
    for (const child of this.childrenOf(id)) this.setNodeParent(child.id, null);

    if (node.parentId) this.unlinkChild(node.parentId, id);
    this.children.delete(id);
    this.incident.delete(id);
    this.nodeMap.delete(id);
    this.bus.emit('node:removed', { nodeId: id, node });
    return node;
  }

  moveNode(id: NodeId, position: Point): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    const previous = node.position;
    if (previous.x === position.x && previous.y === position.y) return;
    node.applyPosition(position);
    this.bus.emit('node:moved', { nodeId: id, position: node.position, previous });
  }

  resizeNode(id: NodeId, size: Size): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    const previous = node.size;
    if (previous.width === size.width && previous.height === size.height) return;
    node.applySize(size);
    this.bus.emit('node:resized', { nodeId: id, size: node.size, previous });
  }

  setNodeData(id: NodeId, key: string, value: FieldValue): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    const previous = node.data[key] ?? null;
    if (previous === value) return;
    node.applyField(key, value);
    this.bus.emit('node:data', { nodeId: id, key, value, previous });
  }

  setNodeDataBulk(id: NodeId, patch: Partial<NodeData>): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    // Emit per key so listeners keyed on a specific field still fire; the
    // surrounding transact() collapses them into one flush.
    this.transact(() => {
      for (const [key, value] of Object.entries(patch)) {
        if (value === undefined) continue;
        this.setNodeData(id, key, value);
      }
    });
  }

  setNodeTitle(id: NodeId, title: string): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    node.applyTitle(title);
    this.bus.emit('node:title', { nodeId: id, title: node.title });
  }

  setNodeRuntime(id: NodeId, runtime: Partial<NodeRuntimeState>): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    node.applyRuntime(runtime);
    this.bus.emit('node:runtime', { nodeId: id, runtime: node.runtime });
  }

  setNodeParent(id: NodeId, parentId: NodeId | null): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    const previous = node.parentId;
    if (previous === parentId) return;
    // Refuse a cycle: a container cannot end up inside its own subtree.
    if (parentId && this.isAncestorOf(id, parentId)) return;
    if (previous) this.unlinkChild(previous, id);
    node.applyParent(parentId);
    if (parentId) this.linkChild(parentId, id);
    this.bus.emit('node:parent', { nodeId: id, parentId, previous });
  }

  addEdge(edge: IEdgeModel): void {
    const concrete = edge as EdgeModel;
    if (this.edgeMap.has(concrete.id)) {
      throw new Error(`[workflow] duplicate edge id "${concrete.id}"`);
    }
    this.edgeMap.set(concrete.id, concrete);
    this.incident.get(concrete.source.nodeId)?.add(concrete.id);
    this.incident.get(concrete.target.nodeId)?.add(concrete.id);
    this.bus.emit('edge:added', { edge: concrete });
  }

  removeEdge(id: EdgeId): EdgeModel | undefined {
    const edge = this.edgeMap.get(id);
    if (!edge) return undefined;
    this.edgeMap.delete(id);
    this.incident.get(edge.source.nodeId)?.delete(id);
    this.incident.get(edge.target.nodeId)?.delete(id);
    this.bus.emit('edge:removed', { edgeId: id, edge });
    return edge;
  }

  setEdgeLabel(id: EdgeId, label: string | null): void {
    const edge = this.edgeMap.get(id);
    if (!edge) return;
    edge.applyLabel(label);
    this.bus.emit('edge:label', { edgeId: id, label: edge.label });
  }

  setName(name: string): void {
    const trimmed = name.trim() || 'Untitled workflow';
    if (trimmed === this._name) return;
    this._name = trimmed;
    this.bus.emit('workflow:name', { name: trimmed });
  }

  /** Empties the document and tells listeners to resync from scratch. */
  clear(): void {
    this.transact(() => {
      this.nodeMap.clear();
      this.edgeMap.clear();
      this.incident.clear();
      this.children.clear();
    });
    this.bus.emit('workflow:reset', { workflow: this });
  }

  /** Announces a wholesale change made by the deserializer. */
  notifyReset(): void {
    this.bus.emit('workflow:reset', { workflow: this });
  }

  /* ================================================================ *
   * Lifecycle & observation
   * ================================================================ */

  transact<T>(fn: () => T): T {
    return this.bus.batch(fn);
  }

  /**
   * A link's sort key: everything that identifies it, source before target.
   *
   * NUL separates the parts so a port named `a-b` cannot collide with a
   * node `a` and port `b`.
   */
  private static endpointKey(edge: IEdgeModel): string {
    const { source, target } = edge;
    return [source.nodeId, source.portId, target.nodeId, target.portId].join('\u0000');
  }

  /**
   * Serialises the document in a canonical order.
   *
   * Rows are sorted rather than emitted in `Map` insertion order. Insertion
   * order is not stable for a given graph: deleting a node and undoing
   * re-inserts it at the end, so an identical document would
   * serialise differently. Since `workflow.json` is git-tracked and read in
   * diffs, that would turn every save into a whole-file change and make
   * review — human or agent — impossible.
   */
  toJSON(): SerializedWorkflow {
    return {
      version: WORKFLOW_SCHEMA_VERSION,
      name: this._name,
      nodes: sortByIdNatural(this.nodes(), (node) => node.id).map((node) => node.toJSON()),
      // Edges sort by endpoints, not by id — the id is a creation counter and
      // is not written to the file at all.
      edges: sortByIdNatural(this.edges(), WorkflowModel.endpointKey).map((edge) => edge.toJSON()),
    };
  }

  on<K extends keyof WorkflowEvents & string>(
    type: K,
    handler: (payload: WorkflowEvents[K]) => void,
  ): Unsubscribe {
    return this.bus.on(type, handler);
  }

  onAny(handler: (type: string) => void): Unsubscribe {
    return this.bus.onAny((type) => handler(type));
  }

  dispose(): void {
    this.bus.dispose();
  }

  /* ================================================================ *
   * Internals
   * ================================================================ */

  private linkChild(parentId: NodeId, childId: NodeId): void {
    let set = this.children.get(parentId);
    if (!set) {
      set = new Set();
      this.children.set(parentId, set);
    }
    set.add(childId);
  }

  private unlinkChild(parentId: NodeId, childId: NodeId): void {
    const set = this.children.get(parentId);
    set?.delete(childId);
    if (set?.size === 0) this.children.delete(parentId);
  }

  private isAncestorOf(ancestorId: NodeId, nodeId: NodeId): boolean {
    let current = this.nodeMap.get(nodeId)?.parentId ?? null;
    while (current) {
      if (current === ancestorId) return true;
      current = this.nodeMap.get(current)?.parentId ?? null;
    }
    return false;
  }
}
