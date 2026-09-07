import type { Point, Rect } from '@core/kernel/geometry';

/**
 * What an orthogonal run has to go round, and what it may go straight through.
 *
 * `manhattan` builds its own obstacle map from every element in the graph, and
 * offers `excludeTypes` to drop some of them — keyed on the JointJS cell
 * *type*, which every one of our cards and every one of our frames shares. So
 * the stock map would treat an annotation frame as a wall, and a run passing
 * behind a labelled region would take a detour round a rectangle that is not
 * there.
 *
 * The classification already exists and has one owner: a node's `kind`.
 * `AutoLayout` reads exactly the same field to decide what dagre may rank —
 * *"a frame has no edges"* — and `edge-legibility` recorded the rule in as many
 * words: **frames are not obstacles, a frame is a background region things sit
 * inside.** This is that rule, read by the thing that draws the lines.
 *
 * Supplying `isPointObstacle` replaces the stock map wholesale — `padding`,
 * `excludeEnds` and `excludeTypes` are all ignored once it is set — so the
 * padding is re-applied here, and it must be the *same* number the router
 * expands its end boxes by or the two disagree about where a run may start.
 */

/**
 * A predicate over the routing grid: is this point inside something?
 *
 * **Strictly** inside. The router derives its first and last route point on
 * the boundary of a padded end box, and a boundary counted as blocked would
 * fail the accessibility check and drop the whole link to the fallback router
 * — a straight diagonal, which is the one shape orthogonal routing exists to
 * remove. So the edge of the padded rect belongs to the run, not to the card.
 */
export function obstacleTest(rects: readonly Rect[], padding: number): (point: Point) => boolean {
  const bounds = rects.map((rect) => ({
    left: rect.x - padding,
    top: rect.y - padding,
    right: rect.x + rect.width + padding,
    bottom: rect.y + rect.height + padding,
  }));
  return (point: Point): boolean =>
    bounds.some(
      (box) =>
        point.x > box.left && point.x < box.right && point.y > box.top && point.y < box.bottom,
    );
}
