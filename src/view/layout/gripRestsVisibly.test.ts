import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * `stable-beta-public/19`. The owner opened chat and inspector side by
 * side, looked for the handle `16` drew, and pointed at the panel border
 * *between* them — because the real grip, on the column's left edge, draws
 * nothing until a pointer finds it. Hover and focus painted a full-height
 * hairline; nothing painted at rest.
 *
 * The fix is a resting affordance: a `--grip-length` (300px) bar, centred,
 * at `--color-rule` — the same "this is a draggable weight" ink
 * `aBorderIsDraggableOrItIsNot.test.ts` already reserves for a pointer-drag
 * edge. Hover/focus keep the full-height hairline as the "you are
 * dragging this" state; that CSS is untouched.
 *
 * The run dock's grip had no resting mark either (`RunDock.css`), so it
 * gets the same treatment turned ninety degrees in this commit, and the
 * two are asserted side by side rather than one at a time.
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

describe('the column grip has a resting mark, not just a hover mark', () => {
  const css = read('view/AppShell.css');

  it('declares --grip-length as a token, 300px', () => {
    const tokens = code(read('design/styles/tokens.css'));
    expect(tokens).toMatch(/--grip-length:\s*300px;/);
  });

  it('draws a resting bar on .app-shell__column-grip, vertically centred', () => {
    const body = ruleBody(css, '.app-shell__column-grip::before');
    expect(body).toMatch(/content:\s*['"]{2};?/);
    expect(body).toMatch(/height:\s*var\(--grip-length\);/);
    expect(body).toMatch(/border-left:\s*var\(--border-width-rule\) solid var\(--color-rule\);/);
    // Vertically centred: either top:50%/translateY(-50%), or inset-block
    // auto-margined, or top+bottom:0 with margin:auto 0.
    const centred =
      (/top:\s*50%/.test(body) && /translateY\(-50%\)/.test(body)) ||
      (/top:\s*0;/.test(body) && /bottom:\s*0;/.test(body) && /margin:\s*auto 0;/.test(body));
    expect(centred).toBe(true);
  });

  it('still keeps the full-height hairline on hover/focus, unchanged', () => {
    const hover = ruleBody(
      css,
      '.app-shell__column-grip:hover::after,\n.app-shell__column-grip:focus-visible::after',
    );
    expect(hover).toMatch(/top:\s*0;/);
    expect(hover).toMatch(/bottom:\s*0;/);
    expect(hover).toMatch(/background:\s*var\(--color-primary\);/);
  });
});

describe('the run dock grip gets the same resting mark, turned ninety degrees', () => {
  const css = read('view/run/RunDock.css');

  it('draws a resting bar on .run-dock__grip, horizontally centred', () => {
    const body = ruleBody(css, '.run-dock__grip::before');
    expect(body).toMatch(/content:\s*['"]{2};?/);
    expect(body).toMatch(/width:\s*var\(--grip-length\);/);
    expect(body).toMatch(/border-top:\s*var\(--border-width-rule\) solid var\(--color-rule\);/);
    const centred =
      (/left:\s*50%/.test(body) && /translateX\(-50%\)/.test(body)) ||
      (/left:\s*0;/.test(body) && /right:\s*0;/.test(body) && /margin:\s*0 auto;/.test(body));
    expect(centred).toBe(true);
  });
});
