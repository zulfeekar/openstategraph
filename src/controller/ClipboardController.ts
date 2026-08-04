import { CANVAS } from '@design/tokens';
import type { Point } from '@core/kernel/geometry';
import type { NodeId } from '@core/model/contracts/node';
import {
  failed,
  OK,
  type ActionOutcome,
  type EditingContext,
  type IClipboardController,
  type IGroupingController,
  type ISelectionActions,
} from './contracts';
import type { ClipboardService } from './ClipboardService';
import type { SelectionModel } from './SelectionModel';

/**
 * Copy, cut, paste and duplicate.
 *
 * `ClipboardService` holds the fragment and builds the paste command; this owns
 * the *gestures* around it — what gets copied, what happens to the selection
 * afterwards, and the fact that a pasted node re-evaluates its containment just
 * as a dropped one does.
 *
 * Duplicate lives here rather than with node editing because it is a copy and a
 * paste with an offset, not a new node — sharing the implementation is what
 * keeps the two from drifting.
 */
export class ClipboardController implements IClipboardController {
  constructor(
    private readonly ctx: EditingContext,
    private readonly clipboard: ClipboardService,
    private readonly selection: SelectionModel,
    private readonly selectionActions: ISelectionActions,
    private readonly grouping: IGroupingController,
  ) {}

  copy(): ActionOutcome {
    const fragment = this.clipboard.copy(this.selection.nodes);
    return fragment ? OK : failed('Select a node first');
  }

  cut(): ActionOutcome {
    const copied = this.copy();
    if (!copied.ok) return copied;
    return this.selectionActions.deleteSelection();
  }

  paste(at: Point): ActionOutcome {
    const { command, nodeIds } = this.clipboard.pasteCommand(at);
    if (!command) return failed('Clipboard is empty');
    this.ctx.commands.execute(command);
    if (nodeIds.length > 0) {
      this.selection.selectNodes(nodeIds);
      this.grouping.reparentByGeometry(nodeIds);
    }
    return OK;
  }

  duplicate(nodeIds: readonly NodeId[]): ActionOutcome {
    if (nodeIds.length === 0) return OK;
    const fragment = this.clipboard.copy(nodeIds);
    if (!fragment) return failed('Nothing to duplicate');

    // Offset by a few grid steps so the copy sits visibly on top of, rather
    // than exactly hiding, the original.
    const offset = CANVAS.gridSize * 3;
    const { command, nodeIds: created } = this.clipboard.pasteCommand(
      { x: fragment.origin.x + offset, y: fragment.origin.y + offset },
      fragment,
    );
    if (!command) return failed('Nothing to duplicate');
    this.ctx.commands.execute(command);
    if (created.length > 0) this.selection.selectNodes(created);
    return OK;
  }
}
