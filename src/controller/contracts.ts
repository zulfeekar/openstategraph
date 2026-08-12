import type { Unsubscribe } from '@core/kernel/Disposable';
import type { Point, Rect, Size } from '@core/kernel/geometry';
import type { CommandStack } from '@core/commands/CommandStack';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { FieldValue, NodeData } from '@core/model/contracts/fields';
import type { PortRef } from '@core/model/contracts/ports';
import type { NodeId, NodeTypeId } from '@core/model/contracts/node';
import type { EdgeId } from '@core/model/contracts/workflow';
import type { Diagnostic } from '@core/validation/WorkflowValidator';
import type { SelectionMode } from './SelectionModel';

/**
 * The editing collaborators' public contracts.
 *
 * Each is a narrow slice of what the editor can do, so a consumer depends on
 * the one it uses rather than on everything — the inspector needs field edits,
 * the topbar needs history, and neither should see the other. That is the whole
 * point of the split: before it, every one of them imported a 41-member class.
 *
 * There is deliberately **no `Abstract*`/`Base*` tier here.** Each contract has
 * exactly one implementation and no shared behaviour between them, so a ladder
 * would be depth for its own sake. CLAUDE.md's ladder applies to entity
 * *families* — node types, tools, providers — where subclasses genuinely share
 * behaviour. Controllers are not a family; they are collaborators.
 */

/** Reported back to the view so it can show a toast. */
export interface ActionOutcome {
  readonly ok: boolean;
  readonly message?: string;
}

export const OK: ActionOutcome = { ok: true };
export const failed = (message: string): ActionOutcome => ({ ok: false, message });

/**
 * What every collaborator needs to do its job.
 *
 * Passed as one object rather than as positional arguments so adding a
 * dependency later does not touch seven constructors.
 */
export interface EditingContext {
  readonly model: WorkflowModel;
  readonly registry: ModelRegistry;
  readonly commands: CommandStack;
}

/** Creating, deleting, moving and editing nodes. */
export interface INodeEditor {
  add(
    typeId: NodeTypeId,
    at: Point,
    options?: { data?: Partial<NodeData>; select?: boolean; centre?: boolean },
  ): ActionOutcome;
  delete(nodeIds: readonly NodeId[]): ActionOutcome;
  deleteTree(nodeId: NodeId): ActionOutcome;
  move(moves: readonly { nodeId: NodeId; position: Point }[], snap?: boolean): void;
  resize(nodeId: NodeId, size: Size): void;
  applyMeasuredSize(nodeId: NodeId, size: Size): void;
  setField(nodeId: NodeId, key: string, value: FieldValue): void;
  setFields(nodeId: NodeId, patch: Partial<NodeData>, label?: string): void;
  setTitle(nodeId: NodeId, title: string): void;
}

/** Connecting and disconnecting ports. */
export interface IEdgeEditor {
  canConnect(source: PortRef, target: PortRef): boolean;
  connect(source: PortRef, target: PortRef): ActionOutcome;
  disconnect(edgeIds: readonly EdgeId[]): ActionOutcome;
  setLabel(edgeId: EdgeId, label: string | null): void;
  /** Replaces the waypoints a link's run passes through. */
  setVertices(edgeId: EdgeId, vertices: readonly Point[]): void;
  /** Ticket 25's splice-insert — see `EdgeEditor.insertOnEdge`. */
  insertOnEdge(edgeId: EdgeId, typeId: NodeTypeId, at: Point): ActionOutcome;
}

/** Containment — which nodes sit inside which container. */
export interface IGroupingController {
  setParent(nodeId: NodeId, parentId: NodeId | null): void;
  reparentByGeometry(nodeIds: readonly NodeId[]): void;
  group(containerTypeId: NodeTypeId): ActionOutcome;
  ungroup(containerId: NodeId): ActionOutcome;
}

/** Copy, cut, paste, duplicate. */
export interface IClipboardController {
  copy(): ActionOutcome;
  cut(): ActionOutcome;
  paste(at: Point): ActionOutcome;
  duplicate(nodeIds: readonly NodeId[]): ActionOutcome;
}

/** Undo, redo, and grouping several edits into one step. */
export interface IHistoryController {
  undo(): void;
  redo(): void;
  readonly canUndo: boolean;
  readonly canRedo: boolean;
  transact(label: string, fn: () => void): void;
  /**
   * Fires when availability changes, for toolbar enablement.
   *
   * Narrower than `WorkflowController.onChange`, which fires for *any* model or
   * selection change — a toolbar that re-rendered on every keystroke would be
   * doing so to learn something that only changes on an undo boundary.
   */
  onChange(handler: (state: { canUndo: boolean; canRedo: boolean }) => void): Unsubscribe;
}

/** Whole-document operations: validate, import, export, clear, rename. */
export interface IDocumentController {
  diagnostics(): readonly Diagnostic[];
  exportJSON(): string;
  importJSON(text: string): ActionOutcome;
  clear(): void;
  setName(name: string): void;
}

/**
 * Gestures whose subject is *whatever is currently selected*.
 *
 * Separate from `SelectionModel`, which holds the selection state. The split is
 * along the one-reason-to-change line: the model changes when selection
 * semantics change (additive? toggle?), this changes when the gestures do.
 */
export interface ISelectionActions {
  selectNodes(ids: readonly NodeId[], mode?: SelectionMode): void;
  selectAll(): void;
  bounds(): Rect | null;
  deleteSelection(): ActionOutcome;
  nudge(dx: number, dy: number): void;
}
