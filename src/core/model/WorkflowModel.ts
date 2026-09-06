import { EventBus } from '@core/kernel/EventBus';
import type { Unsubscribe } from '@core/kernel/Disposable';
import type { Point, Rect, Size } from '@core/kernel/geometry';
import { sortByIdNatural } from '@core/kernel/ordering';
import { AdjacencyIndex } from './AdjacencyIndex';
import { GraphQueries } from './GraphQueries';
import type { AbstractNodeModel } from './AbstractNodeModel';
import type { EdgeModel } from './EdgeModel';
import type { FieldValue, NodeData } from './contracts/fields';
import type { PortRef } from './contracts/ports';
import type {
  INodeModel,
  NodeId,
  NodeRuntimeState,
  NodeTypeId,
  SizeOrigin,
} from './contracts/node';
import type {
  EdgeId,
  IEdgeModel,
  IWorkflowModel,
  SerializedWorkflow,
  WorkflowEvents,
} from './contracts/workflow';

/**
 * Current on-disk schema version. Bump alongside a migration.
 *
 * **Two-sided.** `backend/openstategraph/schema.py` declares the same number
 * and the same chain, because a document is written by one side and read by
 * the other. They move together or a document written here is refused there
 * as coming from the future — which is what a v3 stamp did until the editor's
 * own chain caught up (production-ready ticket 16).
 */
export const WORKFLOW_SCHEMA_VERSION = 3;

/**
 * The document.
 *
 * Every mutator is deliberately *primitive* — one concept, no policy. All
 * policy (what is legal, what should happen together, what can be undone)
 * lives in the command layer above. That is what lets undo be a generic
 * mechanism instead of a per-feature concern, and it keeps this class
 * small enough to reason about.
 *
 * Two collaborators split off the concerns that do not need this class's
 * event-emitting or serialisation responsibilities (ticket 17): incidence
 * bookkeeping (`AdjacencyIndex`) is maintained incrementally alongside the
 * edge map — rebuilding it per query was measurably the hot path while
 * dragging a link across a large graph, since validation walks the
 * neighbours of every port under the pointer — and the read-only graph
 * algorithms over that bookkeeping (`GraphQueries`). Neither is a second
 * public surface: this class's own public methods are unchanged and still
 * answer every one of these questions, just by delegating.
 */
export class WorkflowModel implements IWorkflowModel {
  private readonly bus = new EventBus<WorkflowEvents>();
  private readonly nodeMap = new Map<NodeId, AbstractNodeModel>();
  private readonly edgeMap = new Map<EdgeId, EdgeModel>();
  private readonly adjacency = new AdjacencyIndex();
  private readonly queries = new GraphQueries(this.nodeMap, this.edgeMap, this.adjacency);

  private _name: string;
  private _settings: Record<string, unknown> = {};

  constructor(name = 'Untitled workflow') {
    this._name = name;
  }

  /* ================================================================ *
   * Queries
   * ================================================================ */

  get name(): string {
    return this._name;
  }

  /** Workflow-level runtime configuration. Empty means "all defaults". */
  get settings(): Readonly<Record<string, unknown>> {
    return this._settings;
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

  edgesOf(nodeId: NodeId): readonly EdgeModel[] {
    return this.queries.edgesOf(nodeId);
  }

  edgesInto(ref: PortRef): readonly EdgeModel[] {
    return this.queries.edgesInto(ref);
  }

  edgesFrom(ref: PortRef): readonly EdgeModel[] {
    return this.queries.edgesFrom(ref);
  }

  childrenOf(nodeId: NodeId): readonly AbstractNodeModel[] {
    return this.queries.childrenOf(nodeId);
  }

  /** Children, grandchildren and so on. */
  descendantsOf(nodeId: NodeId): readonly AbstractNodeModel[] {
    return this.queries.descendantsOf(nodeId);
  }

  predecessorsOf(nodeId: NodeId): readonly AbstractNodeModel[] {
    return this.queries.predecessorsOf(nodeId);
  }

  successorsOf(nodeId: NodeId): readonly AbstractNodeModel[] {
    return this.queries.successorsOf(nodeId);
  }

  countOfType(type: NodeTypeId): number {
    return this.queries.countOfType(type);
  }

  /** Kahn's algorithm over executable nodes. See `GraphQueries.topologicalOrder`. */
  topologicalOrder(): { order: readonly NodeId[]; cycle: readonly NodeId[] | null } {
    return this.queries.topologicalOrder();
  }

  bounds(): Rect | null {
    return this.queries.bounds();
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
    this.adjacency.registerNode(concrete.id);
    if (concrete.parentId) this.adjacency.linkChild(concrete.parentId, concrete.id);
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

    if (node.parentId) this.adjacency.unlinkChild(node.parentId, id);
    this.adjacency.unregisterNode(id);
    this.nodeMap.delete(id);
    this.bus.emit('node:removed', { nodeId: id, node });
    return node;
  }

  moveNode(id: NodeId, position: Point): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    const previous = node.position;
    if (previous.x === position.x && previous.y === position.y) return;
    node.write.position(position);
    this.bus.emit('node:moved', { nodeId: id, position: node.position, previous });
  }

