import { clamp, inflate, unionRects, type Rect } from '@core/kernel/geometry';

/**
 * Should the camera move, where to, and at what scale?
 *
 * Pure geometry: rectangles in, a decision out. No paper, no viewport, no
 * timers — which is what makes the interesting part of "the canvas follows
 * the run" testable at all. Everything that is hard to get right here (the
 * dead zone that stops jitter, the readable ceiling, the zoom floor) is a
 * rule about numbers, and rules about numbers belong in a function you can
 * assert on rather than in a callback you can only watch.
 *
 * Two shapes of answer, because one active node and five active nodes are
 * different questions:
 *
 * - **one node** → `focus`. Bring it to a size you can actually read. A pan
 *   alone is not enough: at the zoom people use to see a whole graph a card
 *   is a coloured box, and following it faithfully still shows you nothing.
 *   "Readable" is a rule about the card's **width** — the one dimension
 *   design fixes — and a card too tall to show whole is framed from its top
 *   rather than shrunk until it fits. See `focusZoomFor`.
 * - **several nodes** (a `Send` fan-out) → `fit`, and *zoom out only*.
 *   Magnifying a fan-out to fill the screen would throw away the context
 *   that makes a fan-out legible in the first place.
 */

export interface FollowInput {
  /** What the user can currently see, in model coordinates. */
  readonly viewport: Rect;
  readonly zoom: number;
  /** The rect of every node currently running. Several during a `Send` fan-out. */
  readonly targets: readonly Rect[];
  /**
   * Comfort inset, as a fraction of each viewport axis. A target already
   * inside the inset rectangle is "comfortably placed" and nothing moves.
   */
  readonly margin: number;
  /** Slack left around the targets when the camera does have to reframe. */
  readonly padding: number;
  readonly minZoom: number;
  readonly maxZoom: number;
  /**
   * Share of the viewport **width** a single focused node should span. Well
   * under 1: the node must be readable, not alone. Width, not "the
   * constraining axis" — see `focusZoomFor`.
   */
  readonly focusFill: number;
  /** Readable ceiling for *automatic* zoom, at or below `maxZoom`. */
  readonly focusMaxZoom: number;
}

export type FollowDecision =
  /** Already comfortable — placed well and readable. Doing nothing is the feature. */
  | { readonly kind: 'stay' }
  /** One node: frame it at a size that can be read. */
  | { readonly kind: 'focus'; readonly center: Rect; readonly zoom: number }
  /** Several nodes: frame them all, zooming out if that is what it takes. */
  | { readonly kind: 'fit'; readonly center: Rect; readonly zoom: number };

/**
 * How far below the ideal scale a node may sit before the camera re-frames
 * it. Without a band the camera chases its own target: any scheme that
 * corrects toward an ideal must tolerate a neighbourhood of that ideal, or
 * every clamp and rounding error becomes another glide. 0.7 is chosen so
 * that the default 1:1 zoom is *inside* the band — starting a run at the
 * zoom the editor opens at must not move the camera at all.
 */
const ZOOM_DEADBAND = 0.7;

/**
 * Slack, in model units, when asking whether a rectangle sits inside the
 * comfort box. A frame clipped to *exactly* the comfort height has to count
 * as contained or a tall card can never settle; the camera's own arithmetic
 * is wrong by fractions of a pixel, never by half a model unit.
 */
const CONTAIN_SLACK = 0.5;

