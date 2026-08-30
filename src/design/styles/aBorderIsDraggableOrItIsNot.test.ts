import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The instrument for `the-look-has-an-author-now/15`, and the owner's rule
 * of thumb is the argument for its shape, quoted rather than paraphrased:
 *
 * > "The rule of thumb is: darker border only for the draggable. Other
 * > normal borders should be the same border colour but a lighter variant
 * > or opacity of the dark colour — about 60%, a greyish. Find the correct
 * > balance."
 *
 * So there are exactly **two** structural border weights, and which one a
 * border gets is decided by what it means, never by where it sits:
 * `--color-rule` (full ink, `--osg-divider`) for the one thing on a card a
 * user actually takes hold of, `--color-border` (the same ink at 60%
 * through `color-mix()`) for everything else — a panel edge, a card
 * outline, a divider, an input field, a table rule.
 *
 * **What this file does not try to settle.** A colour used to signal
 * something other than structural weight — danger, warning, focus, an
 * accent identity, a brand indicator — was never a candidate for either of
 * the two weights, and forcing one onto it would be answering a question
 * this ticket was not asked. Those are named below, each with the argument
 * for why it stays outside the two-weight system, the same way
 * `tokensDoNotDriftBack.test.ts` names its own quarantine rather than
 * writing a rule broad enough to wave at everything.
 *
 * **The one real exception, and it is a debt rather than a decision.**
 * `src/view/run/` still spends the three retired roles this ticket replaced
 * everywhere else (`--color-border-subtle/-default/-strong`) — a
 * concurrent session owns that directory and is applying this same rule
 * there itself. Excluding the directory from the census would have hidden
 * that debt behind a path check that outlives the reason for it; naming
 * every site instead means the row disappears the day someone actually
 * fixes it, and nothing else has to change here when they do.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const under = (path: string): string => relative(SRC, path).split(sep).join('/');
const read = (path: string): string => readFileSync(path, 'utf8');
const code = (css: string): string => css.replace(/\/\*[\s\S]*?\*\//g, '');

function filesUnder(dir: string, ext: readonly string[]): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) found.push(...filesUnder(path, ext));
    else if (ext.some((e) => entry.endsWith(e))) found.push(path);
  }
  return found.sort();
}

/** Every `.css` in the app — the whole app, `view/run/` included. A pin
 *  that path-excludes a directory stops meaning anything the day someone
 *  forgets why it was excluded; the debt in `view/run/` is named instead,
 *  below, so the directory stays in the census. */
const stylesheets = (): string[] => filesUnder(SRC, ['.css']);

interface Declaration {
  readonly file: string;
  readonly property: string;
  readonly value: string;
}

/** One `property: value;` declaration, as written — multi-line values
 *  included, the same shape `tokensDoNotDriftBack.test.ts` reads. */
function declarations(): Declaration[] {
  const out: Declaration[] = [];
  for (const path of stylesheets()) {
    for (const match of code(read(path)).matchAll(/([-a-zA-Z]+)\s*:\s*([^;{}]+);/g)) {
      out.push({
        file: under(path),
        property: match[1] ?? '',
        value: (match[2] ?? '').replace(/\s+/g, ' ').trim(),
      });
    }
  }
  return out;
}

/** A border or outline shorthand/longhand — every property that can put a
 *  visible line on an edge. `-radius` is excluded by name already; nothing
 *  here names a radius property. */
const BORDER_PROPS = new Set([
  'border',
  'border-top',
  'border-right',
  'border-bottom',
  'border-left',
  'border-inline-start',
  'border-inline-end',
  'border-block-start',
  'border-block-end',
  'border-color',
  'border-top-color',
  'border-right-color',
  'border-bottom-color',
  'border-left-color',
  'outline',
  'outline-color',
]);

/** Named helpers that carry width or geometry, never colour — stripped out
 *  before what is left is read as "the colour this line spends". */
const NOT_A_COLOUR = new Set([
  '--border-width-hairline',
  '--border-width-rule',
  '--border-width-marker',
  '--focus-ring-width',
]);

/** The colour token(s) a border/outline declaration spends, once width and
 *  geometry helpers are set aside. Usually exactly one; `none`/`0` (no line
 *  drawn at all) yield none, and those lines are dropped by the caller. */
function borderColourTokens(value: string): string[] {
  const names = [...value.matchAll(/var\(\s*(--[a-zA-Z0-9_-]+)/g)]
    .map((m) => m[1] ?? '')
    .filter((n) => !NOT_A_COLOUR.has(n));
  if (names.length > 0) return names;
  if (/currentColor/.test(value)) return ['currentColor'];
  if (/\btransparent\b/.test(value)) return ['transparent'];
  const rgba = /rgba?\([^)]+\)/.exec(value);
  if (rgba) return [rgba[0]];
  const hex = /#[0-9a-fA-F]{3,8}\b/.exec(value);
  if (hex) return [hex[0]];
  return [];
}

