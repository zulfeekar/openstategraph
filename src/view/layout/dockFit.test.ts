import { describe, expect, it } from 'vitest';
import { LAYOUT } from '@design/tokens';
import {
  clampDockHeight,
  dockMaxHeight,
  DOCK_DEFAULT_HEIGHT,
  DOCK_MIN_HEIGHT,
  MIN_CANVAS_HEIGHT,
} from './dockFit';

/**
 * The height axis, which this shell has never had.
 *
 * `panelFit` adds up widths; `LAYOUT` carried exactly one height and nothing
 * could move it. `memory-and-replay` 51's dock is dragged, so for the first
 * time a gesture decides how tall the rest of the app is — and the whole of
 * the behaviour a user can feel at the ends of that drag is decidable here
 * rather than by dragging a browser and squinting.
 */
describe('the run dock’s height', () => {
  const TALL = 1000;

  it('gives the canvas its floor before it gives the dock anything', () => {
    // The mirror of `panelsMustOverlay`: the ceiling is what is left after the
    // top bar's row and the shortest canvas still worth calling one.
    expect(dockMaxHeight(TALL)).toBe(TALL - LAYOUT.topbarHeight - MIN_CANVAS_HEIGHT);
  });

  it('refuses to be dragged shorter than a dock', () => {
    // Not zero. Below the floor the drag has produced a strip that says
    // nothing, and the only way back is to find the same few pixels of edge
    // again. Closing it is a different gesture with a button and a shortcut.
    expect(clampDockHeight(0, TALL)).toBe(DOCK_MIN_HEIGHT);
    expect(clampDockHeight(-400, TALL)).toBe(DOCK_MIN_HEIGHT);
  });

  it('refuses to be dragged past the canvas’s floor', () => {
    expect(clampDockHeight(TALL, TALL)).toBe(dockMaxHeight(TALL));
  });

  it('leaves an ordinary drag exactly where it was put', () => {
    expect(clampDockHeight(312, TALL)).toBe(312);
    expect(clampDockHeight(DOCK_DEFAULT_HEIGHT, TALL)).toBe(DOCK_DEFAULT_HEIGHT);
  });

  it('lets the floor win over the ceiling on a window too short for both', () => {
    // A deliberate order, and the one case where the two rules disagree: a
    // dock squeezed below its floor is unreadable, and the canvas has pan and
    // zoom while the dock has neither.
    const short = LAYOUT.topbarHeight + MIN_CANVAS_HEIGHT;
    expect(dockMaxHeight(short)).toBe(DOCK_MIN_HEIGHT);
    expect(clampDockHeight(400, short)).toBe(DOCK_MIN_HEIGHT);
  });

  it('answers a nonsense request with the default rather than with NaN', () => {
    // A stored preference is a string somebody's browser handed back, and
    // `Number('')` is 0 while `Number('x')` is NaN. A height of NaN is a panel
    // with no height and no error.
    expect(clampDockHeight(Number.NaN, TALL)).toBe(DOCK_DEFAULT_HEIGHT);
    expect(clampDockHeight(Number.POSITIVE_INFINITY, TALL)).toBe(DOCK_DEFAULT_HEIGHT);
  });

  it('rounds, because a fractional height is a hairline seam on every repaint', () => {
    expect(clampDockHeight(260.4, TALL)).toBe(260);
  });
});
