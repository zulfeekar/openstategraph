import type { Unsubscribe } from '@core/kernel/Disposable';
import type { Point, Rect, Size } from '@core/kernel/geometry';
import type { FieldValue, NodeData } from './fields';
import type { PortRef } from './ports';
import type {
  INodeModel,
  NodeId,
  NodeRuntimeState,
  NodeTypeId,
  SerializedNode,
} from './node';

export type EdgeId = string;

export interface IEdgeModel {
  readonly id: EdgeId;
  readonly source: PortRef;
  readonly target: PortRef;
  /** Optional label rendered mid-link. */
  readonly label: string | null;
  toJSON(): SerializedEdge;
}

/**
 * A link on disk, identified by its endpoints rather than by an id.
 *
 * An edge's id is an internal handle: nodes are referenced by edges, but an
 * edge is referenced by nothing, so the id carries no information a reader or
 * a reloader needs. Writing it would leak the creation counter into a tracked
 * file — two people drawing the same graph in a different order would get
 * different bytes, and inserting one link would renumber the rest of the diff.
 */
export interface SerializedEdge {
  readonly source: PortRef;
  readonly target: PortRef;
  readonly label?: string | null;
}

export interface SerializedWorkflow {
  /** Bumped when the shape changes; migrations key off it. */
  readonly version: number;
  readonly name: string;
  readonly nodes: readonly SerializedNode[];
  readonly edges: readonly SerializedEdge[];
  readonly meta?: Readonly<Record<string, unknown>>;
}

/**
 * Model change notifications.
 *
 * Fine-grained on purpose: the canvas adapter patches a single JointJS
 * cell in response to `node:moved`, where a coarse "something changed"
 * event would force it to reconcile the entire graph on every drag frame.
 */
export interface WorkflowEvents extends Record<string, unknown> {
  'node:added': { node: INodeModel };
  'node:removed': { nodeId: NodeId; node: INodeModel };
  'node:moved': { nodeId: NodeId; position: Point; previous: Point };
  'node:resized': { nodeId: NodeId; size: Size; previous: Size };
  'node:data': { nodeId: NodeId; key: string; value: FieldValue; previous: FieldValue };
  'node:title': { nodeId: NodeId; title: string };
  'node:runtime': { nodeId: NodeId; runtime: NodeRuntimeState };
  'node:parent': { nodeId: NodeId; parentId: NodeId | null; previous: NodeId | null };
  'edge:added': { edge: IEdgeModel };
  'edge:removed': { edgeId: EdgeId; edge: IEdgeModel };
  'edge:label': { edgeId: EdgeId; label: string | null };
  'workflow:name': { name: string };
  /** Wholesale replacement (import, new document) — listeners resync fully. */
  'workflow:reset': { workflow: IWorkflowModel };
}

/**
 * The aggregate root. Owns nodes and edges and is the only thing allowed
 * to mutate them; callers reach it through commands so every change is
 * undoable.
 */
export interface IWorkflowModel {
  readonly name: string;

  /* ---- queries ---- */
  nodes(): readonly INodeModel[];
  edges(): readonly IEdgeModel[];
  node(id: NodeId): INodeModel | undefined;
  requireNode(id: NodeId): INodeModel;
  edge(id: EdgeId): IEdgeModel | undefined;
  hasNode(id: NodeId): boolean;

  /** Edges touching a node in either direction. */
  edgesOf(nodeId: NodeId): readonly IEdgeModel[];
  /** Edges arriving at a specific input port. */
  edgesInto(ref: PortRef): readonly IEdgeModel[];
  /** Edges leaving a specific output port. */
  edgesFrom(ref: PortRef): readonly IEdgeModel[];
  /** Direct children of a container node. */
  childrenOf(nodeId: NodeId): readonly INodeModel[];
  /** Immediate upstream neighbours. */
  predecessorsOf(nodeId: NodeId): readonly INodeModel[];
  /** Immediate downstream neighbours. */
  successorsOf(nodeId: NodeId): readonly INodeModel[];
  countOfType(type: NodeTypeId): number;

  /** Execution order, or the cycle that prevents one. */
  topologicalOrder(): { order: readonly NodeId[]; cycle: readonly NodeId[] | null };
  /** Bounding box of all nodes, or null when empty. */
  bounds(): Rect | null;

  /* ---- mutation (invoked by commands) ---- */
  addNode(node: INodeModel): void;
  removeNode(id: NodeId): INodeModel | undefined;
  moveNode(id: NodeId, position: Point): void;
  resizeNode(id: NodeId, size: Size): void;
  setNodeData(id: NodeId, key: string, value: FieldValue): void;
  setNodeDataBulk(id: NodeId, patch: Partial<NodeData>): void;
  setNodeTitle(id: NodeId, title: string): void;
  setNodeRuntime(id: NodeId, runtime: Partial<NodeRuntimeState>): void;
  setNodeParent(id: NodeId, parentId: NodeId | null): void;
  addEdge(edge: IEdgeModel): void;
  removeEdge(id: EdgeId): IEdgeModel | undefined;
  setEdgeLabel(id: EdgeId, label: string | null): void;
  setName(name: string): void;

  /* ---- document lifecycle ---- */
  toJSON(): SerializedWorkflow;
  /** Batches events so listeners see one flush for a composite change. */
  transact<T>(fn: () => T): T;

  /* ---- observation ---- */
  on<K extends keyof WorkflowEvents & string>(
    type: K,
    handler: (payload: WorkflowEvents[K]) => void,
  ): Unsubscribe;
  onAny(handler: (type: string) => void): Unsubscribe;
}