  resizeNode(id: NodeId, size: Size, origin: SizeOrigin = 'authored'): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    const previous = node.size;
    const unchanged = previous.width === size.width && previous.height === size.height;
    // A measurement that agrees with the card already on screen has nothing to
    // say. An *authored* one still does even when the pixels match: it is the
    // gesture that promotes the current size to document state, which is the
    // whole of the measured/authored split.
    if (unchanged && origin === 'measured') return;
    node.write.size(size, origin);
    if (unchanged) return;
    this.bus.emit('node:resized', { nodeId: id, size: node.size, previous });
  }

  setNodeData(id: NodeId, key: string, value: FieldValue): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    const previous = node.data[key] ?? null;
    if (previous === value) return;
    node.write.field(key, value);
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
    node.write.title(title);
    this.bus.emit('node:title', { nodeId: id, title: node.title });
  }

  setNodeRuntime(id: NodeId, runtime: Partial<NodeRuntimeState>): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    node.write.runtime(runtime);
    this.bus.emit('node:runtime', { nodeId: id, runtime: node.runtime });
  }

  setNodeParent(id: NodeId, parentId: NodeId | null): void {
    const node = this.nodeMap.get(id);
    if (!node) return;
    const previous = node.parentId;
    if (previous === parentId) return;
    // Refuse a cycle: a container cannot end up inside its own subtree.
    if (parentId && this.queries.isAncestorOf(id, parentId)) return;
    if (previous) this.adjacency.unlinkChild(previous, id);
    node.write.parent(parentId);
    if (parentId) this.adjacency.linkChild(parentId, id);
    this.bus.emit('node:parent', { nodeId: id, parentId, previous });
  }

  addEdge(edge: IEdgeModel): void {
    const concrete = edge as EdgeModel;
    if (this.edgeMap.has(concrete.id)) {
      throw new Error(`[workflow] duplicate edge id "${concrete.id}"`);
    }
    this.edgeMap.set(concrete.id, concrete);
    this.adjacency.registerEdge(concrete);
    this.bus.emit('edge:added', { edge: concrete });
  }

  removeEdge(id: EdgeId): EdgeModel | undefined {
    const edge = this.edgeMap.get(id);
    if (!edge) return undefined;
    this.edgeMap.delete(id);
    this.adjacency.unregisterEdge(edge);
    this.bus.emit('edge:removed', { edgeId: id, edge });
    return edge;
  }

  setEdgeLabel(id: EdgeId, label: string | null): void {
    const edge = this.edgeMap.get(id);
    if (!edge) return;
    edge.applyLabel(label);
    this.bus.emit('edge:label', { edgeId: id, label: edge.label });
  }

  setEdgeVertices(id: EdgeId, vertices: readonly Point[]): void {
    const edge = this.edgeMap.get(id);
    if (!edge) return;
    edge.applyVertices(vertices);
    this.bus.emit('edge:vertices', { edgeId: id, vertices: edge.vertices });
  }

  setName(name: string): void {
    const trimmed = name.trim() || 'Untitled workflow';
    if (trimmed === this._name) return;
    this._name = trimmed;
    this.bus.emit('workflow:name', { name: trimmed });
  }

  /**
   * Replaces (never merges) the workflow-level settings.
   *
   * Replacement semantics match import: loading a document that has no
   * settings must clear any stale ones, or a workflow would silently keep
   * another workflow's model choice. Copied defensively both ways.
   */
  setSettings(settings: Readonly<Record<string, unknown>>): void {
    this._settings = { ...settings };
    this.bus.emit('workflow:settings', { settings: this._settings });
  }

  /** Empties the document and tells listeners to resync from scratch. */
  clear(): void {
    this.transact(() => {
      this.nodeMap.clear();
      this.edgeMap.clear();
      this.adjacency.clear();
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
      // Omitted when empty: an always-present `settings: {}` would be a
      // whole-corpus diff the day the field shipped.
      ...(Object.keys(this._settings).length > 0 ? { settings: { ...this._settings } } : {}),
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
}
