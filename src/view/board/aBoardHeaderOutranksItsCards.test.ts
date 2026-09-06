import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * `kanban-patrol/06`, and the failure it is copied from is
 * `install-experience/29`.
 *
 * There, the start panel rendered on the blank canvas and could not be
 * clicked. Both it and the paper were `position: absolute` children of one
 * stage and **neither declared a `z-index`**, so paint order fell to DOM
 * order — and DOM order depended on *when* the canvas became empty. Empty on
 * arrival: React mounts the panel, `PaperController` appends the paper from an
 * effect, the paper is last, the panel is dead. Emptied while open: the panel
 * is appended after the paper and works. One document, two stacking orders,
 * decided by insertion. It was caught by a **stylesheet test** and not by a
 * rendered mount, because the defect is a fact about two CSS rules.
 *
 * ## The same shape, inside this modal
 *
 * A column at 90% of the viewport scrolls, so its header is `position:
 * sticky` — which makes the header a **positioned** box sharing a stack with
 * the cards below it. Today the cards are `position: static` and the header
 * wins by the paint order in the spec. That is luck, not a decision: the first
 * card that takes `position: relative` — for a hover control, a menu, an
 * absolutely-placed dot — becomes positioned, sits later in DOM order, and
 * paints straight over the header. Intermittent, dependent on an incidental
 * fact about one card, exactly as `29` was.
 *
 * So both layers are named from the scale `tokens.css` publishes under *"one
 * ordered list, no magic numbers"*. The names are absolute-scale names spent
 * on a stack that is local to the dialog, and that is deliberate rather than
 * unnoticed: `.dialog-backdrop` is `position: fixed` with `z-index:
 * var(--z-modal)`, so it is a stacking context and nothing inside it competes
 * with anything outside. The alternative was a bare number, which is the thing
 * the scale exists to refuse.
 *
 * ## One half of this was already true, and is pinned anyway
 *
 * The ticket predicted this file would be *"red first by both `z-index`
 * lookups returning `undefined`"*. Only the board's two are. `.dialog-backdrop`
 * has carried `z-index: var(--z-modal)` since before this ticket, so the modal
 * already outranked the canvas paper — it was simply never measured, and an
 * unmeasured fact is one somebody removes while tidying.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const read = (relative: string): string => readFileSync(SRC + relative, 'utf8');

const BOARD_CSS = read('view/board/PatrolBoard.css');
const OVERLAYS_CSS = read('view/overlays/overlays.css');
const TOKENS_CSS = read('design/styles/tokens.css');
const CANVAS_CSS = read('canvas/canvas.css');

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

describe('the board’s stack is declared, not inherited from insertion order', () => {
  it('makes the column header sticky, which is what puts it in the cards’ stack', () => {
    // The premise. If the header ever stops being sticky the two assertions
    // below are about a question nobody is asking — a ratchet that matches
    // nothing guards nothing.
    expect(declared(ruleFor(BOARD_CSS, '.patrol-column__head'), 'position')).toBe('sticky');
  });

  it('gives the sticky header the panel layer by name', () => {
    expect(declared(ruleFor(BOARD_CSS, '.patrol-column__head'), 'z-index')).toBe('var(--z-panel)');
  });

  it('gives the card the base layer by name, rather than leaving it unpositioned by luck', () => {
    const card = ruleFor(BOARD_CSS, '.patrol-card');
    // Both halves matter. `z-index` on a static box does nothing, so the card
    // has to be positioned for the declaration to be the answer — which is
    // also the state `29` warns a later edit will arrive at anyway.
    expect(declared(card, 'position')).toBe('relative');
    expect(declared(card, 'z-index')).toBe('var(--z-canvas)');
  });

  it('orders the header above the card in the scale itself', () => {
    expect(layerValue('--z-panel')).toBeGreaterThan(layerValue('--z-canvas'));
  });
});

describe('the modal outranks the canvas it opens over', () => {
  it('puts the backdrop on the modal layer by name', () => {
    expect(declared(ruleFor(OVERLAYS_CSS, '.dialog-backdrop'), 'z-index')).toBe('var(--z-modal)');
  });

  it('orders that layer above both canvas layers, paper and overlay', () => {
    expect(layerValue('--z-modal')).toBeGreaterThan(layerValue('--z-canvas-overlay'));
    expect(layerValue('--z-canvas-overlay')).toBeGreaterThan(layerValue('--z-canvas'));
    // And the two canvas layers are still spent where `29` put them, so the
    // comparison above is about the real paper rather than two spare numbers.
    expect(declared(ruleFor(CANVAS_CSS, '.canvas-surface'), 'z-index')).toBe('var(--z-canvas)');
    expect(declared(ruleFor(CANVAS_CSS, '.canvas-empty'), 'z-index')).toBe(
      'var(--z-canvas-overlay)',
    );
  });

  it('leaves nothing in the board inert, because everything on it is meant to be reached', () => {
    // `29`'s other half was `pointer-events: none` on `.canvas-empty`, which
    // is right there — guidance must not swallow a drag aimed at the paper.
    // Nothing on this board is guidance over something else: the empty state
    // *is* the surface and it carries the patrol button. A `pointer-events:
    // none` here would be the `29` defect with the layers already correct.
    expect(BOARD_CSS).not.toContain('pointer-events: none');
  });
});