/** `box-shadow` draws a border in this product wherever it is a ring flush
 *  with the box edge — `inset 0 0 0 Npx <colour>` in a component's own
 *  file, which is how `Field`, `Button`, `Menu`, `Pill`, `Select`,
 *  `Palette`, `Minimap`, `canvas.css` and the node card all draw a 1px edge
 *  without competing with a real `border` a component also needs for its
 *  focus/error state — and `0 0 0 Npx <colour>` with no `inset` keyword at
 *  all inside `--shadow-node`/`-hover`/`-selected` in `theme.css`, which are
 *  spread shadows rather than inset ones but read as the identical ring
 *  once painted; `NodeCard.css` spends them as `box-shadow: var(--shadow-
 *  node-hover)` with no ring syntax of its own to match. A `box-shadow`
 *  with no such ring (a drop shadow, `none`, a glow) is not a border and is
 *  not matched. */
function insetRingColourTokens(value: string): string[] {
  const out: string[] = [];
  for (const m of value.matchAll(/(?:inset\s+)?0\s+0\s+0\s+[\d.]+px\s+([^,]+)/g)) {
    out.push(...borderColourTokens(m[1] ?? ''));
  }
  return out;
}

/** The three custom properties that carry a node-card ring the way a
 *  `box-shadow` declaration does everywhere else — declared once in
 *  `theme.css`, spent by `box-shadow: var(--shadow-node...)` in
 *  `NodeCard.css`, which is why `box-shadow` alone would have missed them. */
const SHADOW_RING_PROPS = new Set([
  '--shadow-node',
  '--shadow-node-hover',
  '--shadow-node-selected',
]);

interface Site {
  readonly file: string;
  readonly property: string;
  readonly value: string;
  readonly token: string;
}

function borderSites(): Site[] {
  const out: Site[] = [];
  for (const d of declarations()) {
    if (BORDER_PROPS.has(d.property)) {
      for (const token of borderColourTokens(d.value)) {
        out.push({ file: d.file, property: d.property, value: d.value, token });
      }
    } else if (d.property === 'box-shadow' || SHADOW_RING_PROPS.has(d.property)) {
      for (const token of insetRingColourTokens(d.value)) {
        out.push({ file: d.file, property: d.property, value: d.value, token });
      }
    }
  }
  return out;
}

