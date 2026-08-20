import type { Accent } from '@design/tokens';
import type { IIdentifiable } from '@core/kernel/Registry';
import type { Point, Size } from '@core/kernel/geometry';
import type { FieldSchema, FieldValue, NodeData } from './fields';
import type { IPortDescriptor } from './ports';

export type NodeTypeId = string;
export type NodeId = string;

/** Palette grouping. Registered separately so plugins can add sections. */
export type NodeCategoryId = string;

export interface INodeCategory extends IIdentifiable {
  readonly id: NodeCategoryId;
  readonly label: string;
  /** Lower sorts first in the palette. */
  readonly order: number;
  /**
   * One sentence shown under the section heading — what makes something
   * belong to this tier. Optional: a section whose label already says it
   * all should not be padded with prose.
   */
  readonly description?: string;
}

/**
 * How the canvas treats a node structurally.
 *
 * `standard` — a card with ports.
 * `container` — can embed other nodes and resizes to fit them.
 * `annotation` — decorative; excluded from execution and from validation.
 */
export type NodeKind = 'standard' | 'container' | 'annotation';

/**
 * Per-node execution state, surfaced as the status dot on the card.
 *
 * `paused` is its own state and not a flavour of `running` (UX-01): a run
 * stopped at a `human.approval` node is *not* working, and marking it
 * `running` had the canvas sweep its glow over the very node that was waiting
 * on the person reading it. It is not `success` either — the node has not
 * completed. The visual rule that follows: nothing about `paused` animates.
 */
export type NodeStatus = 'idle' | 'ready' | 'running' | 'paused' | 'success' | 'warning' | 'error';

/**
 * Whether a node type is always available or belongs to the open workflow.
 * See `INodeDefinition.scope`.
 */
export type NodeScope = 'workflow' | 'app';

/** Live execution result attached to a node between runs. */
export interface NodeRuntimeState {
  readonly status: NodeStatus;
  /** Value produced on the node's primary output port. */
  readonly output: unknown;
  readonly error: string | null;
  /** Tokens attributed to this node in the last run. */
  readonly tokens: number;
  /** Wall-clock duration of the last run, in ms. */
  readonly durationMs: number | null;
  /** Human-readable trace lines for the run log. */
  readonly log: readonly string[];
}

export const IDLE_RUNTIME: NodeRuntimeState = {
  status: 'idle',
  output: null,
  error: null,
  tokens: 0,
  durationMs: null,
  log: [],
};

/**
 * The read-only view of a node that everything outside the model sees.
 * Mutation goes exclusively through commands on the controller, so the
 * canvas and the React tree are handed this narrow interface.
 */
export interface INodeModel {
  readonly id: NodeId;
  readonly type: NodeTypeId;
  readonly kind: NodeKind;
  readonly definition: INodeDefinition;
  readonly position: Point;
  readonly size: Size;
  /** Container this node is embedded in, if any. */
  readonly parentId: NodeId | null;
  readonly data: Readonly<NodeData>;
  readonly runtime: NodeRuntimeState;
  /** Ports for the node's *current* data — a node type may vary them. */
  readonly ports: readonly IPortDescriptor[];
  /** Card title; may be overridden per-instance. */
  readonly title: string;
  /**
   * Whether `title` is this node's own name or its type's label.
   *
   * On the contract rather than only on `AbstractNodeModel` because the
   * distinction is a consumer's question, not an implementation detail: a
   * document with three untitled workers has three nodes whose `title` is
   * `"Worker"`, and anything naming one of them — a run's lane header, a
   * diagnostic, a diff — has to be able to tell "unnamed" from "named
   * Worker" (`memory-and-replay` 39).
   */
  readonly hasCustomTitle: boolean;
  readonly subtitle: string;

  getField<T extends FieldValue>(key: string): T;
  port(portId: string): IPortDescriptor | undefined;
  toJSON(): SerializedNode;
}

/**
 * Everything the app needs to know about a node *type*.
 *
 * This is the extension point: `NodeTypeRegistry.register(definition)` is
 * the whole cost of adding a node. The palette, canvas, inspector,
 * serializer and execution engine all read from here, so none of them
 * needs a branch per node type.
 */
export interface INodeDefinition extends IIdentifiable {
  readonly id: NodeTypeId;
  readonly kind: NodeKind;
  readonly category: NodeCategoryId;
  /** Palette + card title. */
  readonly label: string;
  /** One-line palette + card description. */
  readonly description: string;
  /** Icon token resolved by the view's icon registry. */
  readonly iconId: string;
  readonly accent: Accent;
  readonly fields: readonly FieldSchema[];
  /** Ports for a given data state; static for most node types. */
  readonly ports: (data: Readonly<NodeData>) => readonly IPortDescriptor[];
  readonly defaultSize: Size;
  /** Instances allowed on one canvas. Omit for unlimited. */
  readonly maxInstances?: number;
  /** Hide from the palette (used by container/annotation helpers). */
  readonly hiddenInPalette?: boolean;
  /** Custom card body component id, resolved by the view's body registry. */
  readonly bodyId?: string;
  /** Keywords that should match this node in palette search. */
  readonly keywords?: readonly string[];
  /**
   * Where this node type comes from, for the palette to say so.
   *
   * `'app'` (the default when omitted) — an app-wide prebuilt: agents,
   * router, grader, platform tools. Always available, in every workflow.
   *
   * `'workflow'` — registered only while a particular workflow is open,
   * because it belongs to that workflow's own package (`syncWorkflowScopedNodes`,
   * `registerDiscoveredCapabilities`). It travels with the workflow and
   * disappears when another one is opened, so the palette must not present
   * it as if it were always there.
   *
   * Optional and additive: nothing outside the palette branches on it, and
   * a node type that never says anything is treated as `'app'`.
   */
  readonly scope?: NodeScope;
  /**
   * True when this node type's capability reaches the run **without being
   * wired to anything** (ticket 09).
   *
   * Knowledge is the worked case: the runtime attaches the lookup tool to
   * every agent and worker in the package whenever `knowledge/` holds at least
   * one `.md`, card or no card. The card is a visible declaration and the home
   * of the build button, not a connection — so "isn't connected to anything",
   * true of the graph, is false about the consequence, and the canvas is the
   * one surface this project insists must be a truthful projection.
   *
   * A flag on the type rather than a list inside the rule, so the next ambient
   * capability declares itself instead of needing an edit to `core/`.
   */
  readonly bindsWithoutWiring?: boolean;
  /**
   * Constructs the instance. Concrete node classes are reached only
   * through here, which is what keeps the model open for extension and
   * closed for modification.
   */
  readonly create: (init: NodeInit) => INodeModel;
}

export interface NodeInit {
  readonly id?: NodeId;
  readonly position: Point;
  readonly size?: Size;
  readonly parentId?: NodeId | null;
  /** Partial data merged over the schema defaults. */
  readonly data?: Partial<NodeData>;
  readonly title?: string;
}

/* ------------------------------------------------------------------ *
 * Serialization shapes — the on-disk contract. Versioned separately
 * from the model classes so a stored workflow keeps loading after the
 * classes are refactored.
 * ------------------------------------------------------------------ */

export interface SerializedNode {
  readonly id: NodeId;
  readonly type: NodeTypeId;
  readonly position: Point;
  readonly size: Size;
  readonly parentId: NodeId | null;
  readonly data: NodeData;
  readonly title?: string;
}
