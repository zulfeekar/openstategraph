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
 *
 * **The rule decision is superseded in part, twice, and by the same
 * owner sentence read twice.** `the-look-has-an-author-now/16` split the
 * width from the ink and took `--color-rule` off three of the four seams;
 * `17` took `--border-width-rule` off the same three. What survives of
 * `07` here is the *pair* — a 2px full-ink line — and it survives where a
 * pointer can drag. The argument is written at the seams table below
 * rather than here, beside the rows it changes.
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
   * `--color-rule` is still the authored full ink and still flips with the
   * theme. **What changed in `16` is who may spend it** — see the
   * supersession note on the seams block below.
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
   * **`07`'s decision, superseded in part twice — by
   * `the-look-has-an-author-now/16` and then by `17` — and the two
   * supersessions are one move finished.**
   *
   * `07` measured `borderWidthsInUse === ["1px"]` and decided four seams:
   * the toolbar against everything under it, each side panel against the
   * canvas, and the run dock against the stage. Two values carried that
   * decision — a **width** (`--border-width-rule`, 2px) and an **ink**
   * (`--color-rule`, full). The reported defect was the width; the ink came
   * along with it.
   *
   * `16` read the owner's second sentence as prescribing a dark grey for
   * normal borders, took full ink off three of these four seams, and left
   * them at 2px. Their third sentence, pointing at the palette's right
   * edge, says that was the wrong half: *"this is a normal border — I asked
   * opacity less, or light grey shade. Only the draggable border is
   * correct."* A 2px line at 70% ink beside a 2px line at 100% differs by
   * alpha alone, which is a difference you measure rather than see.
   *
   * So `17` takes the **width** off the same three. Three of these four
   * seams are not draggable: the toolbar is fixed, and both panels take
   * their width from `--layout-palette-width` / `--layout-inspector-width`
   * with no handle anywhere. The fourth is: `.run-dock__grip` straddles the
   * dock's lower edge with `cursor: ns-resize` and draws no line of its
   * own, so that border **is** the grip.
   *
   * What is left is not "width says region, ink says draggable" — that was
   * `16`'s formula and it asked a reader to see 30% of alpha. It is
   * simpler: **2px full ink is the draggable weight, and it is one pair,
   * spent nowhere else.** `07`'s Modernist argument was for that pair, and
   * the pair still exists; what `07` got wrong is only *how many* lines in
   * the product are allowed to wear it.
   *
   * The dock's seam is on its **lower** edge since `memory-and-replay` 63 —
   * it opens under the top bar and pushes the paper down, so the seam it
   * draws is the one it shares with the paper, which is also the one it is
   * dragged by. The side a seam is drawn on is a fact about where the
   * region is, and this table is where that is recorded.
   *
   * A panel *header* is not one of them, and neither is a list row — the
   * panel's own edge is already the seam, and a second one 40px inside it
   * doubles the boundary rather than drawing a new one.
   */
  const SEAMS: ReadonlyArray<
    readonly [file: string, selector: string, side: string, width: string, ink: string]
  > = [
    [
      'view/topbar/TopBar.css',
      '.topbar',
      'border-bottom',
      '--border-width-hairline',
      '--color-border',
    ],
    [
      'design/primitives/Panel.css',
      '.panel--left',
      'border-right',
      '--border-width-hairline',
      '--color-border',
    ],
    [
      'design/primitives/Panel.css',
      '.panel--right',
      'border-left',
      '--border-width-hairline',
      '--color-border',
    ],
    ['view/run/RunDock.css', '.run-dock', 'border-bottom', '--border-width-rule', '--color-rule'],
  ];

  it.each(SEAMS)('%s %s draws its seam from tokens', (file, selector, side, width, ink) => {
    const css = read(join(SRC, file));
    const block = new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? '';
    expect(block).toContain(`${side}: var(${width}) solid var(${ink})`);
  });

  /**
   * The cage test, and `17` narrows what it cages. Rule width is no longer
   * a property of a *seam*; it is half of the draggable pair, so the files
   * allowed to draw it are the files allowed to spend `--color-rule` —
   * `aBorderIsDraggableOrItIsNot.test.ts` holds that list app-wide and
   * checks the two halves land on the same declarations.
   */
  const RULE_WIDTH_FILES = ['view/nodes/NodeCard.css', 'view/run/RunDock.css'];

  it('draws a rule-width line only where a pointer can drag', () => {
    const drawn = stylesheets().flatMap((path) =>
      [...read(path).matchAll(/--border-width-rule\)/g)].map(() => under(path)),
    );
    expect([...new Set(drawn)].sort()).toEqual(RULE_WIDTH_FILES.slice().sort());
  });

  /**
   * And the half of `07` that survived both passes, asserted separately so
   * a future reader can see which claim is still standing: exactly one of
   * the four is the draggable pair, and it is the one with a grip on it.
   * The app-wide statement lives in `aBorderIsDraggableOrItIsNot.test.ts`;
   * this is the local one, because this is the file that used to say all
   * four were.
   */
  it('gives full ink to the one seam a pointer can drag, and to no other seam', () => {
    expect(SEAMS.filter(([, , , , ink]) => ink === '--color-rule')).toEqual([
      ['view/run/RunDock.css', '.run-dock', 'border-bottom', '--border-width-rule', '--color-rule'],
    ]);
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
