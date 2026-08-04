import { nextId } from '@core/kernel/id';
import { withSortedKeys } from '@core/kernel/ordering';
import type { Point, Size } from '@core/kernel/geometry';
import { defaultsFrom, mergeData, type FieldValue, type NodeData } from './contracts/fields';
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
    this._position = { ...init.position };
    this._size = { ...(init.size ?? definition.defaultSize) };
    this._parentId = init.parentId ?? null;
    // Schema defaults first so a node loaded from an older document gains
    // any field added since it was saved.
    this._data = mergeData(defaultsFrom(definition.fields), init.data);
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

  getFlag(key: string, fallback = false): boolean {
    const value = this._data[key];
    return typeof value === 'boolean' ? value : fallback;
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

  /* ---------------- runtime ---------------- */

  get runtime(): NodeRuntimeState {
    return this._runtime;
  }

  /* ---------------- mutators — WorkflowModel only ---------------- */

  applyPosition(position: Point): void {
    this._position = { ...position };
  }

  applySize(size: Size): void {
    this._size = { ...size };
  }

  applyParent(parentId: NodeId | null): void {
    this._parentId = parentId;
  }

  applyField(key: string, value: FieldValue): void {
    this._data = { ...this._data, [key]: value };
  }

  applyData(patch: Partial<NodeData>): void {
    this._data = mergeData(this._data, patch);
  }

  applyTitle(title: string): void {
    const trimmed = title.trim();
    // An empty title falls back to the type label rather than rendering a
    // blank header.
    this._title = trimmed.length > 0 ? trimmed : null;
  }

  applyRuntime(patch: Partial<NodeRuntimeState>): void {
    this._runtime = { ...this._runtime, ...patch };
  }

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
      // on which field the user happened to edit first.
      data: withSortedKeys(this._data),
      ...(this._title != null ? { title: this._title } : {}),
    };
  }

  /**
   * Whether this node participates in a run. Annotations opt out, so the
   * scheduler needs no knowledge of what a "note" is.
   */
  get isExecutable(): boolean {
    return this.kind === 'standard';
  }
}
