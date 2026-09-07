import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The chat column's top inset, pinned — `stable-beta-public/09`.
 *
 * `AskPanel.css` drew four spacings on the same column, each argued alone:
 * the thread's turn-to-turn gap (`--space-5`), a turn's own row gap
 * (`--space-3`), a bubble's padding (`--space-2 --space-3`), and the inset
 * above the very first turn — which came from nowhere written down, so it
 * measured 0. Measured live against the inspector panel beside it
 * (`.panel-section`'s own padding in `src/design/primitives/Panel.css`),
 * the room a reader expects above the first row of any panel body is
 * `--space-3` — the same token every panel already uses, not the larger
 * `--space-5` a reader might guess from "it is a gap in the thread".
 *
 * Read from source rather than rendered, the way `legendMatchesTheFold.test.ts`
 * reads this same directory's other components: the rhythm is a decision the
 * stylesheet made, not a rendering a browser has to reproduce to check.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const ASK_PANEL_CSS = read('./AskPanel.css');
const PANEL_CSS = read('../../design/primitives/Panel.css');

/** Pulls the padding-top a rule resolves to, tolerant of shorthand and
 *  longhand alike — `padding: a b c` (top is `a`) or `padding-top: a`. */
function paddingTop(css: string, selector: string): string {
  const rule = css.match(new RegExp(`${selector.replace(/[.[\]]/g, '\\$&')}\\s*\\{([^}]*)\\}`));
  const body = rule?.[1] ?? '';
  const longhand = body.match(/padding-top:\s*([^;]+);/);
  if (longhand) return (longhand[1] ?? '').trim();
  const shorthand = body.match(/padding:\s*([^;]+);/);
  if (!shorthand) return '';
  const parts = (shorthand[1] ?? '').trim().split(/\s+/);
  // CSS shorthand: 1 value = all sides, 2 = v/h, 3 = top/h/bottom, 4 = t/r/b/l.
  return parts[0] ?? '';
}

/** Pulls the `gap` a rule declares, same tolerance as `paddingTop` above. */
function gapOf(css: string, selector: string): string {
  const rule = css.match(new RegExp(`${selector.replace(/[.[\]]/g, '\\$&')}\\s*\\{([^}]*)\\}`));
  const body = rule?.[1] ?? '';
  const match = body.match(/gap:\s*([^;]+);/);
  return (match?.[1] ?? '').trim();
}

describe('the chat thread opens with the same inset every panel body opens with', () => {
  it("`.ask .panel__body`'s top inset is the panel-section canonical inset, not the turn-to-turn gap", () => {
    const askTop = paddingTop(ASK_PANEL_CSS, '.ask .panel__body');
    const sectionTop = paddingTop(PANEL_CSS, '.panel-section');

    expect(askTop).not.toBe('');
    expect(sectionTop).not.toBe('');
    // The two panels' canonical insets resolve to the same token.
    expect(askTop).toBe(sectionTop);
    expect(askTop).toBe('var(--space-3)');
    // Explicitly not the thread's own turn-to-turn rhythm — a bigger gap
    // that answers a different question ("how far apart are two turns")
    // than the one the top inset answers ("how far from the chrome does
    // this column's content start").
    const threadGap = gapOf(ASK_PANEL_CSS, '.ask__thread');
    expect(threadGap).toBe('var(--space-5)');
    expect(askTop).not.toBe(threadGap);
  });
});
