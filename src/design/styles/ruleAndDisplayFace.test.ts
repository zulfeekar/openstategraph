import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Two values the design system authored, and two ways they were being lost.
 *
 * `the-look-has-an-author-now/07`. Measured on the running app before this
 * pin existed: `borderWidthsInUse` over every `div`/`section`/`header`
 * returned exactly `["1px"]`, and the wordmark computed to IBM Plex Sans
 * while `--osg-font-display` — Archivo, downloaded on every page load —
 * was read by no rule anywhere.
 *
 * Neither loss was a decision. Both were the default: a `1px` typed into a
 * component because that is what a border looks like, and a display face
 * that nothing set because setting it is a separate act from shipping it.
 * A default has no way to fail, which is what this file is for.
 *
 * It pins **two decisions and their boundaries**, because in both cases the
 * over-applied version is the same defect as the un-applied one — 2px on
 * every list row is a cage, and a 13px node title in a display face at
 * weight 700 is the mistake the ticket warned about by name.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url));
const SRC = fileURLToPath(new URL('../../', import.meta.url));

/** A path as this repository writes it — `view/run/RunDock.css`. */
const under = (path: string): string => relative(SRC, path).split(sep).join('/');

const read = (path: string): string => readFileSync(path, 'utf8');
const styles = (name: string): string => read(join(HERE, name));

const TOKENS = styles('tokens.css');
const THEME = styles('theme.css');

/** Every `.css` under `src/`, so a new stylesheet is covered on the day it lands. */
function stylesheets(dir: string = SRC): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) found.push(...stylesheets(path));
    else if (entry.endsWith('.css')) found.push(path);
  }
  return found.sort();
}

/** The declared value of a custom property, from the first block that sets it. */
function declared(css: string, token: string): string {
  return (new RegExp(`${token}\\s*:\\s*([^;]+);`).exec(css)?.[1] ?? '').replace(/\s+/g, ' ').trim();
}

