import { ClearMountOverrideCommand, SetMountOverrideCommand } from '@core/commands/mountCommands';
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
import { freePositionNear } from '@core/model/placement';
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
    options: {
      data?: Partial<NodeData>;
      select?: boolean;
      centre?: boolean;
      /**
       * Step aside when the requested spot is already taken.
       *
       * For placements the user did not *aim*: a palette click names no
       * point, so without this three clicks stacked three nodes on one
       * coordinate — one visible card, two buried, and nothing to say so.
       *
       * Off by default, because a **drop** carries the point the pointer was
       * released on and putting the node anywhere else would be wrong.
       *
       * Here rather than at the call site: this method owns the convention
       * that its argument is the node's *centre* and the stored position is
       * `centre - size / 2`. A caller that cascaded would have to reproduce
       * that conversion to know what "taken" means — and the first attempt at
       * this did exactly that, compared centres against top-left corners, and
       * silently never collided.
       */
      avoidOverlap?: boolean;
    } = {},
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
    // Compared as centres, which is the space `at` is already in.
    const requested = options.avoidOverlap
      ? freePositionNear(
          at,
          this.ctx.model.nodes().map((node) => ({
            x: node.position.x + node.size.width / 2,
            y: node.position.y + node.size.height / 2,
          })),
        )
      : at;
    const topLeft = centre
      ? {
          x: requested.x - definition.defaultSize.width / 2,
          y: requested.y - definition.defaultSize.height / 2,
        }
      : requested;

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
   *
   * **And without reaching the document.** `'measured'` moves the card on the
   * canvas and leaves `SerializedNode.size` alone, because the height is a
   * property of this build's card styling rather than of the workflow — a
   * shorter card body silently rewrote five heights in a saved package
   * (`production-ready` 69).
   */
  applyMeasuredSize(nodeId: NodeId, size: Size): void {
    this.ctx.model.resizeNode(nodeId, size, 'measured');
  }

  /**
   * The single funnel every field edit already goes through — an inspector
   * control, a card body, a shortcut, a future scripting call — which is why
   * the instance branch is here and in exactly one place (ticket 42).
   *
   * While a mount is displayed the edit is not a change to the document on
   * screen: that document is derived, and saving it back would burn the value
   * into the shared package. It is a change to *this mount's* overrides, in
   * the parent — so a different command runs, writing both the parent and the
   * model, and undo stays generic because both are one command.
   */
  setField(nodeId: NodeId, key: string, value: FieldValue): void {
    const mounts = this.ctx.commands.context.mounts;
    this.ctx.commands.execute(
      mounts
        ? new SetMountOverrideCommand(nodeId, key, value)
        : new SetFieldCommand(nodeId, key, value),
    );
  }

  /**
   * Drop this instance's override of one field, so the package's own value
   * applies again. A no-op outside a mount, where there is no override to
   * drop — the inspector only offers it when there is one.
   */
  clearOverride(nodeId: NodeId, key: string): void {
    if (!this.ctx.commands.context.mounts) return;
    this.ctx.commands.execute(new ClearMountOverrideCommand(nodeId, key));
  }

  setFields(nodeId: NodeId, patch: Partial<NodeData>, label?: string): void {
    this.ctx.commands.execute(new SetFieldsCommand(nodeId, patch, label));
  }

  setTitle(nodeId: NodeId, title: string): void {
    this.ctx.commands.execute(new SetNodeTitleCommand(nodeId, title));
  }
}