export function decideFollow(input: FollowInput): FollowDecision {
  const { viewport, targets, margin, padding, zoom, minZoom } = input;
  if (targets.length === 0) return { kind: 'stay' };
  if (viewport.width <= 0 || viewport.height <= 0) return { kind: 'stay' };

  const union = unionRects(targets);
  if (!union) return { kind: 'stay' };

  // The dead zone. Without it a node drifting one pixel past the edge would
  // re-centre the camera on every streamed frame, which reads as the canvas
  // twitching rather than following.
  const comfort = inflate(viewport, -viewport.width * margin, -viewport.height * margin);

  const padded = inflate(union, padding);

  if (targets.length === 1) {
    const ideal = focusZoomFor(union, input);
    const tooSmall = zoom < ideal * ZOOM_DEADBAND;
    // "Too big to frame" is a width question too, for the same reason the
    // ideal is: a card wider than the screen has to be pulled back, a card
    // *taller* than the screen has to be read from the top instead.
    const tooWide = padded.width > viewport.width;
    // Re-scale only when the node is genuinely unreadable, or too wide to
    // frame at all. In between, the zoom the user chose is theirs to keep
    // and the camera just goes to the node.
    const scale = tooSmall || tooWide ? ideal : zoom;
    const frame = readableFrame(union, input, scale);
    if (!tooSmall && !tooWide && contains(comfort, frame)) return { kind: 'stay' };
    return { kind: 'focus', center: frame, zoom: scale };
  }

  if (contains(comfort, union)) return { kind: 'stay' };

  // A fan-out. Zoom *out* only — and the floor keeps text readable rather
  // than fitting at any cost.
  const required = Math.min(
    (viewport.width * zoom) / padded.width,
    (viewport.height * zoom) / padded.height,
  );
  return {
    kind: 'fit',
    center: union,
    zoom: clamp(Math.min(required, zoom), minZoom, input.maxZoom),
  };
}

/**
 * The scale at which `target` spans `focusFill` of the viewport **width**.
 *
 * **Width, and only width, because width is the one card dimension design
 * fixes.** `NODE.width` is the same for every card; height is content, and on
 * the shipped Chinook document it runs from 100 model units (a tool) to 1068
 * (the Intent router, with five branch rows, a rules textarea, a model picker
 * and a rules-mode select). Sizing to `min(width, height)` therefore made the
 * *most informative* card the one the camera refused to enlarge: measured on
 * that document at a 768×952 canvas, the height term put the router's ideal
 * at **0.37** while its neighbours got 1.03–1.25, so the run visibly zoomed in
 * on every node except the one that had the most to read. Legibility is a
 * property of type size, type size scales with zoom, and zoom that satisfies
 * the fixed width satisfies the type.
 *
 * Height does not disappear — it decides *which part* of a tall card the
 * camera commits to (`readableFrame`), which is a framing question, not a
 * scaling one. A card taller than the screen cannot be both whole and
 * readable, and readable wins.
 *
 * `viewport` is model space, so `viewport.width * zoom` is the screen in css
 * pixels — the quantity "readable" is actually about. A degenerate target
 * yields `Infinity` here, which the clamp turns into the ceiling rather than
 * into a broken transform.
 */
function focusZoomFor(target: Rect, input: FollowInput): number {
  const { viewport, zoom, focusFill, focusMaxZoom, minZoom, maxZoom } = input;
  const ideal = (viewport.width * zoom * focusFill) / target.width;
  return clamp(ideal, minZoom, Math.min(maxZoom, focusMaxZoom));
}

/**
 * The slice of a target the camera actually frames, at `scale`.
 *
 * For everything that fits, this is the target. For a card taller than the
 * comfort box it is the **top** of that card: centring a 1068-unit router on
 * its geometric middle at a readable scale shows an anonymous band of branch
 * rows, with the header — the node's name, its accent, the running dot — off
 * screen above. Anchoring at the top also makes `stay` reachable for such a
 * card: `contains` can never hold for a rectangle taller than the box it is
 * tested against, so without this the follower would re-issue a move on every
 * streamed frame for exactly the nodes it was trying to help.
 */
function readableFrame(target: Rect, input: FollowInput, scale: number): Rect {
  const { viewport, zoom, margin } = input;
  // The comfort box's height, expressed in model units at `scale`.
  const room = ((viewport.height * zoom) / scale) * (1 - 2 * margin);
  if (!(room > 0) || target.height <= room) return target;
  return { x: target.x, y: target.y, width: target.width, height: room };
}

function contains(outer: Rect, inner: Rect): boolean {
  return (
    inner.x >= outer.x - CONTAIN_SLACK &&
    inner.y >= outer.y - CONTAIN_SLACK &&
    inner.x + inner.width <= outer.x + outer.width + CONTAIN_SLACK &&
    inner.y + inner.height <= outer.y + outer.height + CONTAIN_SLACK
  );
}
