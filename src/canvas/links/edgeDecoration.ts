import type { connectors, dia, routers } from '@joint/core';
import type { FlowDirection, IPortDescriptor, PortSide } from '@core/model/contracts/ports';

/**
 * How a link is drawn and what, if anything, it says.
 *
 * Pure: it takes ports and a flow direction and returns JointJS option
 * objects. No paper, no graph, no DOM — which is why the rules below are unit
 * tested rather than eyeballed.
 *
 * **The problem this solves.** The card's port footer names every port in a
 * right-aligned list. In *horizontal* flow that list sits beside the dots it
 * names, so a router's five branches read straight off the card. Rotate the
 * canvas and the dots move to the card's bottom edge, spread across its width
 * — while the names stay in the footer. The name and the thing it names come
 * apart, and with five branches, a grader loop and an approval on screen there
 * is no way to tell which line is which. That is the owner's "connection
 * labels are off, especially on vertical flow".
 *
 * The fix is not to move the footer. It is to accept that *which way did it
 * go* is a fact about the **connection**, so it belongs on the link — where it
 * is equally readable in either reading direction, and where professional
 * diagramming has always put a guard condition.
 */

/**
 * How sharp a corner is.
 *
 * The owner asked for a *rigid* line, so the run is orthogonal and the corner
 * is only eased, not rounded away: at 8px a bend still reads as a right angle
 * at fit-zoom, while the join stops being the one-pixel spike that a hairline
 * stroke turns a true 90° into.
 */
const CORNER_RADIUS = 8;

/**
 * The connector for every link.
 *
 * The route is a list of orthogonal points — the router's job, below — so the
 * connector's only remaining decision is what a corner looks like. `rounded`
 * draws the segments verbatim and eases each bend by `radius`.
 *
 * It replaces `curve`, and with it the whole tangent apparatus: a spline's
 * tangent existed to make a line *leave a port in the port's own direction*,
 * which an orthogonal router expresses directly as a start direction. The
 * knowledge is not discarded, it moved — see `linkRouter`.
 */
export const LINK_CONNECTOR: connectors.GenericConnectorJSON<'rounded'> = {
  name: 'rounded',
  args: { radius: CORNER_RADIUS },
};

/**
 * Which way a run leaves a card, per side of the card.
 *
 * This is `TANGENT_OUT` from the curve era, restated in the router's
 * vocabulary: JointJS names a curve's tangents `up`/`down` and a router's
 * directions `top`/`bottom`, for the same four facts.
 */
const RUN_OUT: Record<PortSide, dia.OrthogonalDirection> = {
  left: 'left' as dia.OrthogonalDirection,
  right: 'right' as dia.OrthogonalDirection,
  top: 'top' as dia.OrthogonalDirection,
  bottom: 'bottom' as dia.OrthogonalDirection,
};

/**
 * The routing grid, and how far a run stays off a card it passes.
 *
 * `step` is the pathfinder's grid. It is a divisor of `NODE.portRowHeight`
 * (24) on purpose: two runs leaving adjacent ports are 24 apart, so a grid of
 * 12 can hold them apart instead of snapping them onto one line.
 *
 * `padding` is the clearance the search keeps around every obstacle. It is
 * half the cross-flow node gap, so a run diverted between two cards has room
 * for itself and still leaves a visible gap on both sides.
 */
const ROUTER_STEP = 12;
export const ROUTER_PADDING = 24;

/**
 * The router for one link, with both ends pinned to the sides its ports sit
 * on, and obstacle avoidance in between.
 *
 * **`manhattan`, and it is not a paid feature.** The decision record for the
 * previous edge work stated that the fix for the one remaining card crossing
 * was "an obstacle-avoiding router (paid)". That was false and it is corrected
 * in `docs/decisions/edge-legibility.md`: the free package ships
 * `manhattan`, `metro`, `normal`, `oneSide`, `orthogonal` and `rightAngle`,
 * and `manhattan` is the obstacle-avoiding one. The claim is load-bearing
 * because it is why a real defect — the grader's `revise` back-edge crossing
 * two cards — was written off instead of fixed.
 *
 * **Why the directions are supplied rather than guessed.** Exactly the reason
 * the curve connector's tangents were: once links attach to **magnets**,
 * `LinkView.sourceBBox` is the *port's* 10px hit circle rather than the card,
 * so any "which side of the box is this nearest" rule degenerates to
 * "whichever way the target lies", and a run leaving a bottom port sets off
 * sideways along the card's own border. `startDirections`/`endDirections`
 * take the answer from `resolvePortSide`, which is where the flow direction
 * lives — so this stays the one place the reading direction reaches link
 * geometry, and nothing here needs a `flow` parameter of its own.
 *
 * A single direction, never a list: the port is on one side of the card, and
 * offering the router alternatives is how a run ends up leaving a dot
 * backwards to save four pixels of path length.
 */
