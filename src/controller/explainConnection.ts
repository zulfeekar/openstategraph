/**
 * What a connection gesture should say when it ends.
 *
 * One drag crosses many ports, and `validateConnection` runs on every one of
 * them — so the reason cannot be announced when it is computed, or hovering
 * across a card would fire a toast per port. It is recorded instead, and this
 * decides what to do with it once the pointer is released.
 *
 * Pure, and here rather than inside the canvas feature, because the rule is
 * three lines of judgement and the feature is JointJS event wiring that no
 * unit test can reach.
 */
export interface GestureEnd {
  /** True when a link was actually made during this gesture. */
  readonly connected: boolean;
  /** The reason the last port under the pointer refused, if one did. */
  readonly lastRefusal: string | null;
}

export function announcementFor({ connected, lastRefusal }: GestureEnd): string | null {
  // A made link speaks for itself — the edge is on the canvas.
  if (connected) return null;
  // Released over blank canvas or a card body: no rule refused anything, so
  // there is nothing to explain. Complaining here would turn every abandoned
  // drag into an error.
  return lastRefusal;
}
