import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The instrument for `stable-beta-public/25`.
 *
 * The palette's first control is a search field, and it was drawn as a
 * *field in a strip*: `panel__header` contributed `var(--space-2)
 * var(--space-3)` of inset on all four sides, and the input drew its own
 * four-sided border inside that — so the box floated with 12px of surface
 * to its left, 39px to its right and 8px above it, and a reader saw two
 * horizontal lines (the input's own top edge, and the panel's) forty-five
 * pixels apart saying the same thing.
 *
 * The fix is that the header *is* the control: a `panel__header--flush`
 * modifier the palette opts into, which drops the header's inset and its
 * minimum height, and a `palette__search` modifier on the input which
 * reduces its four-sided border to the bottom hairline and moves the inset
 * inside the box, where it pads text instead of floating a box.
 *
 * **Why this reads CSS rather than a rendered box.** The numbers that
 * settle the ticket were measured in a real browser and written into it;
 * jsdom lays out nothing, so a `getBoundingClientRect` assertion here would
 * report zeros and pass whatever the stylesheet said. What a source-reading
 * pin *can* do is fail the day somebody restores one of the three
 * declarations that produced the float — which is the regression, the
 * measurement being the proof it is gone today.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const read = (relative: string): string => readFileSync(SRC + relative, 'utf8');

const PANEL_CSS = read('design/primitives/Panel.css');
const PANEL_TSX = read('design/primitives/Panel.tsx');
const PALETTE_CSS = read('view/palette/Palette.css');
const PALETTE_TSX = read('view/palette/Palette.tsx');

/** The declarations of the one rule whose selector is exactly `selector`. */
function block(css: string, selector: string): string {
  const noComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const at = noComments.indexOf(`\n${selector} {`);
  expect(at, `${selector} is declared`).toBeGreaterThanOrEqual(0);
  const open = noComments.indexOf('{', at);
  const close = noComments.indexOf('}', open);
  return noComments.slice(open + 1, close);
}

describe('the palette search field is the panel header, not a box inside it', () => {
  it('offers a flush header modifier that drops the inset entirely', () => {
    const flush = block(PANEL_CSS, '.panel__header--flush');
    expect(flush).toMatch(/padding:\s*0\s*;/);
    // 40px of minimum height is a strip a control sits *in*. The flush
    // header is the control, so its height is the control's height.
    expect(flush).toMatch(/min-height:\s*0\s*;/);
  });

  it('is opted into by the palette, and carries no rule above it', () => {
    expect(PANEL_TSX).toMatch(/flush\s*&&\s*'panel__header--flush'/);
    expect(PALETTE_TSX).toMatch(/<PanelHeader flush>/);
    // `bordered` would draw a second line under a control that already
    // draws one; the panel's own top edge is the boundary above.
    expect(PALETTE_TSX).not.toMatch(/<PanelHeader[^>]*bordered/);
    expect(PALETTE_TSX).toMatch(/className="palette__search"/);
  });

  it('reduces the field to a bottom hairline with the inset moved inside it', () => {
    const search = block(PALETTE_CSS, '.palette__search');
    // Edge to edge: a flex child that does not grow leaves the 39px gap
    // the ticket measured on the right.
    expect(search).toMatch(/flex:\s*1 1 auto\s*;/);
    expect(search).toMatch(/border:\s*0\s*;/);
    expect(search).toMatch(
      /border-bottom:\s*var\(--border-width-hairline\) solid var\(--color-border\)\s*;/,
    );
    expect(search).toMatch(/border-radius:\s*0\s*;/);
    expect(search).toMatch(/padding:\s*var\(--space-2\) var\(--space-3\)\s*;/);
  });
});