describe('a border is drawn by what it means, and there are two weights', () => {
  it('finds real sites, so the census below is not vacuous', () => {
    const sites = borderSites();
    expect(sites.some((s) => s.token === '--color-border')).toBe(true);
    expect(sites.some((s) => s.token === '--color-rule')).toBe(true);
    expect(sites.length).toBeGreaterThan(80);
  });

  /**
   * Colour used for something other than structural weight — a state, an
   * identity, a brand mark — was never a candidate for either of the two
   * weights. Recorded by token rather than by site: the question this file
   * asks is "which colours are in play", and a token used for one reason
   * in ten files is one exception, not ten.
   */
  const SEMANTIC_EXCEPTIONS: ReadonlyArray<readonly [token: string, why: string]> = [
    ['--color-border-focus', 'focus indication — the accent, not a structural weight'],
    ['--color-focus-ring', 'the same accent, spent directly by an outline/ring'],
    ['--focus-ring-soft', 'the soft variant of the same focus accent (reset.css)'],
    ['--color-danger', 'an error state'],
    ['--color-status-warning', 'a warning state'],
    ['--color-status-running', "a running node's own status ring"],
    ['--color-status-error', 'an error/status state (TopBar, and RunDock — held below too)'],
    ['--color-primary', 'the active-tab / published indicator, a brand mark, not a border'],
    ['--color-selection-band-border', 'the marquee-selection accent on the canvas'],
    ['--color-group-border', "a container node's own identity tint"],
    ['--color-note-border', "a note node's own identity tint"],
    ['--accent-solid', "the slider thumb's own node-family accent"],
    ['--color-text-secondary', "the slider thumb's accent fallback, sharing the slot above"],
    ['currentColor', 'inherits the surrounding text colour on purpose'],
    ['transparent', 'a reserved slot with no line drawn (a tab underline, a focus ring, a reset)'],
    ['--amber-100', 'a warning-toned suggestion box in the ask panel'],
    ['--indigo-100', 'an info-toned suggestion box in the ask panel'],
  ];

  it.each(SEMANTIC_EXCEPTIONS)(
    '%s is a state/identity colour, not a border weight — %s',
    (token) => {
      // Existence check only: a token named here that nothing spends any more
      // is a stale exception, which the "no unexplained token" test below
      // would not itself catch since removing a use only shrinks the census.
      expect(borderSites().some((s) => s.token === token)).toBe(true);
    },
  );

  /**
   * `rgba()` amber/indigo hover states, one step darker than the
   * `--amber-100`/`--indigo-100` resting borders above — the same
   * suggestion boxes, and the same recorded gap `tokensDoNotDriftBack.test.ts`
   * already names for `rgba()`: an alpha composition over a ground the
   * token layer does not name, not a token this file can point at by name.
   */
  it('names the rgba() hover states beside the tokens they darken', () => {
    const rgbaSites = borderSites().filter((s) => /^rgba\(/.test(s.token));
    expect(rgbaSites.map((s) => `${s.file} ${s.value}`).sort()).toEqual(
      [
        'view/ask/AskPanel.css rgba(245, 158, 11, 0.3)',
        'view/ask/AskPanel.css rgba(245, 158, 11, 0.28)',
        'view/ask/AskPanel.css rgba(99, 102, 241, 0.28)',
      ].sort(),
    );
  });

  /**
   * Interaction *state*, not a third structural weight — `theme.css`'s own
   * argument for why it exists at all. Recorded as an exact site list
   * rather than a token existence check, because the thing that makes this
   * one safe is narrower than "the token appears somewhere": every site is
   * a `:hover`/`:active`/pressed rule, never a resting border, and a
   * resting use joining this list unnoticed is exactly the drift this
   * pin exists to catch. `--shadow-node-hover` is included once for each
   * theme block that declares it — both read `--color-border-emphasis`,
   * neither is a fresh site.
   */
  const EMPHASIS_SITES: ReadonlyArray<readonly [file: string, value: string]> = [
    [
      'design/primitives/Button.css',
      'inset 0 0 0 1px var(--color-border-emphasis), var(--shadow-xs)',
    ],
    ['design/primitives/Field.css', 'inset 0 0 0 1px var(--color-border-emphasis)'],
    ['design/primitives/Select.css', 'inset 0 0 0 1px var(--color-border-emphasis)'],
    ['design/styles/theme.css', '0 0 0 1px var(--color-border-emphasis), var(--osg-shadow-md)'],
    [
      'design/styles/theme.css',
      '0 0 0 1px var(--color-border-emphasis), 0 2px 0 rgba(0, 0, 0, 0.55)',
    ],
    ['view/ask/AskPanel.css', 'var(--color-border-emphasis)'],
    ['view/nodes/CompositionBody.css', 'var(--color-border-emphasis)'],
    ['view/nodes/NodeCard.css', 'var(--color-border-emphasis)'],
    ['view/palette/Palette.css', 'inset 0 0 0 1px var(--color-border-emphasis), var(--shadow-sm)'],
    ['view/workflow/DrillBanner.css', 'var(--color-border-emphasis)'],
  ];

  it('spends --color-border-emphasis at exactly the recorded interaction sites', () => {
    const found = borderSites()
      .filter((s) => s.token === '--color-border-emphasis')
      .map((s) => `${s.file} ${s.value}`)
      .sort();
    expect(found).toEqual(EMPHASIS_SITES.map(([file, value]) => `${file} ${value}`).sort());
  });

  /**
   * The debt this file does not hide. `view/run/RunDock.css` still spends
   * every one of the three roles this ticket retired elsewhere — a
   * concurrent session owns that directory and applies this same rule
   * there itself. Named exactly, by file and token, rather than by an
   * excluded path, so the row disappears the day it is fixed and nothing
   * here has to change when it does.
   */
  const HELD: ReadonlyArray<readonly [file: string, token: string, count: number]> = [
    ['view/run/RunDock.css', '--color-border-subtle', 6],
    ['view/run/RunDock.css', '--color-border-default', 1],
    ['view/run/RunDock.css', '--color-border-strong', 1],
    ['view/run/RunDock.css', '--color-bg-inverse', 1],
    ['view/run/RunDock.css', '--color-text-primary', 2],
    ['view/run/RunDock.css', '--color-text-quaternary', 1],
  ];

  it.each(HELD)(
    '%s still spends %s at %i site(s), and that is a debt with a ticket',
    (file, token, n) => {
      expect(borderSites().filter((s) => s.file === file && s.token === token)).toHaveLength(n);
    },
  );

  it('leaves no border/outline/inset-ring colour outside the two weights, a named exception, or a held row', () => {
    const allowed = new Set(['--color-border', '--color-rule']);
    const semantic = new Set(SEMANTIC_EXCEPTIONS.map(([token]) => token));
    const emphasisSites = new Set(EMPHASIS_SITES.map(([file, value]) => `${file} ${value}`));
    const held = new Set(HELD.map(([file, token]) => `${file} ${token}`));

    const violations = borderSites()
      .filter((s) => {
        if (allowed.has(s.token)) return false;
        if (semantic.has(s.token)) return false;
        if (/^rgba\(/.test(s.token)) return false; // named by site above
        if (s.token === '--color-border-emphasis')
          return !emphasisSites.has(`${s.file} ${s.value}`);
        if (held.has(`${s.file} ${s.token}`)) return false;
        return true;
      })
      .map((s) => `${s.file} ${s.property}: ${s.value} (${s.token})`);

    expect(violations).toEqual([]);
  });
});
