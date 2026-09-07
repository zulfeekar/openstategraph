import { describe, expect, it } from 'vitest';
import { coversAnyNode, type ScreenProjection } from './coverage';

/** A viewport panned by (dx, dy) at a given zoom, in the one direction this needs. */
const projection = (zoom: number, dx = 0, dy = 0): ScreenProjection => ({
  zoom,
  localToClient: (point) => ({ x: point.x * zoom + dx, y: point.y * zoom + dy }),
});

/** Where the map floats: bottom-right of a 1200×800 canvas. */
const MAP = { x: 1000, y: 640, width: 184, height: 144 };

describe('coversAnyNode', () => {
  it('is false with nothing on the canvas', () => {
    expect(coversAnyNode(MAP, [], projection(1))).toBe(false);
  });

  it('is false for a node nowhere near it', () => {
    const node = { x: 40, y: 40, width: 252, height: 120 };

    expect(coversAnyNode(MAP, [node], projection(1))).toBe(false);
  });

  it('is true for a card dropped underneath it — the reported case', () => {
    const node = { x: 1040, y: 680, width: 252, height: 120 };

    expect(coversAnyNode(MAP, [node], projection(1))).toBe(true);
  });

  it('follows the camera rather than the model', () => {
    // The same node, once panned under the map and once away from it. A rule
    // written in model coordinates would answer the same both times.
    const node = { x: 0, y: 0, width: 252, height: 120 };

    expect(coversAnyNode(MAP, [node], projection(1))).toBe(false);
    expect(coversAnyNode(MAP, [node], projection(1, 1020, 660))).toBe(true);
  });

  it('scales a node with the zoom', () => {
    // Small enough to clear the map at 1×, wide enough to reach it at 2×.
    const node = { x: 400, y: 260, width: 252, height: 120 };

    expect(coversAnyNode(MAP, [node], projection(1))).toBe(false);
    expect(coversAnyNode(MAP, [node], projection(2))).toBe(true);
  });

  it('answers false before the map has been measured', () => {
    expect(coversAnyNode(null, [{ x: 1040, y: 680, width: 252, height: 120 }], projection(1))).toBe(
      false,
    );
  });
});
