import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * **One palette, one rule for getting a component onto the canvas.**
 *
 * `say-it-on-the-surface` 04, superseding half of `canvas-feels-right` 01.
 *
 * The palette had two rules and nobody had noticed: `PaletteItem` and
 * `PackageItem` placed on click, `AssemblyItem` had no click handler at all —
 * so the Revision loop was drag-only by *omission*. One of three row kinds
 * already behaved the way the owner asked for, and it got there by accident.
 *
 * The rule now: **drag aims, the keyboard places, a mouse click does neither.**
 * The accessibility ground `canvas-feels-right` 01 stood on is honoured — a
 * keyboard user can still place a node — but it is honoured by a *keyboard*
 * path rather than by a mouse click doubling as one.
 *
 * Source assertions, for the reason the other palette tests record: there is no
 * seam in a `node` environment that catches a handler quietly returning, and
 * "which gestures place" is exactly what a later tidy-up restores without
 * meaning to.
 */
const palette = readFileSync(fileURLToPath(new URL('./Palette.tsx', import.meta.url)), 'utf8');

/**
 * The howto paragraph's rendered text, collapsed to single spaces.
 *
 * Prettier is free to move the line break inside this JSX text node — it did,
 * moving `Tab` to the end of the previous line (`production-ready` 91) — and
 * a browser collapses that whitespace identically either way. So the source
 * bytes are not what a user reads; the collapsed text is. Matching *that*
 * keeps the test asserting the copy's meaning rather than its line-wrapping,
 * which is the only thing distinguishing this from the bug it replaces: a
 * reflow must stay green, and a reworded sentence must still go red.
 */
function collapsedWhitespace(source: string): string {
  return source.replace(/\s+/g, ' ').trim();
}

/** The opening tag of each of the three row components. */
function rowSource(component: string): string {
  const at = palette.indexOf(`function ${component}(`);
  expect(at, `${component} not found`).toBeGreaterThan(-1);
  const next = palette.indexOf('\nfunction ', at + 1);
  return palette.slice(at, next === -1 ? undefined : next);
}

const ROWS = ['PaletteItem', 'PackageItem', 'AssemblyItem'] as const;

describe('the palette’s placement rule', () => {
  it('gives every row kind the same keyboard path', () => {
    // Including the assembly, which had none. This is the assertion that would
    // have caught the original inconsistency.
    for (const row of ROWS) {
      expect(rowSource(row), row).toContain('onKeyDown={onKeyboardActivate(');
    }
  });

  it('places from no row kind on a plain mouse click', () => {
    for (const row of ROWS) {
      const source = rowSource(row);
      // `PackageItem` keeps an `onClick`, but only to *speak a refusal* —
      // never to place. The distinction is the whole point, so it is asserted
      // rather than waved at: no click handler may reach `onActivate`.
      expect(source, row).not.toMatch(/onClick=\{[^}]*onActivate\(\)/);
    }
  });

  it('activates on Enter and Space, and on nothing else', () => {
    const handler = palette.slice(
      palette.indexOf('function onKeyboardActivate'),
      palette.indexOf('function onKeyboardActivate') + 400,
    );
    expect(handler).toContain("event.key !== 'Enter' && event.key !== ' '");
    // Without this a `<button>` synthesises a click from Enter and the
    // placement fires twice.
    expect(handler).toContain('event.preventDefault()');
  });

  it('still aims with a drag, from every row kind', () => {
    // The half that always worked, pinned so that "make it consistent" can
    // never be read as "remove the drag".
    for (const row of ROWS) {
      expect(rowSource(row), row).toContain('onDragStart={(event) => {');
    }
  });

  it('says the rule out loud, which is what never shipped last time', () => {
    // `canvas-feels-right` 01 resolved "and the palette says so". The
    // mechanical half landed; this half lived in a source comment, so every
    // user met the rule by accident.
    expect(palette).toContain('palette-howto');
    const howto = collapsedWhitespace(rowSource('Palette').match(/<p className="palette-howto">([\s\S]*?)<\/p>/)?.[1] ?? '');
    expect(howto).toMatch(/Drag any of these onto the canvas/);
    expect(howto).toMatch(/Tab to one and press Enter/);
  });
});
