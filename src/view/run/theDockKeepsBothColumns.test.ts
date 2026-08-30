import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The chart and the payload column, side by side at every width —
 * `memory-and-replay` 67, and the row metrics of `68`.
 *
 * # Why one file for two tickets
 *
 * Because they are one failure seen twice. `67` is the payload column stacking
 * itself below a chart that already fills the dock; `68` is the lane block
 * stretching to fill whatever height it is given. Both are a **document**
 * layout applied to a region with a fixed height, and both were correct for
 * `51`'s bottom drawer and wrong the moment `63` docked the surface under the
 * top bar. A dock has a height budget. A document has a scrollbar.
 *
 * # Why the assertions are on the stylesheet
 *
 * Every number below is a number the design the owner authored states outright,
 * and the shipped value was measured off the live dock with `getComputedStyle`
 * before it was changed. A rendered assertion would need a DOM, a layout pass
 * and a viewport, and would then be checking the browser rather than the
 * decision — this repository's own reason for keeping every decidable part of
 * this surface out of the JSX.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const DOCK = read('./RunDock.css');

/** The value of one declaration inside the first rule matching `selector`. */
function declaration(selector: string, property: string): string | null {
  const at = DOCK.indexOf(`\n${selector} {`);
  if (at === -1) return null;
  const body = DOCK.slice(at, DOCK.indexOf('}', at));
  const found = new RegExp(`(?:^|;|\\{)\\s*${property}:\\s*([^;]+);`, 'm').exec(body);
  return found?.[1]?.trim() ?? null;
}

describe('the dock keeps both of its columns', () => {
  it('never stacks them, because a dock has a height budget and not a scrollbar', () => {
    // Driven to 880 px the old rule put two independent scrollers in one
    // 260 px box: the chart kept three of its five rows, the scrub rail landed
    // on top of the lanes, and the selected-step facts, the payload and the
    // trace were all below a fold with no scrollbar to reach them. That is the
    // owner's screenshot with no detail column in it — nothing was missing,
    // everything was underneath.
    expect(DOCK).not.toMatch(/@media[^{]*max-width[^{]*\{[^}]*\.run-dock__body/);
    expect(DOCK).not.toMatch(/\.run-dock__body\s*\{[^}]*flex-direction:\s*column/);
  });

  it('gives the payload column a floor, so narrowing is not the same as vanishing', () => {
    // A column that narrows to nothing is no better than one that stacks. The
    // chart is what gives, against this floor.
    expect(declaration('.run-dock__detail', 'min-width')).not.toBeNull();
  });
});

describe('the rows carry the design’s own numbers', () => {
  // Left column: read out of the artifact the owner authored. Right: measured
  // on the live dock before this ticket. The bar sits on the row's centre by
  // construction — 9 + 16 + 9 = 34 — which is the "one baseline" the owner
  // asked for and which 22/14/4 cannot produce at any offset.
  it('is a 34 px row carrying a 16 px bar on a 9 px offset', () => {
    expect(declaration('.rtl__lane', 'min-height')).toBe('34px');
    expect(declaration('.rtl__track', 'height')).toBe('34px');
    expect(declaration('.rtl__bar', 'height')).toBe('16px');
    expect(declaration('.rtl__bar', 'top')).toBe('9px');
  });

  it('heads them with a 26 px axis strip', () => {
    expect(declaration('.rtl__ticks', 'height')).toBe('26px');
  });

  it('ends the lane block with its last row instead of stretching to the dock', () => {
    // `flex: 1 1 auto` is why five rows sat at the top of a 128 px box inside
    // a 144 px chart inside a 206 px pane, with roughly two thirds of the
    // surface empty below the last one. The lanes may shrink and scroll; they
    // may not grow.
    expect(declaration('.rtl__lanes', 'flex')).toBe('0 1 auto');
  });

  it('keeps the hairline weight 64 settled, and does not take the design’s 2 px bars', () => {
    // The design is a standalone page with a 2 px rule system and no draggable
    // edge to distinguish. Here the owner's instruction was the opposite — one
    // border ink, darker only for the draggable — so a 2 px border on every bar
    // would re-introduce the second weight `64` removed, in the one place a
    // reader is asked to compare shapes.
    expect(declaration('.rtl__bar', 'border')).toContain('--border-width-hairline');
  });
});
