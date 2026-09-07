import { describe, expect, it } from 'vitest';
import { placeFloating } from './useFloating';

/**
 * The positioning maths behind every tooltip, menu and popover.
 *
 * Extracted from the hook so it can be tested at all: it is arithmetic over
 * four rectangles, it lives in `design/` which holds no app logic, and until
 * now the only way to exercise it was to open a menu in a browser and look.
 *
 * The defect that prompted this (canvas-feels-right ticket 02), measured live
 * at a 690x998 viewport with the canvas panned:
 *
 *     trigger.right  736      <- the anchor was OUTSIDE the viewport
 *     menu           x=1, y=-2, 173x110
 *                         ^^^^ clipped off the top of the screen
 *
 * Two causes, and the hook's own docstring named the first as an assumption it
 * was allowed to make: *"the app only ever anchors to elements already inside
 * the viewport"*. The canvas pans and zooms, so that was never true.
 */
const viewport = { width: 1000, height: 800 };
const anchor = (x: number, y: number, width = 40, height = 20) => ({
  left: x,
  top: y,
  right: x + width,
  bottom: y + height,
  width,
  height,
});

describe('placing a floating element', () => {
  it('sits below its anchor when there is room', () => {
    const at = placeFloating(anchor(400, 300), { width: 160, height: 100 }, viewport, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    expect(at.placement).toBe('bottom');
    expect(at.y).toBe(326); // anchor.bottom + offset
    expect(at.x).toBe(340); // centred: 400 + (40 - 160) / 2
  });

  it('flips above when there is no room below', () => {
    const at = placeFloating(anchor(400, 760), { width: 160, height: 100 }, viewport, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    expect(at.placement).toBe('top');
    expect(at.y).toBe(654); // anchor.top - height - offset
  });
});

describe('an anchor outside the viewport', () => {
  /**
   * The canvas pans, so a node card — and the menu trigger on it — is
   * routinely off-screen. The popup must still land somewhere a person can
   * read it, because it is *their* popup: they opened it.
   */
  it('keeps the popup on screen when the anchor is off the right edge', () => {
    const at = placeFloating(anchor(1200, 300), { width: 173, height: 110 }, viewport, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    expect(at.x).toBeGreaterThanOrEqual(8);
    expect(at.x + 173).toBeLessThanOrEqual(1000 - 8);
  });

  it('keeps the popup on screen when the anchor is above the top edge', () => {
    // The exact reproduction: this returned y = -2.
    const at = placeFloating(anchor(700, -60), { width: 173, height: 110 }, viewport, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    expect(at.y).toBeGreaterThanOrEqual(8);
  });

  it('keeps the popup on screen when the anchor is far below', () => {
    const at = placeFloating(anchor(400, 2000), { width: 160, height: 100 }, viewport, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    expect(at.y).toBeGreaterThanOrEqual(8);
    expect(at.y + 100).toBeLessThanOrEqual(800 - 8);
  });
});

describe('a floating element bigger than the window', () => {
  /**
   * The subtle half, and the one that would have come back after the anchor
   * case was fixed. The old clamp was
   *
   *     Math.min(Math.max(v, padding), window.innerHeight - height - padding)
   *
   * which is a clamp only while `padding <= innerHeight - height - padding`.
   * A long menu, a short window, or a measurement taken before layout (when
   * `offsetHeight` is still 0 or wrong) inverts the bounds — `Math.min` wins,
   * and the result is *less than padding*: negative, off-screen. The guard
   * written to prevent clipping was the thing producing it.
   */
  it('pins to the top-left padding rather than going negative', () => {
    const at = placeFloating(anchor(400, 300), { width: 2000, height: 1200 }, viewport, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    // It cannot fit. It must still start on screen, so the first item is
    // reachable and the rest can scroll — never begin off the top or left.
    expect(at.x).toBe(8);
    expect(at.y).toBe(8);
  });

  it('is exactly at the padding when it fills the window precisely', () => {
    const at = placeFloating(anchor(400, 300), { width: 984, height: 784 }, viewport, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    expect(at.x).toBe(8);
    expect(at.y).toBe(8);
  });
});

/**
 * The box, and what happens when it is not the window.
 *
 * `launch-readiness` 189 with `memory-and-replay` 51. The Workflows list is a
 * popover anchored to a top-bar button, and the run dock is a sibling of the
 * stage that button sits in — so opening or dragging the dock takes height out
 * of the stage while the window's size does not change and no `resize` event
 * fires anywhere. A popover clamped to the window would hang over the
 * timeline, silently, and nothing in the DOM would ever say so.
 *
 * `placeFloating` already took the box as data, which is why the fix is a
 * shorter rectangle here rather than a second positioner somewhere else.
 */
describe('a floating surface bounded by something smaller than the window', () => {
  /** The stage with a 300px dock under it, in a 1000x800 window. */
  const stage = { width: 1000, height: 500 };

  it('fits inside the stage rather than over the panel below it', () => {
    const at = placeFloating(anchor(480, 20), { width: 320, height: 600 }, stage, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    // Taller than the room it has, so it starts at the padding and scrolls —
    // never at `anchor.bottom`, which would put six hundred pixels of list
    // across a timeline the user is watching.
    expect(at.y).toBe(8);
  });

  it('still hangs off its trigger when the stage has room', () => {
    const at = placeFloating(anchor(480, 20), { width: 320, height: 200 }, stage, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    expect(at.y).toBe(46);
    // Centred: 480 + 40/2 - 320/2.
    expect(at.x).toBe(340);
  });

  it('lets fitting beat centring when the trigger is near an edge', () => {
    // The case the top bar actually produces: the bar wraps and reflows, so
    // the Workflows button genuinely does travel to within half a popover of
    // both edges. Centring is a preference — it says *this came from that
    // button* — and fitting is a requirement, so the centre is computed first
    // and then clamped.
    const at = placeFloating(anchor(960, 20), { width: 320, height: 200 }, stage, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    expect(at.x).toBe(stage.width - 320 - 8);
  });

  it('keeps the head of an over-wide popover rather than centring the overflow', () => {
    // A list is read from its left edge, so what overflows should be its tail.
    const narrow = { width: 300, height: 500 };
    const at = placeFloating(anchor(150, 20), { width: 320, height: 200 }, narrow, {
      placement: 'bottom',
      align: 'center',
      offset: 6,
      padding: 8,
    });

    expect(at.x).toBe(8);
  });
});
