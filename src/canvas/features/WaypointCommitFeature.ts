import type { dia } from '@joint/core';
import type { Point } from '@core/kernel/geometry';
import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';

/**
 * Commits waypoint gestures to the document.
 *
 * `linkTools.Vertices` — already attached by `LinkToolsFeature` — lets a user
 * click a link to add a point, drag it, and double-click it to take it away.
 * It has always done so; the points simply had nowhere to live, so the next
 * re-projection swept them away and nothing ever reached the file. This is the
 * missing half: every such change is written back through a command, which is
 * what makes it undoable and what makes it saved.
 *
 * Same shape as `DragCommitFeature`, and for the same reason — the graph leads
 * the model for the duration of a gesture — but the commit is per change
 * rather than on pointer-up. A vertex handle is a tool view with its own
 * pointer sequence, so there is no `link:pointerup` to hang the commit on;
 * `SetEdgeVerticesCommand` coalesces per edge instead, which collapses the
 * drag into one undo step by the same mechanism a typed label uses.
 */
export class WaypointCommitFeature extends PaperFeature {
  readonly id = 'waypoint-commit';

  protected onInstall(ctx: PaperFeatureContext): void {
    const { controller, adapter } = ctx;

    this.onGraph('change:vertices', ((link: dia.Link, vertices: readonly Point[]) => {
      // The adapter writing the model's own waypoints back onto the cell is
      // not a user gesture, and committing it would push a no-op command for
      // every projection.
      if (adapter.isApplying) return;
      const edge = controller.model.edge(String(link.id));
      if (!edge) return;

      const next = (vertices ?? []).map((point) => ({ x: point.x, y: point.y }));
      const current = edge.vertices;
      if (
        next.length === current.length &&
        next.every((point, index) => {
          const previous = current[index];
          return previous != null && point.x === previous.x && point.y === previous.y;
        })
      ) {
        return;
      }

      controller.edges.setVertices(edge.id, next);
    }) as never);
  }
}
