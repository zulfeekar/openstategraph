import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * `stable-beta-public/19`. The owner opened chat and inspector side by
 * side, looked for the handle `16` drew, and pointed at the panel border
 * *between* them — because the real grip, on the column's left edge, drew
 * nothing until a pointer found it. Hover and focus painted a hairline;
 * nothing painted at rest.
 *
 * The claim this file still makes, and the only one: **a grip has a mark
 * with no pointer near it** — a `--grip-length` bar, centred on its own
 * axis, on both orientations.
 *
 * What it no longer says is what that bar is *made of*. `19` drew it at
 * `--color-rule` and full rule width, in `AppShell.css` and `RunDock.css`
 * separately; `21` split the states — quiet at rest, heavy under a pointer
 * — and moved both into `design/primitives/Grip.css`, because two
 * stylesheets drawing one control is a weight neither can compare with the
 * other, and they had come apart by 2px on screen.
 *
 * `21`'s "quiet" turned out to mean invisible: it moved the resting bar's
 * *ink* down to `--color-border`, the hairline every non-draggable edge
 * uses, and the owner reported twice in one day that they could not find
 * the control (`stable-beta-public/23`). What made it vanish was width, not
 * ink: 1px of the hairline against the 2px of full ink `23` restored. This
 * sentence used to say the hairline "composites under 2:1 against the panel
 * ground", which was not true of the 60% mix it was written about (4.41:1),
 * and is true of the 30% mix `stable-beta-public/26` shipped — by accident,
 * so the argument is stated as width instead. `23`
 * gave the two states back one ink — `--color-rule`, full strength, at
 * both rest and hover — and let *width* alone carry the difference:
 * `--border-width-rule` (2px) at rest, `--grip-weight` (4px) under a
 * pointer. The states, the tokens and the fact that no other stylesheet
 * draws one are `design/primitives/gripIsOneControl.test.ts`; this file is
 * the older, narrower question, kept because it is the one the owner asked.
 */
const SRC = fileURLToPath(new URL('../../', import.meta.url));
const read = (path: string): string => readFileSync(join(SRC, path), 'utf8');
const code = (css: string): string => css.replace(/\/\*[\s\S]*?\*\//g, '');

/** The block for one selector, as written — `{...}` only, comments stripped. */
function ruleBody(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`).exec(code(css));
  if (!match) throw new Error(`no rule for ${selector}`);
  return match[1] ?? '';
}

describe('a grip has a resting mark, not just a hover mark', () => {
  const css = read('design/primitives/Grip.css');

  it('declares --grip-length as a token, 300px', () => {
    const tokens = code(read('design/styles/tokens.css'));
    expect(tokens).toMatch(/--grip-length:\s*300px;/);
  });

  it('draws a resting bar on the column grip, vertically centred', () => {
    const body = ruleBody(css, '.grip--vertical::before');
    expect(body).toMatch(/height:\s*var\(--grip-length\);/);
    // Vertically centred: either top:50%/translateY(-50%), or top+bottom:0
    // with margin:auto 0.
    const centred =
      (/top:\s*50%/.test(body) && /translateY\(-50%\)/.test(body)) ||
      (/top:\s*0;/.test(body) && /bottom:\s*0;/.test(body) && /margin:\s*auto 0;/.test(body));
    expect(centred).toBe(true);
  });

  it('draws a resting bar on the run dock grip, horizontally centred', () => {
    const body = ruleBody(css, '.grip--horizontal::before');
    expect(body).toMatch(/width:\s*var\(--grip-length\);/);
    const centred =
      (/left:\s*50%/.test(body) && /translateX\(-50%\)/.test(body)) ||
      (/left:\s*0;/.test(body) && /right:\s*0;/.test(body) && /margin:\s*0 auto;/.test(body));
    expect(centred).toBe(true);
  });

  /**
   * `21` made the resting bar quieter by moving its *ink* down a weight —
   * `--color-border`, the same hairline every non-draggable edge uses, at
   * 1px against the 2px of full ink the hover state brought — which is
   * indistinguishable from "not drawn" (`stable-beta-public/23`). So the
   * bar is quieter at rest by *width* only now, never by ink: both states
   * share `--color-rule`, and only `--grip-weight` — the hover/focus
   * stroke — is absent at rest.
   */
  it('keeps the resting bar quieter than the stroke a pointer brings, by width alone', () => {
    for (const selector of ['.grip--vertical::before', '.grip--horizontal::before']) {
      const body = ruleBody(css, selector);
      expect(body).toContain('var(--border-width-rule)');
      expect(body).toContain('var(--color-rule)');
      expect(body).not.toContain('var(--grip-weight)');
    }
  });
});
