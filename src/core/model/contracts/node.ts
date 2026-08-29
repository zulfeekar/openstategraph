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

/**
 * One child a run spawned from this node, as a card can draw it.
 *
 * `canvas-feels-right/07`, the canvas half. Declared here rather than
 * imported from the fold that produces it (`view/spawned/spawnedTasks.ts`)
 * for the layering reason this directory exists: `core/` is the contract and
 * may not depend on `view/`. The fold's own `SpawnedTask` **extends** this,
 * so the knowledge is declared once and the extra fields it carries for the
 * chat panel — the run's task id, the owning node — stay out of a shape the
 * card does not need.
 *
 * `subgraph` is deliberately not a kind: a mounted workflow *is* a node in
 * the saved document with a card of its own, and a chip beside it would
 * claim runtime-only-ness about the one child that is genuinely part of the
 * file.
 */
export interface SpawnedChild {
  /** Stable across re-projections — the React key and the popover identity. */
  readonly key: string;
  readonly kind: 'fanout' | 'subagent' | 'async';
  /** What to call it: an archetype, or the declared subagent type. */
  readonly label: string;
  /** The brief it was given, as the spawn frame carried it. */
  readonly instruction: string;
  /** Its own account, oldest first — what `ThinkingStack` renders. */
  readonly lines: readonly string[];
  /**
   * Whether this run's stream ever carried a frame under this child's id.
   *
   * Not the same as `lines.length > 0`: a frame can come back carrying an
   * empty output, and *it reported and said nothing* is a different fact from
   * *nothing about it ever reached this stream*. Only a `fanout` child's own
   * frames come back on this stream at all — a `subagent` returns one
   * `ToolMessage` and an `async` runs on a desk outside the run — so an empty
   * account for those two is correct rather than missing, and the surface
   * says which in words.
   */
  readonly reported: boolean;
  /**
   * Whether this child outlives the run that launched it. `async` only.
   *
   * The other two end when this run ends, so a finished run is a finished
   * child; a background worker's answer arrives on a later turn, which is why
   * nothing ever calls one finished.
   */
  readonly detached: boolean;
}

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
  /**
   * What this node has said about itself, in order, during the current run.
   *
   * `launch-readiness/140`. Separate from `log`, which is the local preview
   * run's trace and is written by `ExecutionEngine`; this is the stream of
   * `progress` frames a *backend* run attributed to this card. Two fields
   * because they have two reasons to change and two writers — folding them
   * together would put a preview's tool-output line and a live narration
   * sentence in one list with no way to tell them apart.
   *
   * Kept after the node finishes, deliberately (the ticket's own open
   * question): a stack that empties at completion loses the account of what
   * happened, which is the only record a reader who cannot open a trace ever
   * gets. It is cleared by `IDLE_RUNTIME` at the *start* of the next run,
   * where "this is not this run's" first becomes true.
   */
  readonly narration: readonly string[];
  /**
   * What this run spawned *from* this node, one entry per child.
   *
   * `canvas-feels-right/07`. It sits beside `narration` for the same reason
   * and by the same mechanism: the panel projects what the stream said onto
   * the card the stream said it about, and the card is a read-only view of
   * that. It is **runtime state, never document state** — `setNodeRuntime`
   * is not a command, is not undoable, and is not serialised — which is how
   * a chip can hang off a card while satisfying the ticket's *nothing is
   * written to the graph*.
   *
   * The limitation this closes is `launch-readiness/140`'s own: a `Send`
   * fan-out creates **tasks, not canvas nodes**, so three parallel workers
   * all dispatch from one card and the canvas draws one box. Three entries
   * here are three chips.
   *
   * Cleared by `IDLE_RUNTIME` at the start of the next run, exactly as
   * `narration` is.
   */
  readonly spawned: readonly SpawnedChild[];
}

export const IDLE_RUNTIME: NodeRuntimeState = {
  status: 'idle',
  output: null,
  error: null,
  tokens: 0,
  durationMs: null,
  log: [],
  narration: [],
  spawned: [],
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
  /**
   * Whether two of this node's `branch` outputs can be live in the same run.
   *
   * Absent means **yes, they are exclusive** — that is what
   * `IPortDescriptor.branch` already declares ("one of several mutually
   * exclusive ways out"), so nothing has to opt in. A family that can take
   * more than one way out at once opts *out*, and exactly one does: a Router
   * set to *run every match, in parallel* dispatches to every branch that
   * matched, in one superstep (`workflow-gallery/64`).
   *
   * On the contract because port capacity asks it (`concurrentProducers.ts`)
   * and capacity may not know node types — a plugin's own broadcasting
   * conditional answers here and needs no edit in `core/`.
   */
  readonly branchesAreExclusive?: boolean;

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

/**
 * Where a size came from, which decides whether the document records it.
 *
 * `'authored'` — somebody set it: the resize grip, `Arrange` refitting a
 * frame, an assembly sizing a node it creates. `'measured'` — the view read
 * the rendered card's height and reported it back, which the model needs and
 * the file must not carry.
 */
export type SizeOrigin = 'authored' | 'measured';

/**
 * Whether a card of this kind reports its own height back to the model.
 *
 * Every card but a container's frame is content-driven: `NodeCard` measures
 * the rendered HTML and calls `applyMeasuredSize`, so its height is a property
 * of this build's styling rather than of the workflow. A frame is the
 * exception — its size comes from the resize grip or from `Arrange` refitting
 * it, and nothing else moves it.
 *
 * Stated once here because two places act on it and they must not drift: the
 * model, which serialises the authored size, and `diskAutosave.comparable`,
 * which decides whether a size change is worth a write (`production-ready` 70).
 */
export function sizeIsMeasured(kind: NodeKind): boolean {
  return kind !== 'container';
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
  /**
   * The *authored* size — what a grip, an `Arrange` refit or the assembly
   * that created the node set. Never the height the browser measured off the
   * rendered card, which is a property of the build (`production-ready` 69).
   *
   * Optional because a hand-written document may leave it out; the loader
   * falls back to the type's `defaultSize`, which is what the examples in
   * `docs/api.md` and `docs/mcp.md` already rely on.
   */
  readonly size?: Size;
  readonly parentId: NodeId | null;
  readonly data: NodeData;
  readonly title?: string;
}
