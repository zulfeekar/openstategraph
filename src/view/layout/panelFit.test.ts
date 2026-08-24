import { describe, expect, it } from 'vitest';
import {
  leftOverlayWidth,
  MIN_CANVAS_WIDTH,
  PANEL_WIDTH,
  panelsMustOverlay,
  panelsWidth,
  rightOverlayWidth,
} from './panelFit';

describe('panelsMustOverlay', () => {
  it('leaves a wide window alone with everything open', () => {
    expect(
      panelsMustOverlay(1920, { palette: true, ask: true, inspector: true, workflows: true }),
    ).toBe(false);
  });

  it('overlays the four-panel case at 1280 — the defect this exists for', () => {
    // Palette 232 + ask 300 + inspector 300 + drawer 320 = 1152, leaving 128px
    // of canvas on a normal laptop. Nothing collapsed and nothing warned.
    expect(
      panelsMustOverlay(1280, { palette: true, ask: true, inspector: true, workflows: true }),
    ).toBe(true);
  });

  it('keeps the ordinary two-panel layout in the row at 1280', () => {
    // The reason this is arithmetic and not a lower breakpoint: palette plus
    // inspector is what most sessions look like, and overlaying *those* at
    // 1280 would be a regression dressed as a fix.
    expect(panelsMustOverlay(1280, { palette: true, inspector: true })).toBe(false);
  });

  it('puts the panels back in the row when one of them closes', () => {
    const open = { palette: true, ask: true, inspector: true, workflows: true };

    expect(panelsMustOverlay(1440, open)).toBe(true);
    expect(panelsMustOverlay(1440, { ...open, workflows: false })).toBe(false);
  });

  it('overlays a narrow window even with a single panel', () => {
    expect(panelsMustOverlay(600, { inspector: true })).toBe(true);
  });

  it('counts nothing when nothing is open', () => {
    expect(panelsWidth({})).toBe(0);
    expect(panelsMustOverlay(MIN_CANVAS_WIDTH, {})).toBe(false);
  });

  it('is exactly the boundary it claims — one pixel decides it', () => {
    const width = PANEL_WIDTH.palette + PANEL_WIDTH.inspector + MIN_CANVAS_WIDTH;

    expect(panelsMustOverlay(width, { palette: true, inspector: true })).toBe(false);
    expect(panelsMustOverlay(width - 1, { palette: true, inspector: true })).toBe(true);
  });
});

describe('rightOverlayWidth', () => {
  // production-ready 76: when the row has room, Ask/Inspector are flex
  // siblings of the canvas, which is already narrower by their width — the
  // canvas element owes nothing more.
  it('is zero when the row has room, regardless of what is open', () => {
    expect(rightOverlayWidth(false, { ask: true, inspector: true })).toBe(0);
    expect(rightOverlayWidth(false, {})).toBe(0);
  });

  it('is zero while overlaying if neither right-hand panel is open', () => {
    expect(rightOverlayWidth(true, {})).toBe(0);
  });

  it('is one panel width while overlaying with just the inspector open', () => {
    expect(rightOverlayWidth(true, { inspector: true })).toBe(PANEL_WIDTH.inspector);
  });

  it('is one panel width while overlaying with just ask open', () => {
    expect(rightOverlayWidth(true, { ask: true })).toBe(PANEL_WIDTH.ask);
  });

  it('sums both while overlaying with ask and inspector both open', () => {
    expect(rightOverlayWidth(true, { ask: true, inspector: true })).toBe(
      PANEL_WIDTH.ask + PANEL_WIDTH.inspector,
    );
  });
});

describe('leftOverlayWidth', () => {
  // launch-readiness 39: the palette is a left panel exactly like Ask and
  // Inspector are right panels — when the row cannot hold it, it floats over
  // the canvas at `left: 0` too (AppShell.css `[data-overlay] > .panel--left`),
  // and the empty-state copy needs to know how much of the left edge that
  // covers, the same way `rightOverlayWidth` already tells it about the right.
  it('is zero when the row has room, regardless of what is open', () => {
    expect(leftOverlayWidth(false, { palette: true, workflows: true })).toBe(0);
    expect(leftOverlayWidth(false, {})).toBe(0);
  });

  it('is zero while overlaying if neither left-hand panel is open', () => {
    expect(leftOverlayWidth(true, {})).toBe(0);
  });

  it('is one panel width while overlaying with just the palette open', () => {
    expect(leftOverlayWidth(true, { palette: true })).toBe(PANEL_WIDTH.palette);
  });

  it('is one panel width while overlaying with just the workflows drawer open', () => {
    expect(leftOverlayWidth(true, { workflows: true })).toBe(PANEL_WIDTH.workflows);
  });

  it('sums both while overlaying with the palette and the drawer both open', () => {
    // They stand side by side (AppShell.css: the drawer sits at
    // `left: var(--layout-palette-width)` when the palette is also open),
    // so together they cover the sum, not just the wider of the two.
    expect(leftOverlayWidth(true, { palette: true, workflows: true })).toBe(
      PANEL_WIDTH.palette + PANEL_WIDTH.workflows,
    );
  });
});
