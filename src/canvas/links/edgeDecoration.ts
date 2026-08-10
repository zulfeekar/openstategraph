import type { connectors, dia } from '@joint/core';
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
 * The connector for every link.
 *
 * `curve` with `direction: 'auto'` takes each end's tangent from the side of
 * the card the port actually sits on. Since `resolvePortSide` already rotates
 * port sides with the flow direction, one connector is correct in both
 * readings with no mode flag.
 *
 * It replaces `smooth`, whose no-vertices branch picks its control points from
 * whichever of |dx| and |dy| is larger. That is a *bounding box* guess, not a
 * port fact: a link leaving a bottom port towards a card offset sideways got
 * horizontal control points, so it left the dot sideways and doubled back —
 * the visual tell that a horizontal layout had been reused rotated.
 */
export const LINK_CONNECTOR: connectors.GenericConnectorJSON<'curve'> = {
  name: 'curve',
  args: {
    // The string is the enum's own value; spelling it out keeps this module a
    // type-only importer of `@joint/core`, which is what lets it be unit
    // tested in the node environment the rest of the suite runs in.
    direction: 'auto' as connectors.CurveDirections,
    // Shorter tangents than the 0.6 default: with cards this close together a
    // long tangent overshoots and the curve bulges back across its neighbour.
    distanceCoefficient: 0.45,
  },
};

/** Which way a curve leaves a card, per side of the card. */
const TANGENT_OUT: Record<PortSide, connectors.CurveTangentDirections> = {
  left: 'left' as connectors.CurveTangentDirections,
  right: 'right' as connectors.CurveTangentDirections,
  top: 'up' as connectors.CurveTangentDirections,
  bottom: 'down' as connectors.CurveTangentDirections,
};

/**
 * The connector for one link, with both tangents pinned to the sides its two
 * ports actually sit on.
 *
 * `direction: 'auto'` is not enough once links attach to **magnets**:
 * `LinkView.sourceBBox` is then the *port's* 10px hit circle, not the card, so
 * "which side of the box is this point nearest" degenerates to "whichever way
 * the target lies". A branch leaving the bottom edge towards a card up and to
 * the right got a horizontal tangent and ran along the card's own bottom
 * border — measured on Store Analytics, where the path came back
 * `M 400 1106 C 911 1106 1586 1263 2097 1263`: a flat S, from a port pointing
 * straight down.
 *
 * So the sides are supplied rather than guessed. They come from
 * `resolvePortSide`, which is where the flow direction lives — which makes
 * this the one place the reading direction reaches link geometry, and the
 * reason nothing here needs a `flow` parameter of its own.
 */
export function linkConnector(
  sourceSide: PortSide | undefined,
  targetSide: PortSide | undefined,
): connectors.GenericConnectorJSON<'curve'> {
  return {
    name: 'curve',
    args: {
      ...LINK_CONNECTOR.args,
      ...(sourceSide ? { sourceDirection: TANGENT_OUT[sourceSide] } : {}),
      // The target tangent is *outward* too — JointJS measures it away from
      // the card, so a link arriving at a top port has an 'up' tangent and
      // therefore comes down into it.
      ...(targetSide ? { targetDirection: TANGENT_OUT[targetSide] } : {}),
    },
  };
}

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