describe('a border width is a token, never a literal', () => {
  /**
   * The authored file ships **both** `--osg-rule: 2px` and
   * `--osg-hairline: 1px`, so the distinction was already made upstream and
   * this product was simply using one of them everywhere. These are the two
   * names it reaches them by.
   */
  it('names the two authored widths and nothing between them', () => {
    expect(declared(TOKENS, '--border-width-hairline')).toBe('var(--osg-hairline)');
    expect(declared(TOKENS, '--border-width-rule')).toBe('var(--osg-rule)');
    expect(declared(TOKENS, '--osg-hairline')).toBe('1px');
    expect(declared(TOKENS, '--osg-rule')).toBe('2px');
  });

  /**
   * The rule is full ink — `--osg-divider`, which the authored file
   * comments as *"2px rules, full ink"* and flips with the theme. That is
   * most of the difference between "flat and minimal" and "Modernist": a
   * muted grey 2px line is just a thicker hairline.
   */
  it('gives the rule the authored full-ink colour, not a muted border grey', () => {
    expect(declared(THEME, '--color-rule')).toBe('var(--osg-divider)');
    expect(declared(TOKENS, '--osg-divider')).toBe('#201e1d');
  });

  /**
   * The one that actually catches drift. A `border: 1px solid ...` typed
   * into a component is how every border in this app came to be a hairline
   * without anybody choosing it, and it reads as ordinary CSS in review.
   *
   * **Scoped to `1px` in a `border` shorthand, and the narrowness is the
   * judgement.** Three kinds of line were looked at and deliberately left
   * alone, because they are not the rule and never were:
   *
   * - **Focus rings and node rings** are `outline` and `box-shadow`, not
   *   borders. `--osg-focus` is the design system's own separate token and
   *   `--focus-ring-width` carries its geometry argument.
   * - **The 2px and 3px left bars** — a blockquote, a quoted run, an
   *   inspector group, the palette's section marker — are indent markers on
   *   a block of text, not seams between regions. They share a number with
   *   the rule and none of its meaning, and renaming them
   *   `--border-width-rule` would have said something false in a file that
   *   is meant to be read.
   * - **`canvas/canvas.css`** is exempt outright. Its lines are drawn over
   *   the JointJS paper, in a coordinate space the authored file measures
   *   separately — `--osg-node-ring: 5.5` is *in 100-unit mark space*, not
   *   pixels — so a CSS pixel token does not apply there by assumption.
   */
  it('leaves no literal hairline in a border shorthand outside the two exempt files', () => {
    const shorthand =
      /^[ \t]*border(?:-(?:top|right|bottom|left|block|inline|block-end|block-start|inline-end|inline-start))?[ \t]*:[ \t]*([^;]+);/gm;
    const exempt = [join(HERE, 'tokens.css'), join(SRC, 'canvas/canvas.css')];
    const offenders: string[] = [];
    for (const path of stylesheets()) {
      if (exempt.includes(path)) continue;
      for (const match of read(path).matchAll(shorthand)) {
        const value = match[1] ?? '';
        if (/(?<![\w.-])1px(?=\s)/.test(value)) {
          offenders.push(`${under(path)}: ${value.trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe('the rule separates regions; everything inside one is a hairline', () => {
  /**
   * Four declarations, and they are the four seams of the shell: the
   * toolbar against everything under it, each side panel against the
   * canvas, and the run dock against the stage. Those are the boundaries a
   * reader is meant to see.
   *
   * A panel *header* is not one of them, and neither is a list row — the
   * panel's own edge is already the rule, and a second one 40px inside it
   * doubles the boundary rather than drawing a new one.
   */
  const SEAMS: ReadonlyArray<readonly [file: string, selector: string, side: string]> = [
    ['view/topbar/TopBar.css', '.topbar', 'border-bottom'],
    ['design/primitives/Panel.css', '.panel--left', 'border-right'],
    ['design/primitives/Panel.css', '.panel--right', 'border-left'],
    ['view/run/RunDock.css', '.run-dock', 'border-top'],
  ];

  it.each(SEAMS)('%s %s draws the rule', (file, selector, side) => {
    const css = read(join(SRC, file));
    const block = new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? '';
    expect(block).toContain(`${side}: var(--border-width-rule) solid var(--color-rule)`);
  });

  /** The cage test: nothing else in the product may draw a rule. */
  it('is drawn in exactly those four places', () => {
    const drawn = stylesheets().flatMap((path) =>
      [...read(path).matchAll(/--border-width-rule\)/g)].map(() => under(path)),
    );
    expect(drawn.sort()).toEqual(SEAMS.map(([file]) => file).sort());
  });
});

describe('the display face is a pairing, not a global swap', () => {
  /** Archivo has to be reachable, or setting it is a no-op nobody sees. */
  it('declares the face it names', () => {
    expect(declared(TOKENS, '--font-display')).toBe('var(--osg-font-display)');
    expect(declared(TOKENS, '--osg-font-display')).toContain("'Archivo Variable'");
    expect(styles('fonts.css')).toContain("font-family: 'Archivo Variable'");
  });

  /**
   * Three roles, and the list is the decision. The masthead and the two
   * largest headings speak in the display face; **everything a user reads
   * at length or scans as a label does not.**
   */
  const DISPLAY = ['--type-wordmark', '--type-display', '--type-heading-lg'];
  const TEXT = [
    '--type-heading-sm',
    '--type-body-md',
    '--type-body-sm',
    '--type-title-node',
    '--type-caption',
    '--type-label',
  ];

  it.each(DISPLAY)('%s is set in the display face', (role) => {
    expect(declared(TOKENS, role)).toContain('var(--font-display)');
  });

  it.each(TEXT)('%s stays in the text face', (role) => {
    expect(declared(TOKENS, role)).toContain('var(--font-sans)');
  });

  /**
   * A node title is 13px inside a 252px card and a field label is 10px
   * uppercase. A display face is drawn for size; at those sizes it is
   * noise, and the ticket named both as the over-application to avoid.
   */
  it('keeps the canvas and the labels out of it', () => {
    expect(declared(TOKENS, '--type-title-node')).not.toContain('var(--font-display)');
    expect(declared(TOKENS, '--type-label')).not.toContain('var(--font-display)');
  });

  /** The wordmark is the masthead, and it is the only component that sets it. */
  it('gives the wordmark the display role', () => {
    expect(read(join(SRC, 'view/topbar/TopBar.css'))).toContain('font: var(--type-wordmark)');
  });
});
