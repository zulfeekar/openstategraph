import { GROUP } from '@design/tokens';
import { unionRects } from '@core/kernel/geometry';
import { fitAround } from '@core/model/containerFit';
import { CompositeCommand, type ICommand } from '@core/commands/ICommand';
import { AddNodeCommand, SetParentCommand } from '@core/commands/nodeCommands';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeId, NodeTypeId } from '@core/model/contracts/node';
import {
  failed,
  OK,
  type ActionOutcome,
  type EditingContext,
  type IGroupingController,
} from './contracts';
import { area, contains, rectOf } from './placement';
import type { SelectionModel } from './SelectionModel';

/**
 * Containment — which nodes sit inside which container.
 *
 * One reason to change: how nesting is decided. That is why the geometric rule
 * and the explicit commands live together — `reparentByGeometry` is the
 * *implicit* form of `setParent`, and keeping them apart would let a drop and a
 * menu action disagree about what "inside" means.
 */
export class GroupingController implements IGroupingController {
  constructor(
    private readonly ctx: EditingContext,
    private readonly selection: SelectionModel,
  ) {}

  setParent(nodeId: NodeId, parentId: NodeId | null): void {
    this.ctx.commands.execute(new SetParentCommand(nodeId, parentId));
  }

  /**
   * Re-evaluates embedding from geometry, after a drop.
   *
   * Containment follows the node's *centre*, and the **smallest** containing
   * container wins so nested groups behave the way they look — dropping into an
   * inner group does not attach to the outer one just because it also overlaps.
   */
  reparentByGeometry(nodeIds: readonly NodeId[]): void {
    const containers = this.ctx.model
      .nodes()
      .filter((node) => node.kind === 'container') as AbstractNodeModel[];
    if (containers.length === 0) return;

    const changes: ICommand[] = [];
    for (const nodeId of nodeIds) {
      const node = this.ctx.model.node(nodeId);
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
      this.ctx.commands.execute(CompositeCommand.of('Regroup', changes));
    }
  }

  /** Wraps the selection in a new container sized to fit it. */
  group(containerTypeId: NodeTypeId): ActionOutcome {
    const nodeIds = this.selection.nodes.filter(
      (id) => this.ctx.model.node(id)?.kind !== 'container',
    );
    if (nodeIds.length === 0) return failed('Select nodes to group');

    const definition = this.ctx.registry.nodeTypes.get(containerTypeId);
    if (!definition || definition.kind !== 'container') {
      return failed('That node type is not a container');
    }

    const box = unionRects(
      nodeIds
        .map((id) => this.ctx.model.node(id))
        .filter((node) => node != null)
        .map((node) => rectOf(node)),
    );
    if (!box) return failed('Select nodes to group');

    // One definition of "a frame wrapping these children", shared with the
    // re-fit `AutoLayout` performs after it moves them. A second copy here
    // would drift from that one the first time the padding changed.
    const fitted = fitAround(box, GROUP.padding, {
      width: GROUP.minWidth,
      height: GROUP.minHeight,
    });
    const add = new AddNodeCommand(definition, {
      position: { x: fitted.x, y: fitted.y },
      size: { width: fitted.width, height: fitted.height },
    });

    // One step: creating the container and embedding the nodes is a single
    // user action, so one undo must reverse all of it.
    this.ctx.commands.transact('Group nodes', () => {
      this.ctx.commands.execute(add);
      const container = add.created;
      if (!container) return;
      for (const nodeId of nodeIds) {
        this.ctx.commands.execute(new SetParentCommand(nodeId, container.id));
      }
    });

    if (add.created) this.selection.selectNodes([add.created.id]);
    return OK;
  }

  /** Releases every child of a container without deleting the container. */
  ungroup(containerId: NodeId): ActionOutcome {
    const children = this.ctx.model.childrenOf(containerId);
    if (children.length === 0) return OK;
    this.ctx.commands.transact('Ungroup', () => {
      for (const child of children) {
        this.ctx.commands.execute(new SetParentCommand(child.id, null));
      }
    });
    return OK;
  }
}
