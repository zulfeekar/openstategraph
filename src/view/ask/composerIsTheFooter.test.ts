import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The composer is the panel's footer, not a card floating inside the padded
 * body — `stable-beta-public/12`.
 *
 * Before this ticket `.ask__composer` was a child of `.ask .panel__body`,
 * which carries the column's canonical left/right inset (`09`). The inset
 * meant for the bubbles pushed the composer in from the edges too, and the
 * composer drew its own border, radius and shadow on top — a bordered card
 * with room on three sides, inside a chat column.
 *
 * Measured live before the fix (`getBoundingClientRect`, the chat panel open
 * beside the inspector, 300px wide): the composer sat 13px in from the
 * panel's left edge and 12px in from its right, both roughly the padded
 * body's `--space-3` inset plus the composer's own hairline border. Below it
 * the gap was already 0 — `.ask .panel__body` only ever padded the *top* and
 * sides (`09`), never the bottom — so the fix is horizontal, not vertical.
 *
 * The fix moves the composer out of `PanelBody` into `PanelFooter`
 * (`src/design/primitives/Panel.tsx`), a sibling of the padded body rather
 * than a child of it, so it inherits the panel's own edges instead of the
 * body's inset. `PanelFooter`'s own rule (`Panel.css` `.panel__footer`,
 * padding `--space-2-5 --space-3`) supplies the top hairline rule for free,
 * but not the exact padding this ticket asks for (`--space-2 --space-3`) —
 * so `.ask__composer` keeps declaring its own padding, at higher specificity
 * (`.panel__footer.ask__composer`) so it wins regardless of stylesheet order.
 * Said here rather than assumed: the footer's rule almost fit and did not
 * fully.
 *
 * Read from source rather than rendered, the way `verticalRhythm.test.ts`
 * and `chatBubblesAgree.test.ts` read this same directory's other components:
 * the shape is a decision the source made, not a rendering a browser has to
 * reproduce to check.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const ASK_PANEL_TSX = read('./AskPanel.tsx');
const ASK_PANEL_CSS = read('./AskPanel.css');

/** The body of one CSS rule, by selector — tolerant of the selector list this
 *  file writes rules under, and of `{`/`}` nested inside comments elsewhere in
 *  the file (which is why this only searches after the first index of the
 *  selector, not the whole file globally). */
function ruleBody(css: string, selector: string): string {
  const at = css.indexOf(selector);
  expect(at, `${selector} is declared in the file`).toBeGreaterThan(-1);
  const openBrace = css.indexOf('{', at);
  const closeBrace = css.indexOf('}', openBrace);
  return css.slice(openBrace + 1, closeBrace);
}

describe('the composer is the panel footer, not a card inside the padded body', () => {
  it('AskPanel.tsx renders the composer through PanelFooter, after PanelBody closes', () => {
    const bodyOpen = ASK_PANEL_TSX.indexOf('<PanelBody>');
    const bodyClose = ASK_PANEL_TSX.indexOf('</PanelBody>');
    const footerOpen = ASK_PANEL_TSX.indexOf('<PanelFooter');
    const composerClass = ASK_PANEL_TSX.indexOf('ask__composer');

    expect(bodyOpen, 'PanelBody is used').toBeGreaterThan(-1);
    expect(bodyClose, 'PanelBody is closed').toBeGreaterThan(bodyOpen);
    expect(footerOpen, 'PanelFooter is used').toBeGreaterThan(-1);

    // The composer is not inside PanelBody's children at all.
    const bodyChildren = ASK_PANEL_TSX.slice(bodyOpen, bodyClose);
    expect(bodyChildren, "PanelBody's children do not include the composer").not.toContain(
      'ask__composer',
    );

    // It is inside PanelFooter, which opens after PanelBody has closed.
    expect(footerOpen, 'PanelFooter opens after PanelBody closes').toBeGreaterThan(bodyClose);
    expect(composerClass, "the composer's class is on PanelFooter").toBeGreaterThan(footerOpen);
  });

  it('`.ask__composer` no longer draws its own card — no border, radius or shadow', () => {
    const rule = ruleBody(ASK_PANEL_CSS, '.ask__composer {');
    expect(rule, 'no own border').not.toMatch(/(?<!-)\bborder:/);
    expect(rule, 'no own border-radius').not.toMatch(/border-radius:/);
    expect(rule, 'no own box-shadow').not.toMatch(/box-shadow:/);
  });

  it('`.ask__composer` pads its own text away from the footer edges at `--space-2 --space-3`', () => {
    const rule = ruleBody(ASK_PANEL_CSS, '.ask__composer {');
    const match = rule.match(/padding:\s*([^;]+);/);
    expect(match?.[1]?.trim()).toBe('var(--space-2) var(--space-3)');
  });
});
