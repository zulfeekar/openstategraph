import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

/**
 * `the-look-has-an-author-now` — a mount card reported with a screenshot:
 * the card's border ended around x=290, and **Open this mount** plus "this
 * mount only, others unaffected" rendered at x=700–880, several hundred
 * pixels outside it. The census line was squeezed to roughly one word per
 * line.
 *
 * The cause: `.node__composition-open-group` (`CompositionBody.css`) is
 * `flex: none` inside `.node__composition-row`, so it never shrinks — its
 * width is whatever its widest child asks for. `.node__composition-scope`
 * (the "this mount only" note) already carries a `max-width`.
 * `.node__composition--missing` (the refusal sentence, shown after a
 * refused press) carried none, so a ~200-character sentence took its
 * natural single-line width, the group grew past the card, and the row's
 * other child — `.node__composition-toggle`, `flex: 1; min-width: 0` — was
 * squeezed to almost nothing to make room.
 *
 * Measured live at http://localhost:5317 (dev-server-only reproduction, no
 * backend needed — an unsaved workflow with an unreachable slug already
 * refuses the press): before this fix, `.node__composition--missing`
 * rendered 851px wide against a 252px card. This suite pins the CSS
 * constraints that keep every text element in the group inside the row's
 * own width, so the group can only grow as wide as its own cap allows —
 * never as wide as its longest possible sentence.
 *
 * Modelled on `src/view/mountScopeIsVisible.test.ts` and
 * `src/canvas/chipsDoNotMoveTheLayout.test.ts`: read the source as text
 * and pin the CSS declaration, rather than mounting the component — this
 * suite runs in `node`, and the declaration is the whole of the promise.
 */

const css = readFileSync(new URL('./nodes/CompositionBody.css', import.meta.url), 'utf8');
const tsx = readFileSync(new URL('./nodes/CompositionBody.tsx', import.meta.url), 'utf8');

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = css.match(new RegExp(`${escaped}\\s*\\{[^}]*\\}`));
  expect(match, `expected a CSS rule for ${selector}`).toBeTruthy();
  return match![0];
}

describe('the open-group can never grow past its own cap', () => {
  it('has a max-width, so a long sentence inside it wraps instead of pushing the card wider', () => {
    expect(rule('.node__composition-open-group')).toMatch(/max-width:/);
  });
});

describe('every text element the open-group can hold wraps within it', () => {
  it('the refusal sentence (`.node__composition--missing`) wraps rather than running past the card', () => {
    expect(rule('.node__composition--missing')).toMatch(/overflow-wrap:\s*break-word/);
  });

  it('the scope note (`.node__composition-scope`) already had a cap — still does', () => {
    expect(rule('.node__composition-scope')).toMatch(/max-width:/);
  });
});

describe('the sibling text outside the open-group wraps too, not just the element that broke', () => {
  it('the note shown when the census cannot be read (`.node__composition-note`, carries the slug) wraps a long slug', () => {
    expect(rule('.node__composition-note')).toMatch(/overflow-wrap:\s*break-word/);
  });

  it('the package purpose line (`.node__composition-purpose`) wraps a long expected-outcome-derived sentence', () => {
    expect(rule('.node__composition-purpose')).toMatch(/overflow-wrap:\s*break-word/);
  });
});

/**
 * The second half of the report: **Open this mount** goes `aria-disabled`
 * while the parent workflow is unsaved, and until now the *why* lived only
 * in the button's `title` — invisible on a touch device, and to a keyboard
 * user before they act, exactly the defect `say-it-on-the-surface/08`
 * closed for the "this mount only" sentence one file over.
 */
describe('a disabled Open-this-mount button says why, visibly, before any press', () => {
  it('renders a short visible reason when the parent is unsaved, not only the button title', () => {
    // The reason must appear as literal JSX text (a span child), not only
    // inside a `title={...}` string — mirroring `mountScopeIsVisible.test.ts`'s
    // own check for the sibling sentence.
    expect(tsx).toMatch(
      /<span className="node__composition-scope">\s*save this workflow to enable\s*<\/span>/,
    );
  });

  it('keeps the fuller sentence for a mouse, in the title', () => {
    expect(tsx).toMatch(/needs a folder on the backend/);
  });

  it('still shows "this mount only, others unaffected" when the mount can actually be opened', () => {
    expect(tsx).toMatch(
      /<span className="node__composition-scope">\s*this mount only, others unaffected\s*<\/span>/,
    );
  });
});
