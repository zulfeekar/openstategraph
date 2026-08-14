import type { Point } from '@core/kernel/geometry';

/**
 * How far each cascade step moves. Big enough that the card underneath is
 * visibly a *different* card rather than a rendering seam, small enough that
 * a handful of clicks stay inside the viewport they were aimed at.
 */
export const PLACEMENT_STEP = 28;

/**
 * How close counts as "already there". Cards hide each other when they are
 * near, not only when they coincide — a two-pixel offset conceals a node just
 * as thoroughly as none, and looks like a rendering bug rather than a second
 * node.
 */
const OCCUPIED_WITHIN = PLACEMENT_STEP / 2;

/** A ceiling on the cascade, so a crowded canvas cannot hang the editor. */
const MAX_STEPS = 40;

/**
 * A spot at or near `preferred` that no existing node is sitting on.
 *
 * Exists because clicking a palette item three times put three nodes at
 * exactly the same coordinate (canvas-feels-right ticket 01): one visible
 * card, two buried under it, and nothing to tell the user. Someone who clicks
 * again because the first click looked like it did nothing ends up with the
 * thing they think they failed to create.
 *
 * A **drag** never needs this — it carries a drop point, and putting a node
 * exactly where the pointer released it is the whole contract. This is only
 * for placements the user did not aim: the palette click, and anything else
 * that has to invent a position.
 *
 * Pure geometry over positions, in `core/`, so it is testable without a
 * canvas — the rule is easy to state and was impossible to see.
 */
export function freePositionNear(preferred: Point, occupied: readonly Point[]): Point {
  const taken = (at: Point): boolean =>
    occupied.some(
      (other) =>
        Math.abs(other.x - at.x) < OCCUPIED_WITHIN && Math.abs(other.y - at.y) < OCCUPIED_WITHIN,
    );

  let at = preferred;
  for (let step = 0; step < MAX_STEPS; step += 1) {
    if (!taken(at)) return at;
    at = {
      x: preferred.x + PLACEMENT_STEP * (step + 1),
      y: preferred.y + PLACEMENT_STEP * (step + 1),
    };
  }
  // Every step of the diagonal is occupied. Returning the last one is worse
  // than it sounds only in theory: the node is placed, visible somewhere on
  // that diagonal, selectable and undoable. Hanging the editor to find a
  // perfect gap would be the actual failure.
  return at;
}
