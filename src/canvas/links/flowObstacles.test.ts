import { describe, expect, it } from 'vitest';
import type { Rect } from '@core/kernel/geometry';
import { obstacleTest } from './flowObstacles';

const card: Rect = { x: 100, y: 100, width: 200, height: 100 };

describe('obstacleTest', () => {
  it('blocks the inside of a card', () => {
    const blocked = obstacleTest([card], 0);
    expect(blocked({ x: 200, y: 150 })).toBe(true);
    expect(blocked({ x: 400, y: 150 })).toBe(false);
  });

  it('keeps runs the padding distance clear of a card', () => {
    const blocked = obstacleTest([card], 24);
    expect(blocked({ x: 310, y: 150 })).toBe(true);
    expect(blocked({ x: 330, y: 150 })).toBe(false);
  });

  it('leaves the padded boundary itself open', () => {
    // The router derives its first and last route point *on* the boundary of a
    // padded end box. Counting that point as blocked fails the router's
    // accessibility check and drops the link to the fallback — a straight
    // diagonal, the one shape orthogonal routing exists to remove.
    const blocked = obstacleTest([card], 24);
    expect(blocked({ x: 324, y: 150 })).toBe(false);
    expect(blocked({ x: 200, y: 76 })).toBe(false);
  });

  it('lets a run pass straight through where no card was listed', () => {
    // Frames are the reason this function takes a list rather than reading the
    // graph: a frame is a background region, and routing round one would send
    // a run on a detour past a rectangle that is not there.
    const blocked = obstacleTest([], 24);
    expect(blocked({ x: 200, y: 150 })).toBe(false);
  });

  it('blocks a point inside any one of several cards', () => {
    const blocked = obstacleTest([card, { x: 500, y: 100, width: 100, height: 100 }], 0);
    expect(blocked({ x: 550, y: 150 })).toBe(true);
    expect(blocked({ x: 420, y: 150 })).toBe(false);
  });
});
