import { nextId } from '@core/kernel/id';
import { withSortedKeys } from '@core/kernel/ordering';
import { finitePoint, finiteSize, type Point, type Size } from '@core/kernel/geometry';
import {
  canonicalRow,
  defaultsFrom,
  mergeData,
  withoutDisplayOnly,
  type FieldValue,
  type NodeData,
} from './contracts/fields';
import type { IPortDescriptor } from './contracts/ports';
import {
  IDLE_RUNTIME,
  type INodeDefinition,
  type INodeModel,
  type NodeId,
  type NodeInit,
  type NodeKind,
  type NodeRuntimeState,
  type SerializedNode,
} from './contracts/node';

/**
 * Base class for every node.
 *
 * Holds the state each node shares — identity, geometry, embedding,
 * configuration data and runtime status — and leaves subclasses to answer
 * only what actually differs between node types. That split is why the
 * concrete classes below are a dozen lines each.
 *
 * Mutators are named `apply*` and are called **only** by `WorkflowModel`,
 * which owns change notification. A node cannot announce its own changes
 * because it has no reference to the graph it lives in; keeping that
 * one-way makes it impossible to mutate a node without an event firing.
 */
/**
 * The node's write side, handed only to `WorkflowModel`.
 *
 * Named as an interface so the rule has something to point at, and so the
 * grep in `nodeWriteSeam.test.ts` has a stable shape to look for.
 */
export interface NodeWrite {
  position(position: Point): void;
  size(size: Size): void;
  parent(parentId: NodeId | null): void;
  field(key: string, value: FieldValue): void;
  title(title: string): void;
  runtime(patch: Partial<NodeRuntimeState>): void;
}

/** Where a node lands when the position it was given is not a number. */
const ORIGIN: Point = { x: 0, y: 0 };

export abstract class AbstractNodeModel implements INodeModel {
  readonly id: NodeId;
  readonly definition: INodeDefinition;

  protected _position: Point;
  protected _size: Size;
  protected _parentId: NodeId | null;
  protected _data: NodeData;
  protected _runtime: NodeRuntimeState = IDLE_RUNTIME;
  protected _title: string | null;

  constructor(definition: INodeDefinition, init: NodeInit) {
    this.definition = definition;
    this.id = init.id ?? nextId('node', definition.id);
    // The third door, and the one a file walks in by: the serializer passes
    // `serialized.position` here verbatim, so a hand-edited or truncated
    // document is where a non-finite coordinate is most likely to originate.
    // The origin is the fallback because at construction there is no previous
    // value to keep — a node at (0, 0) is findable, a node at NaN is not.
    this._position = finitePoint(init.position, ORIGIN);
    this._size = finiteSize(init.size ?? definition.defaultSize, definition.defaultSize);
    this._parentId = init.parentId ?? null;
    // Schema defaults first so a node loaded from an older document gains
    // any field added since it was saved.
    //
    // `withoutDisplayOnly` is what stops the inspector's help text living in
    // the user's repository (ticket 52). `defaultsFrom` no longer seeds one,
    // so this is only about `init.data` — a document saved *before* the fix
    // still carries the prose, and dropping it here means opening and saving
    // that document cleans it, with no schema migration for keys that never
    // meant anything.
    this._data = mergeData(
      defaultsFrom(definition.fields),
      init.data ? withoutDisplayOnly(init.data as NodeData, definition.fields) : undefined,
    );
    this._title = init.title ?? null;
  }

  /* ---------------- identity & presentation ---------------- */

  get type(): string {
    return this.definition.id;
  }

  get kind(): NodeKind {
    return this.definition.kind;
  }

  get title(): string {
    return this._title ?? this.definition.label;
  }

  /**
   * Card subtitle. Defaults to the type's description; override to reflect
   * live configuration instead (see `ToolNodeModel`).
   */
  get subtitle(): string {
    return this.definition.description;
  }

  /** True when the instance carries its own title rather than the type's. */
  get hasCustomTitle(): boolean {
    return this._title != null;
  }

  /* ---------------- geometry ---------------- */

  get position(): Point {
    return this._position;
  }

  get size(): Size {
    return this._size;
  }

  get parentId(): NodeId | null {
    return this._parentId;
  }

  /* ---------------- data ---------------- */

  get data(): Readonly<NodeData> {
    return this._data;
  }

  getField<T extends FieldValue>(key: string): T {
    return this._data[key] as T;
  }

  /** Convenience for the common string case, with an empty-string default. */
  getText(key: string): string {
    const value = this._data[key];
    return typeof value === 'string' ? value : '';
  }

