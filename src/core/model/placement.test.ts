import { describe, expect, it } from 'vitest';
import { freePositionNear, PLACEMENT_STEP } from './placement';

/**
 * Where a node goes when the user did not point at a spot.
 *
 * A drag says where; a click does not, so the palette places at the centre of
 * what you are looking at. That part was already right. What was wrong is what
 * happened on the *second* click (canvas-feels-right ticket 01) — measured in
 * the browser, three clicks on Text Input:
 *
 *     node:input.text-1   x=314 y=501
 *     node:input.text-2   x=314 y=501
 *     node:input.text-3   x=314 y=501
 *
 * Three nodes, one visible card, and nothing said so. A user who clicks twice
 * because the first click "did nothing" has now silently made two nodes — and
 * the only way to discover the buried one is to drag the top one off it.
 *
 * The fix is a cascade, which is what every canvas app does and what paste
 * already ought to do: keep the requested spot when it is free, step away
 * diagonally when it is not.
 */
describe('finding a free spot', () => {
  it('keeps the requested point when nothing is there', () => {
    expect(freePositionNear({ x: 300, y: 200 }, [])).toEqual({ x: 300, y: 200 });
  });

  it('steps away when something already occupies it', () => {
    const at = freePositionNear({ x: 300, y: 200 }, [{ x: 300, y: 200 }]);

    expect(at).toEqual({ x: 300 + PLACEMENT_STEP, y: 200 + PLACEMENT_STEP });
  });

  it('keeps stepping while each new spot is taken', () => {
    // The three-click case, exactly.
    const taken = [
      { x: 300, y: 200 },
      { x: 300 + PLACEMENT_STEP, y: 200 + PLACEMENT_STEP },
    ];

    expect(freePositionNear({ x: 300, y: 200 }, taken)).toEqual({
      x: 300 + PLACEMENT_STEP * 2,
      y: 200 + PLACEMENT_STEP * 2,
    });
  });

  it('treats near-coincident as occupied, not just exact matches', () => {
    // Cards overlap when they are close, not only when they are identical —
    // a two-pixel gap hides a card just as thoroughly as none.
    const at = freePositionNear({ x: 300, y: 200 }, [{ x: 302, y: 199 }]);

    expect(at).not.toEqual({ x: 300, y: 200 });
  });

  it('ignores nodes that are genuinely elsewhere', () => {
    expect(freePositionNear({ x: 300, y: 200 }, [{ x: 900, y: 700 }])).toEqual({ x: 300, y: 200 });
  });

  it('gives up rather than looping forever on a crowded canvas', () => {
    // A pathological board where every cascade step is taken. Returning
    // *something* on the requested diagonal beats hanging the editor; the
    // node is still reachable and still undoable.
    const taken = Array.from({ length: 500 }, (_, i) => ({
      x: 300 + PLACEMENT_STEP * i,
      y: 200 + PLACEMENT_STEP * i,
    }));

    const at = freePositionNear({ x: 300, y: 200 }, taken);

    expect(Number.isFinite(at.x)).toBe(true);
    expect(Number.isFinite(at.y)).toBe(true);
  });
});
