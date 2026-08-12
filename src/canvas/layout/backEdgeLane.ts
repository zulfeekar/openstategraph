import type { Point, Rect } from '@core/kernel/geometry';
import type { FlowDirection } from '@core/model/contracts/ports';

/**
 * A lane, outside the arrangement, for every link that runs against the flow.
 *
 * **The case this exists for** is the grader's `revise` back-edge, and it is
 * the one every previous attempt lost. An evaluator-optimizer loop returns
 * across three ranks; a layered layout has no rank to put it in, so wherever it
 * goes it goes *through* something. `edge-legibility` recorded it as the free
 * stack's limit and named the fix as a paid router, which was wrong on both
 * counts: the free `manhattan` router does avoid obstacles, and it was tried
 * first here. It works — no card is crossed — but the corridor it finds is the
 * gap between an agent and its tool shelf, so the return run then cuts across
 * all three tool bindings on their way into the bus. Measured on the seeded
 * demo: 0 card crossings and 4 edge crossings, three of them that one link.
 *
 * That corridor is not free space. It is the band `bindingLayout` reserves for
 * equipment, and a run through it says the return path is somehow related to
 * the tools. So the answer is not a cleverer search, it is the owner's own
 * sketch: **the back-edge gets a lane of its own**, outside everything, and
 * the router is told to pass through it.
 *
 * Expressed as *waypoints*, which is what makes it cost nothing extra: they
 * are the same points a user can drag, stored the same way, undone in the same
 * step. The layout seeds a good default for the one shape that needs one, and
 * a user who disagrees moves it.
 *
 * Pure by construction: rects in, points out. No JointJS, no paper, no DOM.
 */

/** One link, reduced to the two rectangles it joins. */
export interface LaneCandidate {
  readonly edgeId: string;
  readonly source: Rect;
  readonly target: Rect;
}

const centre = (rect: Rect, flow: FlowDirection): number =>
  flow === 'horizontal' ? rect.x + rect.width / 2 : rect.y + rect.height / 2;

/**
 * Does this link run against the reading direction?
 *
 * Compared at the cards' centres rather than their edges, so two cards that
 * merely overlap in the flow axis — a shelf item and its consumer, say — are
 * not called a back-edge on a few pixels.
 */
export function isBackEdge(candidate: LaneCandidate, flow: FlowDirection): boolean {
  return centre(candidate.target, flow) < centre(candidate.source, flow);
}

/**
 * Waypoints for each back-edge, keyed by edge id.
 *
 * The lane sits past the far edge of the whole arrangement — under it in
 * horizontal flow, beside it in vertical — because that is the only space no
 * rank and no shelf has a claim on. Everything else is somebody's.
 *
 * **Longest outermost.** Two back-edges nesting inside one another would cross
 * if the shorter took the outer lane, so they are sorted by span and the
 * longest gets the outermost. With one back-edge — every graph shipped today —
 * the sort is a no-op that costs nothing and stops the two-loop case from
 * being a surprise.
 *
 * Two points, not one: a single mid-lane point leaves the router free to
 * approach it diagonally in the flow axis and rejoin early. Pinning both ends
 * of the lane run makes the horizontal (or vertical) leg the lane itself.
 */
export function backEdgeLanes(
  candidates: readonly LaneCandidate[],
  occupied: readonly Rect[],
  flow: FlowDirection,
  gap: number,
): ReadonlyMap<string, readonly Point[]> {
  const lanes = new Map<string, readonly Point[]>();
  const back = candidates.filter((candidate) => isBackEdge(candidate, flow));
  if (back.length === 0 || occupied.length === 0) return lanes;

  const span = (candidate: LaneCandidate): number =>
    Math.abs(centre(candidate.source, flow) - centre(candidate.target, flow));
  // Ascending, and the lane index grows with it: the shortest return takes the
  // lane nearest the cards and the longest takes the outermost, so a loop
  // nested inside another loop never has to cross it.
  const ordered = [...back].sort((a, b) => span(a) - span(b));

  if (flow === 'horizontal') {
    const base = Math.max(...occupied.map((rect) => rect.y + rect.height));
    ordered.forEach((candidate, index) => {
      const y = Math.round(base + gap * (index + 1));
      lanes.set(candidate.edgeId, [
        { x: Math.round(candidate.source.x + candidate.source.width + gap / 2), y },
        { x: Math.round(candidate.target.x - gap / 2), y },
      ]);
    });
    return lanes;
  }

  const base = Math.max(...occupied.map((rect) => rect.x + rect.width));
  ordered.forEach((candidate, index) => {
    const x = Math.round(base + gap * (index + 1));
    lanes.set(candidate.edgeId, [
      { x, y: Math.round(candidate.source.y + candidate.source.height + gap / 2) },
      { x, y: Math.round(candidate.target.y - gap / 2) },
    ]);
  });
  return lanes;
}