  getNumber(key: string, fallback = 0): number {
    const value = this._data[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
  }

  /* ---------------- ports ---------------- */

  /**
   * Derived from the definition and the current data, so a node type can
   * vary its ports with configuration without any special-casing here.
   */
  get ports(): readonly IPortDescriptor[] {
    return this.definition.ports(this._data);
  }

  port(portId: string): IPortDescriptor | undefined {
    return this.ports.find((p) => p.id === portId);
  }

  get inputs(): readonly IPortDescriptor[] {
    return this.ports.filter((p) => p.direction === 'in');
  }

  get outputs(): readonly IPortDescriptor[] {
    return this.ports.filter((p) => p.direction === 'out');
  }

  /** The port a downstream consumer reads by default. */
  get primaryOutput(): IPortDescriptor | undefined {
    return this.outputs[0];
  }

  /** The port an upstream producer feeds by default — e.g. a splice-insert's target. */
  get primaryInput(): IPortDescriptor | undefined {
    return this.inputs[0];
  }

  /* ---------------- runtime ---------------- */

  get runtime(): NodeRuntimeState {
    return this._runtime;
  }

  /* ---------------- the write seam ---------------- */

  /**
   * The only way to change a node, and only `WorkflowModel` may use it.
   *
   * These were seven public `apply*` methods under a comment saying
   * "WorkflowModel only", which was the entire enforcement
   * (reviews-2026-08-14 ticket 14). Seven public setters on a node are seven
   * ways for view or canvas code to move one without going through a command
   * — which does not fail, it silently drops out of undo and out of the
   * change events the canvas projection is built from.
   *
   * Grouping them names the seam so `nodeWriteSeam.test.ts` can hold the
   * layering rule (`gesture → Controller → ICommand → Model → event →
   * Adapter → canvas`) rather than a comment asking for it.
   *
   * Closures rather than a `NodeWriter` class: TypeScript's `private` is
   * per-class, so a separate class could not reach these fields without
   * widening them to the world — which is the thing being prevented.
   */
  readonly write: NodeWrite = {
    // `finitePoint` / `finiteSize`, not `{...position}`: these two take their
    // argument straight from a canvas drag, and a `NaN` reaching them would
    // leave through `toJSON()` as `"x": null` — the standing rule against a
    // non-finite number in a serialisable field, arriving by the very route
    // that rule's worked example describes (ticket 46, item 1). `EdgeModel`
    // has guarded its waypoints all along and calls itself "the one door they
    // can come through"; these were the other two.
    position: (position: Point) => {
      this._position = finitePoint(position, this._position);
    },
    size: (size: Size) => {
      this._size = finiteSize(size, this._size);
    },
    parent: (parentId: NodeId | null) => {
      this._parentId = parentId;
    },
    field: (key: string, value: FieldValue) => {
      this._data = { ...this._data, [key]: value };
    },
    title: (title: string) => {
      const trimmed = title.trim();
      // An empty title falls back to the type label rather than rendering a
      // blank header.
      this._title = trimmed.length > 0 ? trimmed : null;
    },
    runtime: (patch: Partial<NodeRuntimeState>) => {
      this._runtime = { ...this._runtime, ...patch };
    },
  };

  /* ---------------- serialization ---------------- */

  toJSON(): SerializedNode {
    return {
      id: this.id,
      type: this.type,
      position: { ...this._position },
      size: { ...this._size },
      parentId: this._parentId,
      // Sorted, not spread: `JSON.stringify` follows insertion order, so two
      // nodes holding identical values would serialise differently depending
      // on which field the user happened to edit first. `canonicalRows`
      // carries the same rule one level down, into a repeatable group's rows
      // — where `withSortedKeys` could not reach, so two MCP servers
      // describing the same thing did not compare equal (ticket 52).
      data: withSortedKeys(this.canonicalRows(this._data)),
      ...(this._title != null ? { title: this._title } : {}),
    };
  }

  /**
   * Every repeatable group's rows, keyed in the order their schema declares.
   *
   * Schema order rather than alphabetical: a row is read in a diff beside the
   * card that wrote it, and `id, url, transport` reads as a server while
   * `authKind, id, transport, url` reads as a hash. The node's own top-level
   * keys stay alphabetical — that is `withSortedKeys`, and it is a different
   * question about a flat record nobody composes by eye.
   */
  private canonicalRows(data: Readonly<NodeData>): NodeData {
    const out: NodeData = { ...data };
    for (const schema of this.definition.fields) {
      if (schema.kind !== 'repeatable-group') continue;
      const rows = out[schema.key];
      if (!Array.isArray(rows)) continue;
      out[schema.key] = rows.map((row) =>
        row && typeof row === 'object' && !Array.isArray(row)
          ? canonicalRow(row as Record<string, FieldValue>, schema.fields)
          : row,
      ) as FieldValue;
    }
    return out;
  }

  /**
   * Whether this node participates in a run. Annotations opt out, so the
   * scheduler needs no knowledge of what a "note" is.
   */
  get isExecutable(): boolean {
    return this.kind === 'standard';
  }
}
