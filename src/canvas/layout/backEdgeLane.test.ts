import { describe, expect, it } from 'vitest';
import type { Rect } from '@core/kernel/geometry';
import { backEdgeLanes, isBackEdge, type LaneCandidate } from './backEdgeLane';

const rect = (x: number, y: number): Rect => ({ x, y, width: 200, height: 100 });

const forward: LaneCandidate = { edgeId: 'e:fwd', source: rect(0, 0), target: rect(400, 0) };
const back: LaneCandidate = { edgeId: 'e:back', source: rect(800, 0), target: rect(0, 0) };
const occupied = [rect(0, 0), rect(400, 0), rect(800, 0), rect(400, 300)];

describe('isBackEdge', () => {
  it('is true only when the target sits behind the source in the reading axis', () => {
    expect(isBackEdge(back, 'horizontal')).toBe(true);
    expect(isBackEdge(forward, 'horizontal')).toBe(false);
  });

  it('reads the other axis when the canvas is vertical', () => {
    const down: LaneCandidate = { edgeId: 'd', source: rect(0, 0), target: rect(0, 400) };
    expect(isBackEdge(down, 'vertical')).toBe(false);
    expect(isBackEdge({ ...down, source: rect(0, 400), target: rect(0, 0) }, 'vertical')).toBe(
      true,
    );
  });

  it('compares centres, so two cards that merely overlap are not a back-edge', () => {
    const overlapping: LaneCandidate = { edgeId: 'o', source: rect(0, 0), target: rect(40, 300) };
    expect(isBackEdge(overlapping, 'horizontal')).toBe(false);
  });
});

describe('backEdgeLanes', () => {
  it('leaves a forward link alone — it has no lane and needs none', () => {
    expect(backEdgeLanes([forward], occupied, 'horizontal', 90).has('e:fwd')).toBe(false);
  });

  it('puts a back-edge in a lane past the far side of everything', () => {
    const lanes = backEdgeLanes([forward, back], occupied, 'horizontal', 90);
    const points = lanes.get('e:back');
    expect(points).toHaveLength(2);
    const bottom = Math.max(...occupied.map((r) => r.y + r.height));
    // Below the lowest card — the shelf band between a card and its tools
    // belongs to the bindings, and a return run through it reads as if the
    // loop were somehow about the tools.
    for (const point of points ?? []) expect(point.y).toBeGreaterThan(bottom);
    // Both points share the lane, so the long leg *is* the lane.
    expect(points?.[0]?.y).toBe(points?.[1]?.y);
    // And it spans from beyond the source to just short of the target.
    expect(points?.[0]?.x).toBeGreaterThan(back.source.x + back.source.width);
    expect(points?.[1]?.x).toBeLessThan(back.target.x);
  });

  it('puts the lane beside the arrangement when the canvas is vertical', () => {
    const upward: LaneCandidate = { edgeId: 'u', source: rect(0, 800), target: rect(0, 0) };
    const points = backEdgeLanes([upward], occupied, 'vertical', 90).get('u');
    const right = Math.max(...occupied.map((r) => r.x + r.width));
    expect(points).toHaveLength(2);
    for (const point of points ?? []) expect(point.x).toBeGreaterThan(right);
    expect(points?.[0]?.x).toBe(points?.[1]?.x);
  });

  it('gives the longest back-edge the outermost lane, so two loops do not cross', () => {
    const long: LaneCandidate = { edgeId: 'long', source: rect(800, 0), target: rect(0, 0) };
    const short: LaneCandidate = { edgeId: 'short', source: rect(800, 0), target: rect(400, 0) };
    const lanes = backEdgeLanes([short, long], occupied, 'horizontal', 90);
    const longY = lanes.get('long')?.[0]?.y ?? 0;
    const shortY = lanes.get('short')?.[0]?.y ?? 0;
    expect(longY).toBeGreaterThan(shortY);
  });

  it('emits nothing when there is nothing to measure a lane against', () => {
    expect(backEdgeLanes([back], [], 'horizontal', 90).size).toBe(0);
    expect(backEdgeLanes([], occupied, 'horizontal', 90).size).toBe(0);
  });

  it('rounds every coordinate, so a waypoint is never a repeating decimal on disk', () => {
    const points = backEdgeLanes([back], occupied, 'horizontal', 95).get('e:back') ?? [];
    for (const point of points) {
      expect(Number.isInteger(point.x)).toBe(true);
      expect(Number.isInteger(point.y)).toBe(true);
    }
  });
});
