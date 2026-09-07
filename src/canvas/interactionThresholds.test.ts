import { describe, expect, it } from 'vitest';
import { CLICK_THRESHOLD, MAGNET_THRESHOLD, MOVE_THRESHOLD } from './interactionThresholds';

/**
 * A regression guard for a defect that had no visible failure mode.
 *
 * `moveThreshold` counts `pointermove` events; it was set to `2`, so the first
 * two moves of every gesture were discarded. A hand-drawn connection between
 * two nearby ports emits two moves, so it produced no link and no complaint.
 * Measured in the browser: 1 or 2 moves did nothing, 3 moves drew the link.
 */
describe('paper interaction thresholds', () => {
  it('discards no pointer moves, because a short drag has only two', () => {
    // The number is the whole point: any positive value silently swallows a
    // connection drag between adjacent ports.
    expect(MOVE_THRESHOLD).toBe(0);
  });

  it('keeps a pixel budget for the wobble that ends in a click', () => {
    // The job `moveThreshold` was wrongly asked to do belongs here, where the
    // unit really is pixels.
    expect(CLICK_THRESHOLD).toBeGreaterThan(0);
  });

  it('starts a link only once the pointer leaves the port', () => {
    expect(MAGNET_THRESHOLD).toBe('onleave');
  });
});
