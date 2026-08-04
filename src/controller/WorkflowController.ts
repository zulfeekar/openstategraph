import { DisposableStore, type Unsubscribe } from '@core/kernel/Disposable';
import { CANVAS, GROUP } from '@design/tokens';
import { snapPoint, unionRects, type Point, type Rect, type Size } from '@core/kernel/geometry';
import { CommandStack } from '@core/commands/CommandStack';
import { CompositeCommand, type CommandContext, type ICommand } from '@core/commands/ICommand';
import {
  AddNodeCommand,
  MoveNodesCommand,
  RemoveNodesCommand,
  ResizeNodeCommand,
  SetFieldCommand,
  SetFieldsCommand,
  SetNodeTitleCommand,
  SetParentCommand,
} from '@core/commands/nodeCommands';
import {
  ConnectCommand,
  DisconnectCommand,
  RenameWorkflowCommand,
  SetEdgeLabelCommand,
} from '@core/commands/edgeCommands';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { FieldValue, NodeData } from '@core/model/contracts/fields';
import type { PortRef } from '@core/model/contracts/ports';
import type { NodeId, NodeTypeId } from '@core/model/contracts/node';
import type { EdgeId } from '@core/model/contracts/workflow';
import type { ConnectionValidator } from '@core/validation/ConnectionValidator';
import type { Diagnostic, WorkflowValidator } from '@core/validation/WorkflowValidator';
import type { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';
import { ClipboardService } from './ClipboardService';
import { SelectionModel, type SelectionMode } from './SelectionModel';

export interface WorkflowControllerDeps {
  readonly model: WorkflowModel;
  readonly registry: ModelRegistry;
  readonly connectionValidator: ConnectionValidator;
  readonly workflowValidator: WorkflowValidator;
  readonly serializer: WorkflowSerializer;
}

/** Reported back to the view so it can show a toast. */
export interface ActionOutcome {
  readonly ok: boolean;
  readonly message?: string;
}

const OK: ActionOutcome = { ok: true };
const failed = (message: string): ActionOutcome => ({ ok: false, message });

/**
 * The editor's public API.
 *
 * Everything the UI can do to a workflow is a method here, and every one of
 * them goes through the command stack. That single rule is what makes the
 * whole app undoable, keeps the React tree free of graph logic, and means a
 * keyboard shortcut, a context menu and a future scripting API all drive
 * the same code path instead of three parallel implementations.
 *
 * The controller owns *intent*: "the user dropped a node here", "the user
 * wants these two ports connected". It resolves that into validated,
 * composed commands. It does not own rendering, and it does not know that
 * JointJS or React exist.
 */
export class WorkflowController {
  readonly model: WorkflowModel;
  readonly registry: ModelRegistry;
  readonly selection = new SelectionModel();
  readonly commands: CommandStack;
  readonly clipboard: ClipboardService;
  readonly connectionValidator: ConnectionValidator;
  readonly workflowValidator: WorkflowValidator;
  readonly serializer: WorkflowSerializer;

  private readonly disposables = new DisposableStore();
  private readonly ctx: CommandContext;

  constructor(deps: WorkflowControllerDeps) {
    this.model = deps.model;
    this.registry = deps.registry;
    this.connectionValidator = deps.connectionValidator;
    this.workflowValidator = deps.workflowValidator;
    this.serializer = deps.serializer;

    this.ctx = { model: this.model, registry: this.registry };
    this.commands = new CommandStack(this.ctx);
    this.clipboard = new ClipboardService(this.model, this.registry);

    // Selection can outlive the things it points at — a delete, an undo of
    // an add, or an import all invalidate ids. Pruning centrally means no
    // caller has to remember to do it.
    this.disposables.addFn(
      this.model.on('node:removed', () => this.pruneSelection()),
    );
    this.disposables.addFn(this.model.on('edge:removed', () => this.pruneSelection()));
    this.disposables.addFn(this.model.on('workflow:reset', () => this.selection.clear()));
  }

  /* ================================================================ *
   * Nodes
   * ================================================================ */

  /**
   * Creates a node of `typeId` at a canvas point.
   *
   * `at` is treated as the node's centre because both call sites — a
   * palette drop and a double-click — describe where the user pointed, not
   * where a corner should land.
   */
  addNode(
    typeId: NodeTypeId,
    at: Point,
    options: { data?: Partial<NodeData>; select?: boolean; centre?: boolean } = {},
  ): ActionOutcome {
    const definition = this.registry.nodeTypes.get(typeId);
    if (!definition) return failed(`Unknown node type "${typeId}"`);

    if (
      definition.maxInstances != null &&
      this.model.countOfType(typeId) >= definition.maxInstances
    ) {
      return failed(
        definition.maxInstances === 1
          ? `Only one ${definition.label} is allowed`
          : `At most ${definition.maxInstances} ${definition.label} nodes are allowed`,
      );
    }

    const centre = options.centre ?? true;
    const topLeft = centre
      ? {
          x: at.x - definition.defaultSize.width / 2,
          y: at.y - definition.defaultSize.height / 2,
        }
      : at;

    const command = new AddNodeCommand(definition, {
      position: snapPoint(topLeft, CANVAS.snapGrid),
      ...(options.data ? { data: options.data } : {}),
    });
    this.commands.execute(command);

    const created = command.created;
    if (created && (options.select ?? true)) {
      this.selection.selectNodes([created.id]);
      // Dropping a node inside a container should embed it, exactly as
      // dragging it there would.
      this.reparentByGeometry([created.id]);
    }
    return OK;
  }

  deleteNodes(nodeIds: readonly NodeId[]): ActionOutcome {
    if (nodeIds.length === 0) return OK;
    this.commands.execute(new RemoveNodesCommand(nodeIds));
    return OK;
  }

  /** Deletes a container together with everything inside it. */
  deleteNodeTree(nodeId: NodeId): ActionOutcome {
    const node = this.model.node(nodeId);
    if (!node) return OK;
    const ids = [nodeId, ...this.model.descendantsOf(nodeId).map((child) => child.id)];
    this.commands.execute(new RemoveNodesCommand(ids, 'Delete group and contents'));
    return OK;
  }

  deleteSelection(): ActionOutcome {
    const { nodes, edges } = this.selection;
    if (nodes.length === 0 && edges.length === 0) return OK;

    this.commands.transact('Delete selection', () => {
      // Edges first: deleting a node removes its edges anyway, and doing
      // it in this order avoids capturing the same edge twice.
      if (edges.length > 0) this.commands.execute(new DisconnectCommand(edges));
      if (nodes.length > 0) this.commands.execute(new RemoveNodesCommand(nodes));
    });
    this.selection.clear();
    return OK;
  }

  moveNodes(moves: readonly { nodeId: NodeId; position: Point }[], snap = true): void {
    const entries = moves
      .map((move) => {
        const node = this.model.node(move.nodeId);
        if (!node) return null;
        return {
          nodeId: move.nodeId,
          from: { ...node.position },
          to: snap ? snapPoint(move.position, CANVAS.snapGrid) : move.position,
        };
      })
      .filter((entry) => entry != null);

    if (entries.length === 0) return;
    this.commands.execute(new MoveNodesCommand(entries));
  }

  /** Nudges the selection by a delta — the arrow-key gesture. */
  nudgeSelection(dx: number, dy: number): void {
    const moves = this.selection.nodes
      .map((nodeId) => {
        const node = this.model.node(nodeId);
        return node ? { nodeId, position: { x: node.position.x + dx, y: node.position.y + dy } } : null;
      })
      .filter((move) => move != null);
    this.moveNodes(moves, false);
  }

  resizeNode(nodeId: NodeId, size: Size): void {
    this.commands.execute(new ResizeNodeCommand(nodeId, size));
  }

  /**
   * Applies a measured content height without recording history.
   *
   * Node cards are content-driven: the view measures the rendered HTML and
   * reports the height back. That is a consequence of a change the user
   * already made, so it must not become its own undo step — the resize is
   * applied straight to the model.
   */
  applyMeasuredSize(nodeId: NodeId, size: Size): void {
    this.model.resizeNode(nodeId, size);
  }

  setField(nodeId: NodeId, key: string, value: FieldValue): void {
    this.commands.execute(new SetFieldCommand(nodeId, key, value));
  }

  setFields(nodeId: NodeId, patch: Partial<NodeData>, label?: string): void {
    this.commands.execute(new SetFieldsCommand(nodeId, patch, label));
  }

  setNodeTitle(nodeId: NodeId, title: string): void {
    this.commands.execute(new SetNodeTitleCommand(nodeId, title));
  }

  setWorkflowName(name: string): void {
    this.commands.execute(new RenameWorkflowCommand(name));
  }

  duplicateNodes(nodeIds: readonly NodeId[]): ActionOutcome {
    if (nodeIds.length === 0) return OK;
    const fragment = this.clipboard.copy(nodeIds);
    if (!fragment) return failed('Nothing to duplicate');
    // Offset by a grid step so the copy is visibly on top of, not hiding,
    // the original.
    const offset = CANVAS.gridSize * 3;
    const { command, nodeIds: created } = this.clipboard.pasteCommand(
      { x: fragment.origin.x + offset, y: fragment.origin.y + offset },
      fragment,
    );
    if (!command) return failed('Nothing to duplicate');
    this.commands.execute(command);
    if (created.length > 0) this.selection.selectNodes(created);
    return OK;
  }

  /* ================================================================ *
   * Clipboard
   * ================================================================ */

  copySelection(): ActionOutcome {
    const fragment = this.clipboard.copy(this.selection.nodes);
    return fragment ? OK : failed('Select a node first');
  }

  cutSelection(): ActionOutcome {
    const copied = this.copySelection();
    if (!copied.ok) return copied;
    return this.deleteSelection();
  }

  paste(at: Point): ActionOutcome {
    const { command, nodeIds } = this.clipboard.pasteCommand(at);
    if (!command) return failed('Clipboard is empty');
    this.commands.execute(command);
    if (nodeIds.length > 0) {
      this.selection.selectNodes(nodeIds);
      this.reparentByGeometry(nodeIds);
    }
    return OK;
  }

  /* ================================================================ *
   * Edges
   * ================================================================ */

  /** Asked by the canvas on every pointer move while drawing a link. */
  canConnect(source: PortRef, target: PortRef): boolean {
    return this.connectionValidator.canConnect(source, target);
  }

  /**
   * Connects two ports if the rules allow it.
   *
   * Displaced links (re-wiring a single-slot input) are removed in the same
   * transaction, so one undo restores the previous wiring exactly.
   */
  connect(source: PortRef, target: PortRef): ActionOutcome {
    const verdict = this.connectionValidator.validate(source, target);
    if (!verdict.ok) return failed(verdict.reason);

    const connect = new ConnectCommand(source, target);
    if (verdict.replaces.length > 0) {
      const command = CompositeCommand.of('Reconnect', [
        new DisconnectCommand(verdict.replaces),
        connect,
      ]);
      this.commands.execute(command);
    } else {
      this.commands.execute(connect);
    }
    return OK;
  }

  disconnect(edgeIds: readonly EdgeId[]): ActionOutcome {
    if (edgeIds.length === 0) return OK;
    this.commands.execute(new DisconnectCommand(edgeIds));
    return OK;
  }

  setEdgeLabel(edgeId: EdgeId, label: string | null): void {
    this.commands.execute(new SetEdgeLabelCommand(edgeId, label));
  }

  /* ================================================================ *
   * Grouping
   * ================================================================ */

  setParent(nodeId: NodeId, parentId: NodeId | null): void {
    this.commands.execute(new SetParentCommand(nodeId, parentId));
  }

  /**
   * Re-evaluates embedding from geometry.
   *
   * Called after a drop. Containment is decided by which container's box
   * the node's centre lands in, and the *smallest* such container wins so
   * nesting behaves intuitively.
   */
  reparentByGeometry(nodeIds: readonly NodeId[]): void {
    const containers = this.model
      .nodes()
      .filter((node) => node.kind === 'container') as AbstractNodeModel[];
    if (containers.length === 0) return;

    const changes: ICommand[] = [];
    for (const nodeId of nodeIds) {
      const node = this.model.node(nodeId);
      if (!node || node.kind === 'container') continue;

      const centre = {
        x: node.position.x + node.size.width / 2,
        y: node.position.y + node.size.height / 2,
      };

      const match = containers
        .filter((container) => container.id !== nodeId)
        .filter((container) => contains(rectOf(container), centre))
        .sort((a, b) => area(rectOf(a)) - area(rectOf(b)))[0];

      const parentId = match?.id ?? null;
      if (parentId !== node.parentId) changes.push(new SetParentCommand(nodeId, parentId));
    }

    if (changes.length > 0) {
      this.commands.execute(CompositeCommand.of('Regroup', changes));
    }
  }

  /** Wraps the selection in a new container sized to fit it. */
  groupSelection(containerTypeId: NodeTypeId): ActionOutcome {
    const nodeIds = this.selection.nodes.filter((id) => this.model.node(id)?.kind !== 'container');
    if (nodeIds.length === 0) return failed('Select nodes to group');

    const definition = this.registry.nodeTypes.get(containerTypeId);
    if (!definition || definition.kind !== 'container') {
      return failed('That node type is not a container');
    }

    const box = unionRects(
      nodeIds
        .map((id) => this.model.node(id))
        .filter((node) => node != null)
        .map((node) => rectOf(node)),
    );
    if (!box) return failed('Select nodes to group');

    const { padding } = GROUP;
    const add = new AddNodeCommand(definition, {
      position: { x: box.x - padding.left, y: box.y - padding.top },
      size: {
        width: Math.max(GROUP.minWidth, box.width + padding.left + padding.right),
        height: Math.max(GROUP.minHeight, box.height + padding.top + padding.bottom),
      },
    });

    this.commands.transact('Group nodes', () => {
      this.commands.execute(add);
      const container = add.created;
      if (!container) return;
      for (const nodeId of nodeIds) {
        this.commands.execute(new SetParentCommand(nodeId, container.id));
      }
    });

    if (add.created) this.selection.selectNodes([add.created.id]);
    return OK;
  }

  /** Releases every child of a container without deleting the container. */
  ungroup(containerId: NodeId): ActionOutcome {
    const children = this.model.childrenOf(containerId);
    if (children.length === 0) return OK;
    this.commands.transact('Ungroup', () => {
      for (const child of children) {
        this.commands.execute(new SetParentCommand(child.id, null));
      }
    });
    return OK;
  }

  /* ================================================================ *
   * Selection helpers
   * ================================================================ */

  selectNodes(ids: readonly NodeId[], mode: SelectionMode = 'replace'): void {
    this.selection.selectNodes(ids, mode);
  }

  selectAll(): void {
    this.selection.set(
      this.model.nodes().map((node) => node.id),
      [],
    );
  }

  /** Bounding box of the selection, or of the whole graph when empty. */
  selectionBounds(): Rect | null {
    const ids = this.selection.nodes;
    if (ids.length === 0) return this.model.bounds();
    return unionRects(
      ids
        .map((id) => this.model.node(id))
        .filter((node) => node != null)
        .map((node) => rectOf(node)),
    );
  }

  /* ================================================================ *
   * History
   * ================================================================ */

  undo(): void {
    this.commands.undo();
  }

  redo(): void {
    this.commands.redo();
  }

  get canUndo(): boolean {
    return this.commands.canUndo;
  }

  get canRedo(): boolean {
    return this.commands.canRedo;
  }

  /* ================================================================ *
   * Document
   * ================================================================ */

  diagnostics(): readonly Diagnostic[] {
    return this.workflowValidator.validate();
  }

  exportJSON(): string {
    return this.serializer.toJSONString(this.model);
  }

  importJSON(text: string): ActionOutcome {
    const result = this.serializer.loadFromText(this.model, text);
    if (!result.ok) return failed(result.error);
    this.commands.clear();
    const { warnings } = result.value;
    return warnings.length > 0 ? { ok: true, message: warnings.join('; ') } : OK;
  }

  clearWorkflow(): void {
    this.model.clear();
    this.commands.clear();
    this.selection.clear();
  }

  /* ================================================================ *
   * Observation
   * ================================================================ */

  /**
   * Fires on any change that could affect derived UI state — the toolbar's
   * enablement, the inspector's contents, the diagnostics count.
   */
  onChange(handler: () => void): Unsubscribe {
    const store = new DisposableStore();
    store.addFn(this.model.onAny(() => handler()));
    store.addFn(this.selection.on(() => handler()));
    store.addFn(this.commands.on('changed', () => handler()));
    return () => store.dispose();
  }

  dispose(): void {
    this.disposables.dispose();
    this.commands.dispose();
    this.selection.dispose();
  }

  private pruneSelection(): void {
    this.selection.prune(
      (id) => this.model.hasNode(id),
      (id) => this.model.edge(id) != null,
    );
  }
}

/* ---------------- local geometry helpers ---------------- */

const rectOf = (node: { position: Point; size: Size }): Rect => ({
  x: node.position.x,
  y: node.position.y,
  width: node.size.width,
  height: node.size.height,
});

const contains = (rect: Rect, p: Point): boolean =>
  p.x >= rect.x && p.x <= rect.x + rect.width && p.y >= rect.y && p.y <= rect.y + rect.height;

const area = (rect: Rect): number => rect.width * rect.height;