export function linkRouter(
  sourceSide: PortSide | undefined,
  targetSide: PortSide | undefined,
  obstacles?: (point: dia.Point) => boolean,
): routers.GenericRouterJSON<'manhattan'> {
  return {
    name: 'manhattan',
    args: {
      step: ROUTER_STEP,
      padding: ROUTER_PADDING,
      // 90, not the 45 the pathfinder defaults to: a 45° change is how
      // `metro` earns its diagonals, and a diagonal is the one thing the
      // owner's sketch rules out.
      maxAllowedDirectionChange: 90,
      ...(sourceSide ? { startDirections: [RUN_OUT[sourceSide]] } : {}),
      // Outward at both ends, like the tangents were: a run arriving at a top
      // port has direction `top`, and therefore comes *down* into it.
      ...(targetSide ? { endDirections: [RUN_OUT[targetSide]] } : {}),
      ...(obstacles ? { isPointObstacle: obstacles } : {}),
    } as routers.ManhattanRouterArguments,
  };
}

/**
 * The router before anything is known about the ports.
 *
 * The shape default and the paper default, so a link being *dragged* — which
 * has no target port yet, and therefore no side to pin to — is orthogonal from
 * the first frame rather than snapping from a diagonal to a run on drop. The
 * adapter re-pins both ends the moment the edge exists.
 */
export const LINK_ROUTER = linkRouter(undefined, undefined);

/**
 * Label rhythm per reading direction.
 *
 * `distance` is an absolute path length from the **source** end, not a 0–1
 * ratio: a branch name means "this is the way out of *this* node", so it
 * belongs where the line leaves, not at a midpoint that drifts with the
 * target's position.
 *
 * `step` staggers siblings along their own lines so five labels leaving one
 * card do not stack. Vertical needs the larger step — dagre's rank separation
 * puts rows closer together than columns, so sibling lines run more nearly
 * parallel and their labels would overlap sooner.
 */
const LABEL_RHYTHM: Record<FlowDirection, { base: number; step: number }> = {
  horizontal: { base: 50, step: 26 },
  vertical: { base: 56, step: 34 },
};

/**
 * Perpendicular clearance, alternating side by rank.
 *
 * The stagger alone is not enough, and Store Analytics proves it: the
 * `database_deep_dive` and `sql_specialist` branches both dive down-left along
 * nearly the same curve, so points 34 apart *along* two near-identical paths
 * landed 6px apart on screen. Alternating the side splits any such pair by
 * twice this figure regardless of what the curves do — collision avoidance
 * that costs one modulo instead of a layout pass over rendered label boxes.
 */
const LABEL_CLEARANCE = 13;

/**
 * Where a link's label sits.
 *
 * `keepGradient` is deliberately **off**. Rotating text to follow the line
 * reads well in a horizontal diagram and becomes sideways words the moment the
 * canvas is vertical — the same "tuned for horizontal, reused rotated" mistake
 * one level down. Text stays upright; the halo behind it (see the label markup
 * in `JointGraphAdapter`) is what makes it survive crossing a line.
 */
export interface LabelPlacement extends dia.Link.LabelPosition {
  /** Absolute path length from the source end — always present here. */
  readonly distance: number;
}

export function labelPlacement(flow: FlowDirection, rank: number): LabelPlacement {
  const rhythm = LABEL_RHYTHM[flow];
  return {
    distance: rhythm.base + Math.max(0, rank) * rhythm.step,
    // Kept small on purpose: far enough to separate two sibling labels, near
    // enough that the halo still reads as belonging to the line under it.
    offset: Math.max(0, rank) % 2 === 0 ? -LABEL_CLEARANCE : LABEL_CLEARANCE,
    args: { keepGradient: false },
  };
}

/**
 * The text a link carries, or `null` for the ones that need none.
 *
 * The cheapest legibility win available: only conditional branches get words.
 * A typed edge already carries its port type's hue *and* a dash signature and
 * is explained by the legend, so labelling it too would bury the labels that
 * actually resolve an ambiguity.
 */
export function edgeLabelText(
  authored: string | null,
  sourcePort: IPortDescriptor | undefined,
): string | null {
  const trimmed = authored?.trim();
  if (trimmed) return trimmed;
  if (sourcePort?.branch) return sourcePort.label;
  return null;
}

/**
 * A branch's position among its siblings, used to stagger labels.
 *
 * Taken from the node's own port order rather than from edge order, so the
 * stagger is a property of the card and does not reshuffle when a link is
 * deleted and redrawn.
 */
export function branchRank(ports: readonly IPortDescriptor[], portId: string): number {
  const branches = ports.filter((port) => port.branch);
  const index = branches.findIndex((port) => port.id === portId);
  return index < 0 ? 0 : index;
}
