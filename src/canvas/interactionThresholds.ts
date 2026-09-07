/**
 * The paper's pointer thresholds — and, more to the point, their units.
 *
 * These three JointJS options look like a family and are not one. Two are
 * measured in pixels and one counts events, and the one that counts events is
 * spelled exactly like the two that do not. Keeping them here, named and
 * explained, is cheaper than rediscovering the difference from a canvas that
 * silently refuses to draw a link.
 */

/**
 * How far the pointer may travel between press and release and still be
 * reported as a click. **Pixels.**
 *
 * This is the option that stops a 1px wobble on a trackpad from being read as
 * a drag — the job `MOVE_THRESHOLD` was mistakenly set to do.
 */
export const CLICK_THRESHOLD = 4;

/**
 * How many `pointermove` events to **discard** at the start of every gesture.
 * **A count of events, not a distance.**
 *
 * JointJS implements it as `if (++mousemoved <= moveThreshold) return;`, so a
 * value of *n* throws away the first *n* moves of every drag no matter how far
 * they travelled.
 *
 * It was set to `2` here with the comment *"clicks land as clicks rather than
 * 1px drags on a trackpad"* — a pixel-distance intention expressed through an
 * event counter, sitting next to `clickThreshold: 4`, which really is pixels
 * and really does that job. The consequence, measured on the running editor:
 * a drag from one port to a nearby port emits **two** `mousemove` events, both
 * were swallowed, and connecting two adjacent nodes by hand did nothing at
 * all — no link, no rejection, no hint. Three or more moves worked, which is
 * why a slow, wandering drag connected and a confident one did not.
 *
 * Zero is both the JointJS default and the only safe value: any positive
 * number makes a short gesture unexpressible, and short gestures are exactly
 * what wiring two ports together is.
 */
export const MOVE_THRESHOLD = 0;

/**
 * When a drag that began on a magnet becomes a link. `'onleave'` starts it as
 * the pointer leaves the port, which is what lets a press-and-release on a
 * port stay a selection rather than a stillborn edge.
 */
export const MAGNET_THRESHOLD = 'onleave';

/**
 * How near a legal port the pointer must get for a dragged link to land on it,
 * **in screen pixels** — a constant distance for the hand, at every zoom.
 *
 * JointJS's own `snapLinks.radius` is in *local* units, and that is the trap
 * this constant exists to close. Set once at construction, a radius of 40
 * measures 40px at 100% zoom but **10px at 25%** — it shrinks precisely when a
 * whole workflow is on screen, the ports are 7px apart, and the forgiveness is
 * most needed. Measured: with a fixed radius of 40, a drop 8px off-target
 * connected and one 14px off did not. So `PaperController` divides this by the
 * live zoom on every viewport change, and the distance stays put.
 *
 * Off by default in JointJS, and off here until now, which meant a drop had to
 * land inside the port's own hit circle. That circle is `r: 10` in model units
 * and therefore *scales with zoom*: at the 25–36% a whole workflow is read at,
 * it renders 5–9 CSS pixels across, with neighbouring ports 7–9 pixels apart.
 * Reconnecting an edge you had just detached meant hitting a three-pixel
 * bullseye — reported from real use as "really struggled to connect again",
 * which is the honest description of a target that small.
 *
 * Enlarging the circle instead does not work: at 100% zoom a radius big enough
 * to be comfortable at 30% would swallow the neighbouring port, so a drop would
 * land on `skill` when it meant `prompt`. Snapping has no such trade-off — it
 * picks the *closest* candidate, so a generous radius stays unambiguous.
 *
 * JointJS filters candidates through `validateConnection`, so this only ever
 * pulls a link toward a port the rules already accept. It cannot make an
 * illegal connection easier to draw.
 */
export const SNAP_RADIUS_PX = 28;

/** The local-unit radius that shows as `SNAP_RADIUS_PX` at this zoom. */
export function snapRadiusAtZoom(zoom: number): number {
  return zoom > 0 ? SNAP_RADIUS_PX / zoom : SNAP_RADIUS_PX;
}
