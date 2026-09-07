import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The instrument for `install-experience` 29: the start panel rendered on the
 * blank canvas and could not be clicked.
 *
 * Measured before it was ruled on. `document.elementFromPoint` over the centre
 * of the *New workflow* button named the paper's own `<svg>` —
 * `position: absolute`, 748×771, `z-index: auto`, inside
 * `.canvas-surface` — and not the button. Nothing was hidden and nothing was
 * disabled; the paper was simply painted over the panel and took the pointer.
 *
 * **Why it was intermittent, which is why a number would not have fixed it.**
 * Both layers are `position: absolute` children of `.canvas-stage` and neither
 * declared a `z-index`, so paint order fell to DOM order — and DOM order here
 * depends on *when the canvas became empty*:
 *
 * - Empty on arrival (a reload, a fresh project): React renders
 *   `.canvas-empty` during the initial mount, and `PaperController` appends
 *   `.canvas-surface` afterwards from an effect. The paper is last, so the
 *   paper wins. **Dead panel.**
 * - Emptied while open (delete the last node): the surface is already there
 *   and React appends `.canvas-empty` after it. The panel is last, so the
 *   panel wins. **Working panel.**
 *
 * One document, two stacking orders, decided by insertion. The repair is to
 * say which layer is which, from the scale `tokens.css` already publishes
 * under "one ordered list, no magic numbers", so the answer no longer depends
 * on who mounted first. Raising a number until it happened to be big enough
 * would have left the same defect waiting for the next thing appended to the
 * stage.
 *
 * The older empty-state guidance was on this same element and was never
 * reported, because it is four spans of text and a glyph: `.canvas-empty` is
 * `pointer-events: none` so a drag falls through to the paper, and text that
 * nothing can click cannot report that nothing can click it. So this is a
 * latent defect the panel exposed, not a regression the panel introduced —
 * and `pointer-events` is the other half of reachability, checked below for
 * the same reason.
 */

const SRC = fileURLToPath(new URL('../', import.meta.url));
const read = (relative: string): string => readFileSync(SRC + relative, 'utf8');

const CANVAS_CSS = read('canvas/canvas.css');
const TOKENS_CSS = read('design/styles/tokens.css');
const START_PANEL_CSS = read('view/canvas/StartPanel.css');

/** The declaration block of a class selector, by exact selector text. */
function ruleFor(css: string, selector: string): string {
  const at = css.indexOf(`\n${selector} {`);
  expect(at, `no rule for ${selector}`).toBeGreaterThan(-1);
  const open = css.indexOf('{', at);
  const close = css.indexOf('}', open);
  return css.slice(open + 1, close);
}

/** The value of a declared property inside a block, `var()` and all. */
function declared(block: string, property: string): string | undefined {
  const match = new RegExp(`(?:^|;|\\n)\\s*${property}\\s*:\\s*([^;}]+)`).exec(block);
  return match?.[1]?.trim();
}

/** What a `--z-*` token resolves to in `tokens.css`. */
function layerValue(token: string): number {
  const match = new RegExp(`${token}\\s*:\\s*(-?\\d+)\\s*;`).exec(TOKENS_CSS);
  if (!match) throw new Error(`no ${token} in the z-index scale`);
  return Number(match[1]);
}

describe('the canvas stack is declared, not inherited from insertion order', () => {
  it('gives the paper the base canvas layer by name', () => {
    expect(declared(ruleFor(CANVAS_CSS, '.canvas-surface'), 'z-index')).toBe('var(--z-canvas)');
  });

  it('gives the empty state the canvas overlay layer, the one the band and the snaplines use', () => {
    expect(declared(ruleFor(CANVAS_CSS, '.canvas-empty'), 'z-index')).toBe(
      'var(--z-canvas-overlay)',
    );
    for (const overlay of ['.selection-band', '.snapline-layer']) {
      expect(declared(ruleFor(CANVAS_CSS, overlay), 'z-index')).toBe('var(--z-canvas-overlay)');
    }
  });

  it('orders the overlay above the paper in the scale itself', () => {
    expect(layerValue('--z-canvas-overlay')).toBeGreaterThan(layerValue('--z-canvas'));
  });

  it('keeps the empty state inert and the panel on it reachable', () => {
    // Both halves are load-bearing and they pull opposite ways: the guidance
    // must not swallow a drag aimed at the paper, and the panel must take the
    // click aimed at it. Losing either one puts the panel back where 29 found
    // it — visible, and dead.
    expect(declared(ruleFor(CANVAS_CSS, '.canvas-empty'), 'pointer-events')).toBe('none');
    expect(declared(ruleFor(START_PANEL_CSS, '.start-panel'), 'pointer-events')).toBe('auto');
  });
});
