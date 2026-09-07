import { describe, expect, it, vi } from 'vitest';
import type { dia } from '@joint/core';
import { CANVAS } from '@design/tokens';
import { Viewport } from './Viewport';

/**
 * The camera had no tests at all.
 *
 * `Viewport` is 250 lines of coordinate arithmetic that every gesture on the
 * canvas depends on — dropping a node from the palette, anchoring a wheel
 * zoom, framing a run — and nothing exercised any of it
 * (reviews-2026-08-14 ticket 14). CLAUDE.md's rule is that a class over the
 * member ceiling is not refactored until tests are in place; this file is
 * that precondition, and it is also the honest basis for the ceiling
 * *exception* the class ends up carrying. Recording "we looked and decided to
 * keep it wide" is only worth something if looking involved running it.
 *
 * Testable without a DOM because the two collaborators are narrow: the paper
 * is asked only to `scale` and `translate`, and the container only for its
 * bounding rect. That narrowness is a property worth keeping — it is what
 * makes the camera arithmetic checkable at all.
 */
const paperStub = () => {
  const calls: { scale: [number, number][]; translate: [number, number][] } = {
    scale: [],
    translate: [],
  };
  const paper = {
    scale: (x: number, y: number) => calls.scale.push([x, y]),
    translate: (x: number, y: number) => calls.translate.push([x, y]),
  } as unknown as dia.Paper;
  return { paper, calls };
};

/** A container of a known size, offset from the page origin. */
const containerStub = (width = 800, height = 600, left = 40, top = 20) =>
  ({
    getBoundingClientRect: () => ({
      width,
      height,
      left,
      top,
      right: left + width,
      bottom: top + height,
    }),
  }) as unknown as HTMLElement;

const viewportOf = (width?: number, height?: number) => {
  const { paper, calls } = paperStub();
  return { viewport: new Viewport(paper, containerStub(width, height)), calls };
};

describe('where the camera is', () => {
  it('starts at the default zoom, unpanned', () => {
    const { viewport } = viewportOf();

    expect(viewport.zoom).toBe(CANVAS.zoom.default);
    expect(viewport.translate).toEqual({ x: 0, y: 0 });
  });

  it('hands out a copy of the translation, not the live one', () => {
    // A caller that mutates what it was given would move the camera without
    // the paper or any listener hearing about it.
    const { viewport } = viewportOf();

    const stolen = viewport.translate;
    stolen.x = 999;

    expect(viewport.translate.x).toBe(0);
  });

  it('reports the model rectangle currently visible', () => {
    const { viewport } = viewportOf(800, 600);

    viewport.panBy(-100, -50);

    // Panning the canvas by -100 moves the visible window +100 in model space.
    expect(viewport.visibleRect).toEqual({ x: 100, y: 50, width: 800, height: 600 });
  });
});

describe('converting between the screen and the model', () => {
  it('subtracts the container offset, so a drop lands where it was dropped', () => {
    // The container sits 40px from the left of the page; a client x of 140 is
    // 100px into the canvas. Getting this wrong is the palette-drop bug.
    const { viewport } = viewportOf();

    expect(viewport.clientToLocal(140, 120)).toEqual({ x: 100, y: 100 });
  });

  it('round-trips a point through both conversions', () => {
    const { viewport } = viewportOf();
    viewport.setZoom(1.7);
    viewport.panBy(-33, 71);

    const client = viewport.localToClient({ x: 420, y: 137 });
    const back = viewport.clientToLocal(client.x, client.y);

    expect(back.x).toBeCloseTo(420, 6);
    expect(back.y).toBeCloseTo(137, 6);
  });
});

describe('zooming', () => {
  it('keeps the point under the cursor pinned', () => {
    // The property that makes wheel-zoom feel like a camera rather than a
    // slider, and the one most likely to be broken by a refactor.
    const { viewport } = viewportOf();
    const anchor = { x: 300, y: 250 };
    const before = viewport.clientToLocal(anchor.x, anchor.y);

    viewport.setZoom(2.2, anchor);
    const after = viewport.clientToLocal(anchor.x, anchor.y);

    expect(after.x).toBeCloseTo(before.x, 6);
    expect(after.y).toBeCloseTo(before.y, 6);
  });

  it('centres the zoom when no anchor is given', () => {
    const { viewport } = viewportOf(800, 600);
    const centre = { x: 40 + 400, y: 20 + 300 };
    const before = viewport.clientToLocal(centre.x, centre.y);

    viewport.setZoom(0.5);

    const after = viewport.clientToLocal(centre.x, centre.y);
    expect(after.x).toBeCloseTo(before.x, 6);
    expect(after.y).toBeCloseTo(before.y, 6);
  });

  it('refuses to go past its limits', () => {
    const { viewport } = viewportOf();

    viewport.setZoom(9999);
    expect(viewport.zoom).toBe(CANVAS.zoom.max);

    viewport.setZoom(-5);
    expect(viewport.zoom).toBe(CANVAS.zoom.min);
  });

  it('steps multiplicatively, so a step feels the same at any scale', () => {
    // Additive steps crawl when zoomed out and lurch when zoomed in.
    const { viewport: a } = viewportOf();
    a.setZoom(0.4);
    const fromLow = a.zoom;
    a.zoomBy(0.25);
    const lowRatio = a.zoom / fromLow;

    const { viewport: b } = viewportOf();
    b.setZoom(1.6);
    const fromHigh = b.zoom;
    b.zoomBy(0.25);

    expect(b.zoom / fromHigh).toBeCloseTo(lowRatio, 6);
  });

  it('comes home on reset', () => {
    const { viewport } = viewportOf();
    viewport.setZoom(2);

    viewport.resetZoom();

    expect(viewport.zoom).toBe(CANVAS.zoom.default);
  });
});

