import { describe, expect, it } from 'vitest';
import { MIN_CANVAS_WIDTH, PANEL_WIDTH, panelsMustOverlay, panelsWidth } from './panelFit';

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
