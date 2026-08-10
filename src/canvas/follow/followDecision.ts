import { clamp, inflate, unionRects, type Rect } from '@core/kernel/geometry';

/**
 * Should the camera move, and where to?
 *
 * Pure geometry: rectangles in, a decision out. No paper, no viewport, no
 * timers — which is what makes the interesting part of "the canvas follows
 * the run" testable at all. Everything that is hard to get right here (the
 * dead zone that stops jitter, the refusal to zoom in, the zoom floor) is a
 * rule about numbers, and rules about numbers belong in a function you can
 * assert on rather than in a callback you can only watch.
 */

export interface FollowInput {
  /** What the user can currently see, in model coordinates. */
  readonly viewport: Rect;
  readonly zoom: number;
  /** The rect of every node currently running. Several during a `Send` fan-out. */
  readonly targets: readonly Rect[];
  /**
   * Comfort inset, as a fraction of each viewport axis. A target already
   * inside the inset rectangle is "comfortably visible" and nothing moves.
   */
  readonly margin: number;
  /** Slack left around the targets when the camera does have to reframe. */
  readonly padding: number;
  readonly minZoom: number;
  readonly maxZoom: number;
}

export type FollowDecision =
  /** Already comfortable. Doing nothing is the feature. */
  | { readonly kind: 'stay' }
  /** Pan only — the zoom the user chose is theirs to keep. */
  | { readonly kind: 'pan'; readonly center: Rect }
  /** The active set does not fit; zoom out far enough that it does. */
  | { readonly kind: 'fit'; readonly center: Rect; readonly zoom: number };

export function decideFollow(input: FollowInput): FollowDecision {
  const { viewport, targets, margin, padding, zoom, minZoom, maxZoom } = input;
  if (targets.length === 0) return { kind: 'stay' };
  if (viewport.width <= 0 || viewport.height <= 0) return { kind: 'stay' };

  const union = unionRects(targets);
  if (!union) return { kind: 'stay' };

  // The dead zone. Without it a node drifting one pixel past the edge would
  // re-centre the camera on every streamed frame, which reads as the canvas
  // twitching rather than following.
  const comfort = inflate(
    viewport,
    -viewport.width * margin,
    -viewport.height * margin,
  );
  if (contains(comfort, union)) return { kind: 'stay' };

  const padded = inflate(union, padding);

  // Does it fit at the zoom the user is already on? Then move the camera and
  // leave the zoom alone. This is also what stops a single active node being
  // magnified until its surroundings are gone: one card always fits, so one
  // card is always a pan.
  if (padded.width <= viewport.width && padded.height <= viewport.height) {
    return { kind: 'pan', center: union };
  }

  // A fan-out wider than the screen. Zoom *out* only — scaling up to "fit"
  // two small nodes would throw away the context the user was looking at, and
  // the floor keeps text readable rather than fitting at any cost.
  const required = Math.min(
    (viewport.width * zoom) / padded.width,
    (viewport.height * zoom) / padded.height,
  );
  return {
    kind: 'fit',
    center: union,
    zoom: clamp(Math.min(required, zoom), minZoom, maxZoom),
  };
}

function contains(outer: Rect, inner: Rect): boolean {
  return (
    inner.x >= outer.x &&
    inner.y >= outer.y &&
    inner.x + inner.width <= outer.x + outer.width &&
    inner.y + inner.height <= outer.y + outer.height
  );
}
