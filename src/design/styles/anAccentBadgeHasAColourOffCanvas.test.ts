import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * `kanban-patrol/14`. `Badge tone="accent"` renders nothing outside a
 * `[data-accent]` subtree — every declaration of `--accent-tint` (and its
 * siblings) sits under `[data-accent]`/`[data-accent='blue']`/etc, none at
 * `:root`, so a badge drawn anywhere the canvas is not computes a
 * transparent background and inherited text colour.
 *
 * Two live call sites already had this bug before the kanban board did:
 * `TopBar.tsx`'s token counter (`tone={running ? 'accent' : 'neutral'}` —
 * invisible exactly while a run is in flight) and `Palette.tsx`'s scoped
 * count. Both get a real background as a consequence of this fix, which
 * is the owner's own call, made explicit rather than an accidental side
 * effect nobody asked for.
 *
 * A rendered mount is not needed to say a custom property has no
 * declaration in scope — this is a fact about two CSS rules, the same
 * idiom `aColumnHasOneToneAndCardsDoNotResort.test.ts` already uses one
 * layer up. Red first: today the lookup finds no `:root` declaration at
 * all.
 */

const THEME_CSS = readFileSync(
  fileURLToPath(new URL('./theme.css', import.meta.url)),
  'utf8',
  // Comments out: this file explains itself in prose, and prose is where
  // the stray braces live that would otherwise desync a brace-counting
  // parser — the same reason `PatrolBoard.css`'s own stylesheet test
  // strips comments before reading rules.
).replace(/\/\*[\s\S]*?\*\//g, '');

/** Every top-level rule's selector and body, correctly nested-brace-aware
 * only for the shallow one level this file's rules actually use. */
function rulesWithSelector(css: string, selectorPattern: RegExp): string[] {
  const bodies: string[] = [];
  const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
  let match: RegExpExecArray | null;
  while ((match = ruleRe.exec(css))) {
    const selector = (match[1] ?? '').trim();
    if (selectorPattern.test(selector)) bodies.push(match[2] ?? '');
  }
  return bodies;
}

const ACCENT_PROPERTIES = [
  '--accent-solid',
  '--accent-strong',
  '--accent-tint',
  '--accent-on-tint',
] as const;

describe('every accent slot has a real, unscoped default', () => {
  it.each(ACCENT_PROPERTIES)('%s is declared inside a `:root` rule', (property) => {
    const rootBodies = rulesWithSelector(THEME_CSS, /(^|,\s*):root(\s*,|\s*$)/);
    const declaredAtRoot = rootBodies.some((body) => body.includes(`${property}:`));

    expect(
      declaredAtRoot,
      `${property} has no :root declaration — a badge drawn outside a [data-accent] subtree gets nothing`,
    ).toBe(true);
  });

  it('the [data-accent] variants still exist and still override the default', () => {
    // The fix adds a default; it must not delete the per-family overrides
    // `[data-accent='blue']` etc — a node family that sets its own hue must
    // still win over the new :root fallback.
    const blueBody = rulesWithSelector(THEME_CSS, /\[data-accent='blue'\]/)[0];
    expect(blueBody).toBeDefined();
    expect(blueBody).toContain('--accent-tint: var(--blue-50)');
  });
});
