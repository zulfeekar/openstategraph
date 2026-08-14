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
import type { MountContext } from '@core/model/MountContext';
import type { SelectionMode } from './SelectionModel';
import type { ClipboardFragment } from './ClipboardService';

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
    options?: {
      data?: Partial<NodeData>;
      select?: boolean;
      centre?: boolean;
      /** Step aside when the spot is taken — for placements the user did not
       *  aim at (a palette click). A drop carries its own point and must not
       *  use this. See `NodeEditor.add`. */
      avoidOverlap?: boolean;
    },
  ): ActionOutcome;
  delete(nodeIds: readonly NodeId[]): ActionOutcome;
  deleteTree(nodeId: NodeId): ActionOutcome;
  move(moves: readonly { nodeId: NodeId; position: Point }[], snap?: boolean): void;
  resize(nodeId: NodeId, size: Size): void;
  applyMeasuredSize(nodeId: NodeId, size: Size): void;
  setField(nodeId: NodeId, key: string, value: FieldValue): void;
  /** Drop this instance's override of one field (ticket 42). */
  clearOverride(nodeId: NodeId, key: string): void;
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

/** Copy, cut, paste, duplicate, and insert a canned fragment. */
export interface IClipboardController {
  copy(): ActionOutcome;
  cut(): ActionOutcome;
  paste(at: Point): ActionOutcome;
  duplicate(nodeIds: readonly NodeId[]): ActionOutcome;
  /**
   * Drop a fragment nobody copied — a palette assembly (ticket 21).
   *
   * Lives here rather than on node editing because inserting an assembly *is*
   * a paste: the same id remapping, edge rewiring, instance caps, selection
   * and single undoable command, differing only in where the fragment came
   * from. `ClipboardService.pasteCommand` already took an explicit fragment,
   * so the seam existed before there was a second caller for it.
   *
   * Leaves the real clipboard untouched — dropping a loop must not overwrite
   * whatever the developer had copied.
   */
  insertFragment(fragment: ClipboardFragment, at: Point): ActionOutcome;
}

/** Undo, redo, and grouping several edits into one step. */
export interface IHistoryController {
  undo(): void;
  redo(): void;
  readonly canUndo: boolean;
  readonly canRedo: boolean;
  transact(label: string, fn: () => void): void;
  /**
   * A change the current edit scope would not allow — see
   * `core/commands/editScope`. Nothing ran and nothing was pushed; the
   * subscriber's job is to say so.
   */
  onRefused(handler: (state: { label: string; reason: string }) => void): Unsubscribe;
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
  /**
   * The document now on screen is the **instance** mounted at `mountId`, not a
   * package — ticket 42. Structural changes are refused while it is, because a
   * mount's own state (`data.overrides`) can carry a field's value and not the
   * workflow's shape; see `core/commands/editScope`.
   *
   * It lives here rather than as an eleventh member on `WorkflowController`
   * because "which document is this, and where did it come from" is already
   * this collaborator's question — `importJSON` is next to it.
   */
  enterInstance(mountId: string, mounts?: MountContext): void;
  /** Back to a package, where every change is expressible. */
  leaveInstance(): void;
  /**
   * The parent document an instance's edits have been written to, or
   * `undefined` outside one. Read by Save, which persists *that* document
   * rather than the derived one on screen.
   */
  mountContext(): MountContext | undefined;
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
