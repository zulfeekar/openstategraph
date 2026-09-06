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
  SizeOrigin,
} from './node';

export type EdgeId = string;

export interface IEdgeModel {
  readonly id: EdgeId;
  readonly source: PortRef;
  readonly target: PortRef;
  /** Optional label rendered mid-link. */
  readonly label: string | null;
  /**
   * Points the run is required to pass through, in document coordinates.
   *
   * Empty for almost every link: the router works out the whole run from the
   * two ports. A waypoint is what a user adds when they disagree with it, and
   * what `AutoLayout` seeds to give a back-edge its own lane.
   *
   * Data, never code — a serialisable list of numbers, so it costs the
   * portability rule nothing.
   */
  readonly vertices: readonly Point[];
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
  /**
   * Hand-placed (or layout-placed) waypoints, omitted when there are none.
   *
   * **Additive, so the schema version does not move.** `backend/.../schema.py`
   * states the rule in as many words — *"Do not bump: adding an optional field
   * with a safe default … anything additive that an older build ignores
   * harmlessly"* — and an older build ignoring `vertices` gets the router's own
   * run, which is what it drew before. Bumping would push every user's
   * document through a two-sided migration to gain nothing.
   */
  readonly vertices?: readonly Point[];
}

export interface SerializedWorkflow {
  /** Bumped when the shape changes; migrations key off it. */
  readonly version: number;
  readonly name: string;
  /**
   * Workflow-level configuration the runtime reads — the default model,
   * a recursion limit, a checkpointer choice (ticket 36), and the run-context
   * declaration below (`RUN_CONTEXT_SETTING`). Optional and omitted when
   * empty, so pre-existing documents keep their bytes. Absent keys mean
   * "inherit the runtime's default".
   */
  readonly settings?: Readonly<Record<string, unknown>>;
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
/**
 * Where a document declares what its runs carry — `organisms-first-class/67`,
 * step 1 of `docs/decisions/runtime-context.md`.
 *
 * A sibling of `model` and `recursionLimit` under `settings`, so
 * `DocumentController.setSetting(key, value)` — generic in the key since
 * `13fa2d7` — writes it with nothing new.
 */
export const RUN_CONTEXT_SETTING = 'context';

/**
 * The three types a declared field may have, and there will not be a fourth
 * soon.
 *
 * Not `object` and not `array`: a nested value cannot be rendered into a
 * generated prompt section honestly, and cannot be typed on a CLI flag without
 * inventing a parser — which is portability guardrail 1 asking to be broken. A
 * workflow needing structure declares a string and parses it in a tool it owns.
 */
export const RUN_CONTEXT_TYPES = ['string', 'number', 'boolean'] as const;

export type RunContextType = (typeof RUN_CONTEXT_TYPES)[number];

/**
 * Keys a declaration may not name, in any casing.
 *
 * **`configurable` is who the run is *for*; run context is what the workflow
 * asked its caller for.** These four are server-determined and unforgeable —
 * `RunRequest` deliberately carries no `user_email`, because that value keys a
 * per-person memory namespace and a client that could name the person could
 * read that person's memories. A field a caller fills may not be one of them.
 *
 * Mirrored from `backend/openstategraph/prebuilt_session.py`, which is the one
 * place they are listed, and pinned against it by
 * `backend/tests/test_run_context_declaration.py` — a hand-mirror without a
 * drift test is what the DRY rule forbids.
 */
export const RESERVED_RUN_CONTEXT_KEYS = [
  'user_email',
  'session_id',
  'thread_id',
  'workflow_slug',
] as const;

/**
 * One declared field, as it sits in `workflow.json`.
 *
 * **Descriptors only, never a type.** LangGraph's channel is a Python class
 * and the whole purpose of this feature is to let a document describe one;
 * portability guardrail 4 is satisfied by never storing it. There is no import
 * path here and nothing to resolve at load time, so a document declaring run
 * context is readable by a runtime that has never heard of LangGraph.
 *
 * A **scalar** default, absent meaning unset — a computed default would be
 * host-language code in a serialised field (guardrail 1), and a non-finite
 * number would not survive its own round trip (`maxConnections` is the worked
 * example).
 */
export interface RunContextField {
  readonly key: string;
  readonly type: RunContextType;
  readonly label?: string;
  readonly description?: string;
  readonly required?: boolean;
  /**
   * Whether this field's **value** may be rendered into a model's system
   * prompt (`organisms-first-class/72`). Absent means no, and that default is
   * the point: a run-context field is exactly where an API handle or a
   * caller's address ends up, and a tool must be able to read one without a
   * model ever seeing it. Opting in is one word; un-sending a handle is not
   * possible at all.
   */
  readonly prompt?: boolean;
  readonly default?: string | number | boolean;
}

const RESERVED_FOLDED = new Map(
  RESERVED_RUN_CONTEXT_KEYS.map((key) => [key.replace(/[^a-z0-9]/g, ''), key] as const),
);

const fold = (key: string): string => key.toLowerCase().replace(/[^a-z0-9]/g, '');

/**
 * Everything wrong with a document's run-context declaration, in order.
 *
 * Empty for a document that declares none *and* for one declaring an empty
 * list: both say "this workflow asks its caller for nothing". The empty list
 * is preserved rather than helpfully dropped, because a serializer that
 * rewrites a file nobody edited is a loss this repository has already paid for.
 *
 * The same sentences the compiler produces, deliberately — the editor is where
 * a mistake is cheapest to fix, and a second wording would be a second thing to
 * keep in step.
 */
export function runContextProblems(
  settings: Readonly<Record<string, unknown>> | undefined,
): string[] {
  const declared = settings?.[RUN_CONTEXT_SETTING];
  if (declared === undefined || declared === null) return [];
  if (!Array.isArray(declared)) {
    return [
      'Run context must be a list of field descriptors — order is the rendering contract, ' +
        'and JSON object key order is not.',
    ];
  }

  const problems: string[] = [];
  const seen = new Set<string>();
  declared.forEach((raw, index) => {
    const position = index + 1;
    if (typeof raw !== 'object' || raw === null) {
      problems.push(`Run context field at position ${position} is not an object.`);
      return;
    }
    const field = raw as Record<string, unknown>;
    const key = field['key'];
    if (typeof key !== 'string' || key.trim() === '') {
      problems.push(`Run context field at position ${position} declares no 'key'.`);
      return;
    }
    const type = field['type'];
    if (typeof type !== 'string' || !(RUN_CONTEXT_TYPES as readonly string[]).includes(type)) {
      problems.push(
        `Run context field '${key}' declares an unknown type — use one of: ` +
          `${RUN_CONTEXT_TYPES.join(', ')}.`,
      );
    }
    const reserved = RESERVED_FOLDED.get(fold(key));
    if (reserved !== undefined) {
      problems.push(
        `Run context field '${key}' names the reserved run identity key '${reserved}' — ` +
          'those are supplied by the server on every run and cannot be declared.',
      );
    }
    if ('default' in field) {
      const value = field['default'];
      if (typeof value === 'number' && !Number.isFinite(value)) {
        problems.push(
          `Run context field '${key}' has a default that is not a finite number — ` +
            'Infinity and NaN cannot survive a JSON round trip.',
        );
      } else if (typeof type === 'string' && typeof value !== type) {
        problems.push(
          `Run context field '${key}' declares type '${type}' and a default that is not one.`,
        );
      }
    }
    if (seen.has(key)) {
      problems.push(
        `Run context declares '${key}' more than once — each key may appear only once.`,
      );
    }
    seen.add(key);
  });
  return problems;
}

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
  'edge:vertices': { edgeId: EdgeId; vertices: readonly Point[] };
  'workflow:name': { name: string };
  'workflow:settings': { settings: Readonly<Record<string, unknown>> };
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
  /**
   * `origin` decides whether the document records the new size. A measurement
   * moves the card on screen and nothing else; see `SizeOrigin`.
   */
  resizeNode(id: NodeId, size: Size, origin?: SizeOrigin): void;
  setNodeData(id: NodeId, key: string, value: FieldValue): void;
  setNodeDataBulk(id: NodeId, patch: Partial<NodeData>): void;
  setNodeTitle(id: NodeId, title: string): void;
  setNodeRuntime(id: NodeId, runtime: Partial<NodeRuntimeState>): void;
  setNodeParent(id: NodeId, parentId: NodeId | null): void;
  addEdge(edge: IEdgeModel): void;
  removeEdge(id: EdgeId): IEdgeModel | undefined;
  setEdgeLabel(id: EdgeId, label: string | null): void;
  setEdgeVertices(id: EdgeId, vertices: readonly Point[]): void;
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