describe('framing', () => {
  it('centres a rectangle without touching the zoom', () => {
    const { viewport } = viewportOf(800, 600);
    viewport.setZoom(1.5);
    const zoom = viewport.zoom;

    viewport.centerOn({ x: 200, y: 100, width: 100, height: 50 });

    expect(viewport.zoom).toBe(zoom);
    const visible = viewport.visibleRect;
    expect(visible.x + visible.width / 2).toBeCloseTo(250, 6);
    expect(visible.y + visible.height / 2).toBeCloseTo(125, 6);
  });

  it('never zooms past 1 to fill the screen with one small node', () => {
    // "Fit" should never look like a mistake.
    const { viewport } = viewportOf(800, 600);

    viewport.fit({ x: 0, y: 0, width: 10, height: 10 });

    expect(viewport.zoom).toBeLessThanOrEqual(1);
  });

  it('shows the whole rectangle it was asked to frame', () => {
    const { viewport } = viewportOf(800, 600);
    const rect = { x: -500, y: -200, width: 2000, height: 1400 };

    viewport.fit(rect);

    const visible = viewport.visibleRect;
    expect(visible.x).toBeLessThanOrEqual(rect.x);
    expect(visible.y).toBeLessThanOrEqual(rect.y);
    expect(visible.x + visible.width).toBeGreaterThanOrEqual(rect.x + rect.width);
    expect(visible.y + visible.height).toBeGreaterThanOrEqual(rect.y + rect.height);
  });

  it('goes home rather than dividing by zero on an empty graph', () => {
    const { viewport } = viewportOf();
    viewport.setZoom(2);
    viewport.panBy(300, 300);

    viewport.fit(null);

    expect(viewport.zoom).toBe(CANVAS.zoom.default);
    expect(viewport.translate).toEqual({ x: 0, y: 0 });
  });

  it('does nothing when the container has not been laid out yet', () => {
    // A zero-sized container is a mount that has not measured; framing into
    // it would produce NaN and poison every later conversion.
    const { viewport } = viewportOf(0, 0);

    viewport.fit({ x: 0, y: 0, width: 100, height: 100 });

    expect(Number.isFinite(viewport.zoom)).toBe(true);
    expect(Number.isFinite(viewport.translate.x)).toBe(true);
  });
});

describe('telling everyone else', () => {
  it('pushes the transform onto the paper', () => {
    const { viewport, calls } = viewportOf();

    viewport.setZoom(2);

    expect(calls.scale.at(-1)).toEqual([2, 2]);
    expect(calls.translate.length).toBeGreaterThan(0);
  });

  it('emits once per change, because every card re-measures on one', () => {
    const { viewport } = viewportOf();
    const heard = vi.fn();
    viewport.onChange(heard);

    viewport.panBy(10, 10);

    expect(heard).toHaveBeenCalledTimes(1);
  });

  it('stays quiet when nothing actually moved', () => {
    const { viewport } = viewportOf();
    const heard = vi.fn();
    viewport.onChange(heard);

    viewport.panBy(0, 0);
    viewport.setZoom(viewport.zoom);

    expect(heard).not.toHaveBeenCalled();
  });

  it('stops listening after dispose', () => {
    const { viewport } = viewportOf();
    const heard = vi.fn();
    viewport.onChange(heard);

    viewport.dispose();
    viewport.panBy(10, 10);

    expect(heard).not.toHaveBeenCalled();
  });
});

describe('gliding', () => {
  it('cuts straight to the destination when animation is unavailable', () => {
    // The node test environment has no `requestAnimationFrame`, which is the
    // same path `prefers-reduced-motion` takes: the destination is the point,
    // the travel is decoration.
    const { viewport } = viewportOf(800, 600);

    viewport.glideTo({ x: 100, y: 100, width: 200, height: 100 }, 1.25);

    expect(viewport.zoom).toBeCloseTo(1.25, 6);
    const visible = viewport.visibleRect;
    expect(visible.x + visible.width / 2).toBeCloseTo(200, 6);
    expect(visible.y + visible.height / 2).toBeCloseTo(150, 6);
  });

  it('stopping an idle camera is not an error', () => {
    const { viewport } = viewportOf();

    expect(() => viewport.stopGlide()).not.toThrow();
  });
});
