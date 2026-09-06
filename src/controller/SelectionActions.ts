import { unionRects, type Rect } from '@core/kernel/geometry';
import { DisconnectCommand } from '@core/commands/edgeCommands';
import { RemoveNodesCommand } from '@core/commands/nodeCommands';
import type { NodeId } from '@core/model/contracts/node';
import {
  OK,
  type ActionOutcome,
  type EditingContext,
  type INodeEditor,
  type ISelectionActions,
} from './contracts';
import { rectOf } from './placement';
import type { SelectionModel, SelectionMode } from './SelectionModel';

/**
 * Gestures whose subject is whatever is currently selected.
 *
 * Split from `SelectionModel` along the one-reason-to-change line: the model
 * changes when selection *semantics* change (additive, toggle, range), this
 * changes when the *gestures* do. Keeping them together would mean a state
 * container that also knows about commands and geometry.
 */
export class SelectionActions implements ISelectionActions {
  constructor(
    private readonly ctx: EditingContext,
    private readonly selection: SelectionModel,
    private readonly nodes: INodeEditor,
  ) {}

  selectNodes(ids: readonly NodeId[], mode: SelectionMode = 'replace'): void {
    this.selection.selectNodes(ids, mode);
  }

  selectAll(): void {
    this.selection.set(
      this.ctx.model.nodes().map((node) => node.id),
      [],
    );
  }

  /** Bounding box of the selection, or of the whole graph when empty. */
  bounds(): Rect | null {
    const ids = this.selection.nodes;
    if (ids.length === 0) return this.ctx.model.bounds();
    return unionRects(
      ids
        .map((id) => this.ctx.model.node(id))
        .filter((node) => node != null)
        .map((node) => rectOf(node)),
    );
  }

  deleteSelection(): ActionOutcome {
    const { nodes, edges } = this.selection;
    if (nodes.length === 0 && edges.length === 0) return OK;

    this.ctx.commands.transact('Delete selection', () => {
      // Edges first: removing a node cascades to its edges anyway, and this
      // order avoids capturing the same edge twice.
      if (edges.length > 0) this.ctx.commands.execute(new DisconnectCommand(edges));
      if (nodes.length > 0) this.ctx.commands.execute(new RemoveNodesCommand(nodes));
    });
    this.selection.clear();
    return OK;
  }

  /** Nudges the selection by a delta — the arrow-key gesture. */
  nudge(dx: number, dy: number): void {
    const moves = this.selection.nodes
      .map((nodeId) => {
        const node = this.ctx.model.node(nodeId);
        return node
          ? { nodeId, position: { x: node.position.x + dx, y: node.position.y + dy } }
          : null;
      })
      .filter((move) => move != null);
    // Unsnapped: a nudge is a deliberate one-step offset, and snapping would
    // swallow it whenever the node already sat on the grid.
    this.nodes.move(moves, false);
  }
}
