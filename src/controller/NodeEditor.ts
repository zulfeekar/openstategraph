import { CANVAS } from '@design/tokens';
import { snapPoint, type Point, type Size } from '@core/kernel/geometry';
import {
  AddNodeCommand,
  MoveNodesCommand,
  RemoveNodesCommand,
  ResizeNodeCommand,
  SetFieldCommand,
  SetFieldsCommand,
  SetNodeTitleCommand,
} from '@core/commands/nodeCommands';
import type { FieldValue, NodeData } from '@core/model/contracts/fields';
import type { NodeId, NodeTypeId } from '@core/model/contracts/node';
import {
  failed,
  OK,
  type ActionOutcome,
  type EditingContext,
  type IGroupingController,
  type INodeEditor,
} from './contracts';
import type { SelectionModel } from './SelectionModel';

/**
 * Creating, deleting, moving and editing nodes.
 *
 * Depends on grouping rather than the reverse: adding a node has to re-evaluate
 * containment, because dropping a node inside a container should embed it
 * exactly as dragging it there would. The arrow points this way so there is no
 * cycle — grouping never needs to create a node except its own container, which
 * it does directly.
 */
export class NodeEditor implements INodeEditor {
  constructor(
    private readonly ctx: EditingContext,
    private readonly selection: SelectionModel,
    private readonly grouping: IGroupingController,
  ) {}

  /**
   * Creates a node of `typeId` at a canvas point.
   *
   * `at` is treated as the node's centre because both call sites — a palette
   * drop and a double-click — describe where the user pointed, not where a
   * corner should land.
   */
  add(
    typeId: NodeTypeId,
    at: Point,
    options: { data?: Partial<NodeData>; select?: boolean; centre?: boolean } = {},
  ): ActionOutcome {
    const definition = this.ctx.registry.nodeTypes.get(typeId);
    if (!definition) return failed(`Unknown node type "${typeId}"`);

    if (
      definition.maxInstances != null &&
      this.ctx.model.countOfType(typeId) >= definition.maxInstances
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
    this.ctx.commands.execute(command);

    const created = command.created;
    if (created && (options.select ?? true)) {
      this.selection.selectNodes([created.id]);
      this.grouping.reparentByGeometry([created.id]);
    }
    return OK;
  }

  delete(nodeIds: readonly NodeId[]): ActionOutcome {
    if (nodeIds.length === 0) return OK;
    this.ctx.commands.execute(new RemoveNodesCommand(nodeIds));
    return OK;
  }

  /** Deletes a container together with everything inside it. */
  deleteTree(nodeId: NodeId): ActionOutcome {
    const node = this.ctx.model.node(nodeId);
    if (!node) return OK;
    const ids = [nodeId, ...this.ctx.model.descendantsOf(nodeId).map((child) => child.id)];
    this.ctx.commands.execute(new RemoveNodesCommand(ids, 'Delete group and contents'));
    return OK;
  }

  move(moves: readonly { nodeId: NodeId; position: Point }[], snap = true): void {
    const entries = moves
      .map((move) => {
        const node = this.ctx.model.node(move.nodeId);
        if (!node) return null;
        return {
          nodeId: move.nodeId,
          from: { ...node.position },
          to: snap ? snapPoint(move.position, CANVAS.snapGrid) : move.position,
        };
      })
      .filter((entry) => entry != null);

    if (entries.length === 0) return;
    this.ctx.commands.execute(new MoveNodesCommand(entries));
  }

  resize(nodeId: NodeId, size: Size): void {
    this.ctx.commands.execute(new ResizeNodeCommand(nodeId, size));
  }

  /**
   * Applies a measured content height **without recording history**.
   *
   * Node cards are content-driven: the view measures the rendered HTML and
   * reports the height back. That is a consequence of a change the user already
   * made, so it must not become its own undo step — it goes straight to the
   * model, bypassing the command stack deliberately.
   */
  applyMeasuredSize(nodeId: NodeId, size: Size): void {
    this.ctx.model.resizeNode(nodeId, size);
  }

  setField(nodeId: NodeId, key: string, value: FieldValue): void {
    this.ctx.commands.execute(new SetFieldCommand(nodeId, key, value));
  }

  setFields(nodeId: NodeId, patch: Partial<NodeData>, label?: string): void {
    this.ctx.commands.execute(new SetFieldsCommand(nodeId, patch, label));
  }

  setTitle(nodeId: NodeId, title: string): void {
    this.ctx.commands.execute(new SetNodeTitleCommand(nodeId, title));
  }
}
