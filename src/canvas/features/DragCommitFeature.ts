import type { dia } from '@joint/core';
import type { Point } from '@core/kernel/geometry';
import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';

/**
 * Commits node drags to the document as single undoable moves.
 *
 * JointJS moves elements continuously while the pointer is down, so the
 * graph leads the model for the duration of a drag. This feature snapshots
 * positions on pointer-down and writes one `MoveNodesCommand` on pointer-up.
 *
 * Committing per frame instead would flood the command stack (coalescing
 * would hide it, but every frame would still round-trip through the model
 * and back to the graph). Committing once means the drag stays smooth and
 * one Cmd-Z returns the nodes to exactly where they started.
 *
 * Multi-select drags are handled here too: JointJS only drags the grabbed
 * element, so the rest of the selection is translated alongside it.
 */
export class DragCommitFeature extends PaperFeature {
  readonly id = 'drag-commit';

  /** Positions of every participating node at drag start. */
  private snapshot = new Map<string, Point>();
  private leader: string | null = null;
  private leaderStart: Point | null = null;

  protected onInstall(ctx: PaperFeatureContext): void {
    const { controller, adapter } = ctx;

    this.onPaper('element:pointerdown', ((view: dia.ElementView) => {
      if (adapter.isApplying) return;

      const nodeId = String(view.model.id);
      this.leader = nodeId;
      this.leaderStart = { ...view.model.position() };
      this.snapshot.clear();

      // The drag set is the selection when the grabbed node is part of it,
      // otherwise just the grabbed node.
      const selected = controller.selection.nodes;
      const participants = selected.includes(nodeId) ? selected : [nodeId];

      for (const id of participants) {
        const element = adapter.element(id);
        if (element) this.snapshot.set(id, { ...element.position() });
        // Descendants move with their container; they need committing too or
        // an undo would leave them behind.
        for (const child of controller.model.descendantsOf(id)) {
          const childElement = adapter.element(child.id);
          if (childElement) this.snapshot.set(child.id, { ...childElement.position() });
        }
      }
    }) as never);

    // Translate the rest of the selection in step with the grabbed node.
    this.onGraph('change:position', ((
      element: dia.Element,
      position: Point,
      opt: { ui?: boolean },
    ) => {
      if (!opt?.ui || adapter.isApplying) return;
      if (this.leader !== String(element.id) || !this.leaderStart) return;

      const dx = position.x - this.leaderStart.x;
      const dy = position.y - this.leaderStart.y;
      this.leaderStart = { x: position.x, y: position.y };
      if (dx === 0 && dy === 0) return;

      for (const id of this.snapshot.keys()) {
        if (id === this.leader) continue;
        const other = adapter.element(id);
        // Skip embedded children: JointJS already moved them with their
        // parent, and translating again would double the delta.
        if (!other || other.getParentCell()) continue;
        other.translate(dx, dy, { ui: true, dyflowFollow: true });
      }
    }) as never);

    this.onPaper('element:pointerup', (() => {
      if (this.snapshot.size === 0) {
        this.reset();
        return;
      }

      const moves: { nodeId: string; position: Point }[] = [];
      for (const [nodeId, from] of this.snapshot) {
        const element = adapter.element(nodeId);
        if (!element) continue;
        const to = element.position();
        if (to.x === from.x && to.y === from.y) continue;
        moves.push({ nodeId, position: { x: to.x, y: to.y } });
      }

      if (moves.length > 0) {
        // Rewind the graph to the pre-drag state first, so the command's
        // own `from` values are authoritative and the model → graph sync
        // reapplies the final position exactly once.
        for (const [nodeId, from] of this.snapshot) {
          adapter.element(nodeId)?.position(from.x, from.y);
        }
        controller.nodes.move(moves);
        // Containment is decided by where the node landed, in the same
        // undo step as the move.
        controller.grouping.reparentByGeometry(moves.map((move) => move.nodeId));
      }

      this.reset();
    }) as never);

    // Containers deliberately do *not* auto-fit to their children. An
    // auto-growing frame would change size behind the user's back — and
    // since only the model may own geometry, every such change would have to
    // round-trip as a command. A frame the user sized stays that size.
  }

  private reset(): void {
    this.snapshot.clear();
    this.leader = null;
    this.leaderStart = null;
  }
}
