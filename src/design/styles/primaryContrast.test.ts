import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { contrastRatio } from '@view/overlays/contrastAudit';

/**
 * White text on the primary button must be readable.
 *
 * The **Run** button — the most important control on the canvas — was white on
 * `#16a34a` at 13px: **3.30:1**, where WCAG AA asks 4.5:1
 * (reviews-2026-08-14 tickets 05 and 11). The same token is used as *text* on
 * a pale green tint by the status pills, which failed at 3.12:1 for the same
 * reason: the green was tuned to look right as a fill, and then reused
 * anywhere green was wanted.
 *
 * This reads the real stylesheets rather than a copy of the values, so it
 * fails if someone brightens the green back — which is the likely future,
 * since the darker green is the less lively one and nothing else would
 * complain.
 *
 * Every state is checked, not just the resting one. A hover that fails is a
 * button that becomes unreadable exactly while it is being used.
 */
const styles = (name: string): string =>
  readFileSync(fileURLToPath(new URL(`./${name}`, import.meta.url)), 'utf8');

const TOKENS = styles('tokens.css');
const THEME = styles('theme.css');

/** Resolves `--green-600` → `#15803d` through one level of `var()`. */
function colour(value: string): string {
  const direct = /^#[0-9a-f]{3,8}$/i.exec(value.trim());
  if (direct) return value.trim();
  const alias = /var\(\s*(--[a-z0-9-]+)\s*\)/i.exec(value);
  if (!alias?.[1]) return value.trim();
  const declared = new RegExp(`${alias[1]}\\s*:\\s*([^;]+);`).exec(TOKENS);
  return (declared?.[1] ?? '').trim();
}

/** The value a token has inside a given block of `theme.css`. */
function tokenIn(block: string, name: string): string {
  const declared = new RegExp(`${name}\\s*:\\s*([^;]+);`).exec(block);
  if (!declared?.[1]) throw new Error(`${name} is not declared in this block`);
  return colour(declared[1]);
}

/** `theme.css` declares light at `:root` and dark under a media/attr block. */
function blocks(): { light: string; dark: string } {
  const darkAt = THEME.search(/@media \(prefers-color-scheme: dark\)|\[data-theme=['"]?dark/);
  expect(darkAt).toBeGreaterThan(0);
  return { light: THEME.slice(0, darkAt), dark: THEME.slice(darkAt) };
}

describe.each(['light', 'dark'] as const)('the primary button in %s', (scheme) => {
  const block = () => blocks()[scheme];

  it.each(['--color-primary', '--color-primary-hover', '--color-primary-active'])(
    '%s carries its own text at 4.5:1 or better',
    (state) => {
      const background = tokenIn(block(), state);
      const text = tokenIn(block(), '--color-primary-text');
      const ratio = contrastRatio(background, text);

      expect(ratio, `${state} = ${background} on ${text}`).not.toBeNull();
      // 4.5:1 — the button's label is 13px, which is nowhere near the 24px
      // (or 18.66px bold) that would earn the 3:1 large-text allowance.
      expect(ratio ?? 0, `${state} = ${background}`).toBeGreaterThanOrEqual(4.5);
    },
  );

  it('keeps the three states visibly different from one another', () => {
    // Contrast must not be bought by collapsing hover and active into the
    // resting colour — that would pass this file and lose the affordance.
    const resting = tokenIn(block(), '--color-primary');
    const hover = tokenIn(block(), '--color-primary-hover');
    const active = tokenIn(block(), '--color-primary-active');

    expect(new Set([resting, hover, active]).size).toBe(3);
  });
});
