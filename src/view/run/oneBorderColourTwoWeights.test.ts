import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * One border colour in this dock, at two weights — `memory-and-replay` 64.
 *
 * The owner, on the shipped panel: *"The rule of thumb is: darker border only
 * for the draggable; other normal borders should be the same border colour but
 * a lighter variant or opacity of the dark colour, about 60% — a greyish."*
 *
 * That is a rule about a **family**, so it cannot be kept by picking a nicer
 * token for the line somebody pointed at. It is kept by there being exactly
 * two weights in the panel and by the darker one belonging to the one edge a
 * pointer can drag. Four token names for four hairlines is how it comes back:
 * each substitution reads fine on its own and the family drifts apart.
 *
 * Scoped to this stylesheet on purpose. A separate ticket owns the rest of the
 * app, and `design/` is where the shared `--color-rule-soft` belongs when
 * somebody mints it; until then `--rtl-rule` is a local value with the
 * argument written beside it.
 */
const css = readFileSync(fileURLToPath(new URL('./RunDock.css', import.meta.url)), 'utf8');

/**
 * Every `solid`/`dashed` border colour this stylesheet names — **hairlines
 * only**.
 *
 * `--border-width-marker` is excluded, and that is a recorded exception rather
 * than a convenient filter. A marker is the quotation rule down the left of
 * `.rtl__payload-text`: it is thicker than a hairline on purpose, it is a
 * typographic mark rather than an edge of a region, and `memory-and-replay/62`
 * already pins the token it wears. Two jobs, two weights; the rule above is
 * about the edges.
 */
function borderColours(): readonly string[] {
  return [...css.matchAll(/border[a-z-]*:\s*([^;]*?)(?:solid|dashed)\s+var\((--[a-z0-9-]+)\)/g)]
    .filter((match) => !match[1]!.includes('--border-width-marker'))
    .map((match) => match[2]!);
}

describe('the run dock draws borders in one colour', () => {
  it('gives the dark weight to the draggable edge and to nothing else', () => {
    // `--color-rule` is the dark one. The dock's lower border is the line the
    // grip straddles — `.run-dock__grip` draws no line of its own, which is
    // why the darker weight is looked for on the panel rather than on the
    // handle.
    expect(borderColours().filter((token) => token === '--color-rule')).toHaveLength(1);
    expect(css).toMatch(/\.run-dock \{[^}]*border-bottom:[^;]*var\(--color-rule\)/s);
  });

  it('draws every other hairline in the same colour at 60%', () => {
    expect(css).toContain('--rtl-rule: color-mix(in srgb, var(--color-rule) 60%, transparent)');

    const others = borderColours().filter((token) => token !== '--color-rule');
    const structural = others.filter((token) => token.startsWith('--color-border'));

    expect(
      structural,
      'a hairline in this dock reaching past `--rtl-rule` for its own border ' +
        'token. Four names for four lines is the drift this rule exists to stop — ' +
        'use `--rtl-rule`, and if a line genuinely needs a different weight, say ' +
        'which and why here.',
    ).toEqual([]);
  });
});
