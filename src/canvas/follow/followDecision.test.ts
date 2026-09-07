import { describe, expect, it } from 'vitest';
import type { Rect, Size } from '@core/kernel/geometry';
import { decideFollow, type FollowInput } from './followDecision';

/** 1000×700 of model space visible at 1:1, with the usual comfort settings. */
const base: Omit<FollowInput, 'targets'> = {
  viewport: { x: 0, y: 0, width: 1000, height: 700 },
  zoom: 1,
  margin: 0.12,
  padding: 80,
  minZoom: 0.25,
  maxZoom: 2.5,
  focusFill: 0.42,
  focusMaxZoom: 1.25,
};

const node = (x: number, y: number): Rect => ({ x, y, width: 252, height: 160 });

describe('decideFollow', () => {
  it('does nothing when nothing is running', () => {
    expect(decideFollow({ ...base, targets: [] })).toEqual({ kind: 'stay' });
  });

  it('does nothing when the active node is already comfortably on screen', () => {
    // Dead centre and readable — the case that would otherwise re-issue a
    // transform on every streamed frame.
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
    expect(decision.kind).toBe('focus');
  });

  it('keeps the zoom the user chose when the node is already a readable size', () => {
    const decision = decideFollow({ ...base, targets: [node(2400, 1800)] });
    expect(decision).toEqual({ kind: 'focus', center: node(2400, 1800), zoom: 1 });
  });

  it('zooms IN toward the target size when the active node is small on screen', () => {
    // At zoom 0.4 the 1000×700 model rect is 400×280 css px, so the card is
    // ~100 px wide — legible only as a coloured box. Target: 42% of the
    // viewport width → 400 × 0.42 / 252.
    const decision = decideFollow({ ...base, zoom: 0.4, targets: [node(4000, 4000)] });
    expect(decision.kind).toBe('focus');
    if (decision.kind !== 'focus') return;
    expect(decision.zoom).toBeCloseTo((400 * 0.42) / 252, 5);
    expect(decision.zoom).toBeGreaterThan(0.4);
  });

  it('never zooms past the readable ceiling, however small the card is', () => {
    // A card 12 model units wide would want an enormous scale to fill 42%.
    const decision = decideFollow({
      ...base,
      zoom: 0.3,
      targets: [{ x: 5000, y: 5000, width: 12, height: 8 }],
    });
    expect(decision.kind).toBe('focus');
    if (decision.kind !== 'focus') return;
    expect(decision.zoom).toBe(1.25);
  });

  it('honours a maxZoom lower than the follow ceiling', () => {
    const decision = decideFollow({
      ...base,
      zoom: 0.3,
      maxZoom: 0.9,
      targets: [{ x: 5000, y: 5000, width: 12, height: 8 }],
    });
    expect(decision.kind).toBe('focus');
    if (decision.kind !== 'focus') return;
    expect(decision.zoom).toBe(0.9);
  });

  it('does not re-zoom a node that is merely a little smaller than ideal', () => {
    // The dead band: ideal here is the 1.25 ceiling, and zoom 1 is inside
    // 70% of it, so a node that is centred is left exactly alone. Without
    // this band the camera would chase the ideal scale forever.
    expect(decideFollow({ ...base, zoom: 1, targets: [node(400, 270)] })).toEqual({ kind: 'stay' });
  });

  it('settles: focusing once leaves a decision that says stay', () => {
    // Feed the focus decision back in as the new camera and assert the
    // second pass is a no-op. This is the real anti-jitter guarantee — a
    // deadband that does not contain its own target still oscillates.
    const first = decideFollow({ ...base, zoom: 0.4, targets: [node(4000, 4000)] });
    if (first.kind !== 'focus') throw new Error('expected focus');
    const settled = decideFollow({
      ...base,
      zoom: first.zoom,
      viewport: centeredOn(first.center, 1000 * 0.4, 700 * 0.4, first.zoom),
      targets: [node(4000, 4000)],
    });
    expect(settled).toEqual({ kind: 'stay' });
  });

  it('pulls back when a single node is bigger than the screen', () => {
    const decision = decideFollow({
      ...base,
      zoom: 2,
      targets: [{ x: 0, y: 0, width: 4000, height: 3000 }],
    });
    expect(decision.kind).toBe('focus');
    if (decision.kind !== 'focus') return;
    expect(decision.zoom).toBeLessThan(2);
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

  it('never zooms IN on a fan-out — several nodes keep their context', () => {
    // Two small nodes side by side at a wide zoom-out: fitting them would
    // magnify, so the answer is a move at the zoom the user already has.
    const decision = decideFollow({
      ...base,
      zoom: 0.5,
      targets: [node(4000, 4000), node(4400, 4000)],
    });
    expect(decision.kind).toBe('fit');
    if (decision.kind !== 'fit') return;
    expect(decision.zoom).toBe(0.5);
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

  it('survives a degenerate target rather than dividing by its zero width', () => {
    const decision = decideFollow({
      ...base,
      targets: [{ x: 4000, y: 4000, width: 0, height: 0 }],
    });
    expect(decision.kind).toBe('focus');
    if (decision.kind !== 'focus') return;
    expect(Number.isFinite(decision.zoom)).toBe(true);
    expect(decision.zoom).toBeLessThanOrEqual(1.25);
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
    expect(away.kind).toBe('focus');
  });
});

/**
 * The bug the owner reported, at the sizes it was reported at.
 *
 * Every rect here was measured off the running editor with `getBBox()` on the
 * shipped `chinook-assistant` document, not derived from `NODE.width`: the
 * card bbox includes port dots and grew ports, and the whole point of the
 * regression is that a *real* card is much taller than a nominal one.
 */
describe('decideFollow · the shipped Chinook cards', () => {
  /** The editor's canvas area at 1280×1000 with both side panels open. */
  const canvas = { width: 768, height: 952 };

  /** Measured 2026-08-11 in the running editor. Height is content, width is not. */
  const CARDS = {
    'Intent (router, 5 branches)': { width: 288, height: 1068 },
    'Verified? (grader)': { width: 300, height: 630 },
    'Front Desk (agent)': { width: 300, height: 428 },
    'Data Analyst (agent)': { width: 300, height: 389 },
    'SQL Analyst skill': { width: 262, height: 376 },
    'Question (input)': { width: 262, height: 220 },
    'Execute SQL Query (tool)': { width: 252, height: 149 },
    'Web Search (tool)': { width: 252, height: 100 },
  } as const;

  /**
   * The camera parked far away, so the answer is always a real decision.
   *
   * `Size`, not `Rect`: `CARDS` records measured widths and heights and the
   * position is supplied here, so asking for a `Rect` asked callers for two
   * coordinates this helper immediately overwrites.
   */
  const away = (card: Size, zoom: number): FollowInput => ({
    ...base,
    zoom,
    viewport: { x: 0, y: 0, width: canvas.width / zoom, height: canvas.height / zoom },
    targets: [{ x: 9000, y: 9000, width: card.width, height: card.height }],
  });

  it('brings every card, tallest included, to a scale a reader can act on', () => {
    // Before this rule the height term put the router at 0.37 while its
    // neighbours got 1.03–1.25 — the reported defect, in one number.
    for (const [name, card] of Object.entries(CARDS)) {
      const decision = decideFollow(away(card, 0.25));
      expect(decision.kind, name).toBe('focus');
      if (decision.kind !== 'focus') continue;
      expect(decision.zoom, name).toBeGreaterThan(1);
    }
  });

  it('follows the tallest card at very nearly the same scale as the shortest', () => {
    const zoomOf = (card: Size) => {
      const decision = decideFollow(away(card, 0.25));
      return decision.kind === 'focus' ? decision.zoom : NaN;
    };
    // Width is fixed by design, so a width rule makes the run's framing
    // *uniform*: nothing is singled out for being informative.
    const zooms = Object.values(CARDS).map(zoomOf);
    expect(Math.min(...zooms) / Math.max(...zooms)).toBeGreaterThan(0.85);
  });

  it('never zooms OUT on the router at the zoom the editor opens at', () => {
    // The other half of the same defect: at 1:1 the old rule pulled back to
    // 0.37 to fit 1068 units of card on screen.
    const decision = decideFollow(away(CARDS['Intent (router, 5 branches)'], 1));
    expect(decision.kind).toBe('focus');
    if (decision.kind !== 'focus') return;
    expect(decision.zoom).toBe(1);
  });

  it('frames a card too tall to show whole from its top, not its middle', () => {
    const router = { x: 9000, y: 9000, ...CARDS['Intent (router, 5 branches)'] };
    const decision = decideFollow(away(CARDS['Intent (router, 5 branches)'], 0.25));
    expect(decision.kind).toBe('focus');
    if (decision.kind !== 'focus') return;
    // The header, the name and the running dot are at the top of the card.
    expect(decision.center.y).toBe(router.y);
    expect(decision.center.height).toBeLessThan(router.height);
    expect(decision.center.height).toBeGreaterThan(0);
  });

  it('settles on the router: framing it once leaves a decision that says stay', () => {
    const card = CARDS['Intent (router, 5 branches)'];
    const first = decideFollow(away(card, 0.25));
    if (first.kind !== 'focus') throw new Error('expected focus');
    const settled = decideFollow({
      ...base,
      zoom: first.zoom,
      viewport: centeredOn(first.center, canvas.width, canvas.height, first.zoom),
      targets: [{ x: 9000, y: 9000, width: card.width, height: card.height }],
    });
    expect(settled).toEqual({ kind: 'stay' });
  });

  it('does not move the camera for a router already framed at 1:1', () => {
    // The invariant the dead band exists for, checked on the card that used
    // to break it: a run starting already framed must not twitch.
    const card = CARDS['Intent (router, 5 branches)'];
    const target = { x: 9000, y: 9000, width: card.width, height: card.height };
    const framed = decideFollow({
      ...base,
      zoom: 1,
      viewport: { x: 0, y: 0, width: canvas.width, height: canvas.height },
      targets: [target],
    });
    if (framed.kind !== 'focus') throw new Error('expected focus');
    expect(
      decideFollow({
        ...base,
        zoom: 1,
        viewport: centeredOn(framed.center, canvas.width, canvas.height, 1),
        targets: [target],
      }),
    ).toEqual({ kind: 'stay' });
  });

  it('still pulls back for a fan-out of shipped cards, zooming out only', () => {
    const row = [0, 1400, 2800].map((x) => ({ x, y: 0, ...CARDS['Data Analyst (agent)'] }));
    const decision = decideFollow({
      ...base,
      viewport: { x: 0, y: 0, width: canvas.width, height: canvas.height },
      targets: row,
    });
    expect(decision.kind).toBe('fit');
    if (decision.kind !== 'fit') return;
    expect(decision.zoom).toBeLessThan(1);
  });
});

/** The model-space rect visible when `zoom` frames `rect` in a screen of `w`×`h` css px. */
function centeredOn(rect: Rect, w: number, h: number, zoom: number): Rect {
  const width = w / zoom;
  const height = h / zoom;
  return {
    x: rect.x + rect.width / 2 - width / 2,
    y: rect.y + rect.height / 2 - height / 2,
    width,
    height,
  };
}
