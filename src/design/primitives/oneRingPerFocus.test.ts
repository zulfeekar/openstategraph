import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';

/**
 * `stable-beta-public/30`. Two rules drew a ring for one focus, and neither
 * was wrong on its own:
 *
 * - `reset.css`'s global `:focus-visible` paints an `outline` on the
 *   **control**, which is exactly right for a bare button — nothing else
 *   would state its focus at all.
 * - `Field.css`'s `.input:focus-within` paints a `box-shadow` ring on the
 *   **wrapper**, which is the visible box a text field actually is.
 *
 * A composed control has both, so every input in the product wore two rings
 * while the design tokens' own comment promised one. The wrapper wins,
 * because the wrapper is the box a reader sees; the control's outline is
 * cleared *inside* the wrapper and nowhere else, so the reset keeps serving
 * every control that has no wrapper.
 *
 * The census below is derived rather than listed, for the reason `CLAUDE.md`
 * gives about hand-picked pins: a list covers the files somebody already
 * worried about, which are the ones least likely to drift. Any primitive that
 * paints a wrapper ring must clear its control's outline in the same
 * stylesheet, and a new one that forgets fails here by name.
 */

/**
 * Comments come out before anything is matched. Every stylesheet in this
 * repository argues for itself in prose, and the argument quotes the rule it
 * is about — so a pin reading raw source passes on a rule that has been
 * commented out, which is what happened the first time this one was broken on
 * purpose. What is asserted is the CSS the browser sees.
 */
function rules(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

const primitives = new URL('./', import.meta.url);
const resetCss = rules(readFileSync(new URL('../styles/reset.css', import.meta.url), 'utf8'));

/** `.input:focus-within { … box-shadow: 0 0 0 var(--focus-ring-width) … }` */
const wrapperRing = /^\.([a-z][a-z-]*):focus-within\s*\{([^}]*)\}/gm;

function wrappersThatPaintARing(css: string): string[] {
  const found = new Set<string>();
  for (const match of css.matchAll(wrapperRing)) {
    const root = match[1] ?? '';
    const body = match[2] ?? '';
    if (/box-shadow:\s*0 0 0 var\(--focus-ring-width\)/.test(body)) found.add(root);
  }
  return [...found];
}

const stylesheets = readdirSync(primitives)
  .filter((name) => name.endsWith('.css'))
  .map((name) => ({ name, css: rules(readFileSync(new URL(name, primitives), 'utf8')) }));

describe('a focused control wears one ring, and the wrapper owns it', () => {
  it('finds the composed controls that paint a wrapper ring', () => {
    // If this ever reads empty the census below asserts nothing, which is the
    // failure mode of every derived pin. `input` and `select` are the two
    // that existed when the ticket was filed.
    const roots = stylesheets.flatMap(({ css }) => wrappersThatPaintARing(css));
    expect(roots).toContain('input');
    expect(roots).toContain('select');
  });

  for (const { name, css } of stylesheets) {
    for (const root of wrappersThatPaintARing(css)) {
      it(`${name}: clears the control's own outline inside .${root}`, () => {
        const cleared = new RegExp(
          `\\.${root}\\s+\\.${root}__control:focus-visible\\s*\\{[^}]*outline:\\s*none`,
        );
        expect(css).toMatch(cleared);
      });

      it(`${name}: still paints the ring on .${root} itself`, () => {
        expect(css).toMatch(
          new RegExp(
            `\\.${root}:focus-within\\s*\\{[^}]*box-shadow:\\s*0 0 0 var\\(--focus-ring-width\\)`,
          ),
        );
      });
    }
  }
});

describe('a bare control keeps the ring the reset gives it', () => {
  it('still outlines anything `:focus-visible`', () => {
    // The half of the pair that must survive: a button, a tab, a canvas row
    // has no wrapper, so this outline is its only focus statement.
    expect(resetCss).toMatch(
      /^:focus-visible\s*\{[^}]*outline:\s*var\(--focus-ring-width\) solid/m,
    );
  });

  it('clears the outline for no class of its own', () => {
    // The suppression belongs beside the wrapper that replaces it. A reset
    // that named `.input` would put one control's exception in the file that
    // is supposed to know about none of them.
    expect(resetCss).not.toMatch(/\.input|\.select/);
  });
});
