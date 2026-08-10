import { describe, expect, it } from 'vitest';
import type { Rect } from '@core/kernel/geometry';
import { decideFollow, type FollowInput } from './followDecision';

/** 1000×700 of model space visible at 1:1, with the usual comfort settings. */
const base: Omit<FollowInput, 'targets'> = {
  viewport: { x: 0, y: 0, width: 1000, height: 700 },
  zoom: 1,
  margin: 0.12,
  padding: 80,
  minZoom: 0.25,
  maxZoom: 2.5,
};

const node = (x: number, y: number): Rect => ({ x, y, width: 252, height: 160 });

describe('decideFollow', () => {
  it('does nothing when nothing is running', () => {
    expect(decideFollow({ ...base, targets: [] })).toEqual({ kind: 'stay' });
  });

  it('does nothing when the active node is already comfortably on screen', () => {
    // Dead centre — the case that would otherwise re-issue a transform on
    // every streamed frame.
    expect(decideFollow({ ...base, targets: [node(400, 270)] })).toEqual({ kind: 'stay' });
  });

  it('still does nothing for a node inside the viewport but near its edge', () => {
    // Inside the 12% comfort inset (x from 120 to 880): 500..752 qualifies.
    expect(decideFollow({ ...base, targets: [node(500, 400)] })).toEqual({ kind: 'stay' });
  });

  it('moves once the node crosses into the margin, before it is actually clipped', () => {
    // Fully visible (ends at x = 962 < 1000) but inside the margin band, so
    // the camera acts *before* the node is half off screen.
    const decision = decideFollow({ ...base, targets: [node(710, 270)] });
    expect(decision.kind).toBe('pan');
  });

  it('pans without touching zoom when one node is off screen', () => {
    const decision = decideFollow({ ...base, targets: [node(2400, 1800)] });
    expect(decision).toEqual({ kind: 'pan', center: node(2400, 1800) });
  });

  it('never zooms in on a single node — context must survive', () => {
    const decision = decideFollow({ ...base, zoom: 0.4, targets: [node(4000, 4000)] });
    expect(decision.kind).toBe('pan');
  });

  it('zooms out to fit a fan-out that does not fit at the current zoom', () => {
    const targets = [node(0, 0), node(1800, 0), node(3600, 0)];
    const decision = decideFollow({ ...base, targets });
    expect(decision.kind).toBe('fit');
    if (decision.kind !== 'fit') return;
    // Union spans 3852 wide; padded 4012 into 1000 → about 0.249, floored.
    expect(decision.zoom).toBeLessThan(1);
    expect(decision.center).toEqual({ x: 0, y: 0, width: 3852, height: 160 });
  });

  it('frames all of the active nodes, not just the first', () => {
    const decision = decideFollow({ ...base, targets: [node(0, 0), node(400, 900)] });
    expect(decision).toMatchObject({ center: { x: 0, y: 0, width: 652, height: 1060 } });
  });

  it('never zooms below the readable floor, even if that means not fitting', () => {
    const wide = [node(0, 0), node(100000, 0)];
    const decision = decideFollow({ ...base, targets: wide, minZoom: 0.25 });
    expect(decision.kind).toBe('fit');
    if (decision.kind !== 'fit') return;
    expect(decision.zoom).toBe(0.25);
  });

  it('treats a zero-sized viewport as "not yet laid out" rather than dividing by it', () => {
    const decision = decideFollow({
      ...base,
      viewport: { x: 0, y: 0, width: 0, height: 0 },
      targets: [node(10, 10)],
    });
    expect(decision).toEqual({ kind: 'stay' });
  });

  it('respects the viewport’s own origin, not just its size', () => {
    // The same node, once with the camera parked over it and once away.
    const here = decideFollow({
      ...base,
      viewport: { x: 2000, y: 1500, width: 1000, height: 700 },
      targets: [node(2400, 1770)],
    });
    const away = decideFollow({ ...base, targets: [node(2400, 1770)] });
    expect(here.kind).toBe('stay');
    expect(away.kind).toBe('pan');
  });
});
