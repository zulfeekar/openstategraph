import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The instrument for `the-look-has-an-author-now/15`, corrected by `16`
 * and again by `17`.
 *
 * The owner has now said this three times, and all three are recorded here
 * because two passes have already overshot in opposite directions.
 *
 * 1. On `15`: *"The rule of thumb is: darker border only for the
 *    draggable. Other normal borders should be the same border colour but
 *    a lighter variant or opacity of the dark colour — about 60%, a
 *    greyish."*
 * 2. On what `15` shipped: *"Still inconsistent — normal borders are dark
 *    grey so that the draggable borders stand out."*
 * 3. On what `16` shipped, pointing at the palette panel's right edge:
 *    *"This is a normal border — I asked opacity less, or light grey
 *    shade. Only the draggable border is correct."*
 *
 * **The second sentence is a report, not a specification, and `16` read it
 * as one.** It raised the normal weight 60% → 70% on the strength of it.
 * The first and third agree with each other and disagree with that
 * reading: the normal weight is the *light* one. So the value goes back to
 * the owner's own number.
 *
 * There is a floor as well as a ceiling. `15`'s first attempt failed the
 * other way — `--color-border-default` sat at 1.25:1 and read as absent —
 * so the job is the band between "competes with the draggable weight" and
 * "is not there". 60% of the ink over white is `#797877` at 4.41:1: a grey
 * line anybody can see, and nobody would call dark.
 *
 * **What `16` could not fix by moving alpha, and `17` fixes by moving
 * width.** Measured on the running app at `5f0b895`, the palette's right
 * edge was `2px` at 70% and the run dock's draggable edge was `2px` at
 * 100%. Two lines of the same width whose only difference is 30% of alpha
 * is a difference a reader measures rather than sees, which is why a third
 * complaint arrived about a token that was already the right one. So the
 * two weights now differ in **both** width and ink:
 *
 * - `--color-rule` at `--border-width-rule` — 2px, full ink, and **only a
 *   border a pointer can drag**. One pair, spent at three declarations
 *   across two files, asserted by site below.
 * - `--color-border` at `--border-width-hairline` — 1px, 60%. Every other
 *   structural line: a panel edge, a card outline, a divider, an input, a
 *   table rule, a chart hairline.
 * - `--color-border-emphasis` — 80%, interaction *state* only, never a
 *   resting border. Equal 20-point steps put it between the two, which is
 *   a rule a reader can check rather than three hand-picked numbers.
 *
 * **What this file does not try to settle.** A colour used to signal
 * something other than structural weight — danger, warning, focus, an
 * accent identity, a brand indicator, a chart mark's own ink — was never a
 * candidate for either of the two weights, and forcing one onto it would
 * be answering a question this ticket was not asked. Those are named
 * below, each with the argument for why it stays outside the two-weight
 * system, the same way `tokensDoNotDriftBack.test.ts` names its own
 * quarantine rather than writing a rule broad enough to wave at everything.
 *
 * **`15`'s `HELD` list is gone, and that is the deliverable rather than a
 * tidy-up.** It named nine `view/run/RunDock.css` rows parked because a
 * concurrent session owned that directory. That session landed `--rtl-rule`
 * — `color-mix(in srgb, var(--color-rule) 60%, transparent)`, a second
 * definition of `--color-border` built from a different base token because
 * neither session could edit the other's files. `16` deleted it, migrated
 * the dock onto the shared tokens, and emptied the list. Nothing is held.
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
  'border-block',
  'border-inline',
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
   * The three weights, as declared. A census can only say which names a
   * line spends; whether those names are *legible and distinguishable* is
   * a property of their values, and a value has no way to fail on its own.
   *
   * Measured, alpha-composited over the ground each weight actually sits
   * on (`--color-bg-surface` / `--color-bg-canvas`):
   *
   * | | light surface | light canvas | dark surface | dark canvas |
   * | --- | --- | --- | --- | --- |
   * | `--color-border` 60% | 4.41:1 | 4.32:1 | 6.33:1 | 6.62:1 |
   * | `--color-border-emphasis` 80% | 8.67:1 | 8.34:1 | 10.40:1 | 11.08:1 |
   * | `--color-rule` 100% | 16.60:1 | 15.66:1 | 15.71:1 | 17.25:1 |
   *
   * And the number the owner's rule is actually about — the step **between
   * the weights**, normal against draggable side by side: **3.77:1 light,
   * 2.48:1 dark**. Under `16`'s 70% it was 2.73:1 / 1.91:1, and the third
   * complaint arrived anyway, because that step was being asked to carry
   * the whole distinction on its own. It is not any more: the draggable
   * weight is also twice as wide.
   *
   * The floor is real and it is `15`'s own failure — a weight at 1.25:1
   * reads as absent. 4.41:1 is not near it. Nor is the low end of the
   * band: 50% would put the normal weight at 3.26:1 on white, and the
   * arithmetic ladder would stop being one.
   *
   * The hover step comes back with the value: 60% → 80% is 1.97:1 light /
   * 1.64:1 dark, against the 1.70:1 / 1.40:1 that `16`'s narrower range
   * cost. That was recorded as `16`'s price, and it is refunded here
   * rather than quietly forgotten.
   */
  it('declares the three weights as one ink at three strengths', () => {
    const theme = read(join(SRC, 'design/styles/theme.css'));
    const declared = (token: string): string =>
      (new RegExp(`${token}\\s*:\\s*([^;]+);`).exec(theme)?.[1] ?? '').replace(/\s+/g, ' ').trim();

    expect(declared('--color-border')).toBe(
      'color-mix(in srgb, var(--osg-divider) 60%, transparent)',
    );
    expect(declared('--color-border-emphasis')).toBe(
      'color-mix(in srgb, var(--osg-divider) 80%, transparent)',
    );
    expect(declared('--color-rule')).toBe('var(--osg-divider)');
  });

  /**
   * `15` kept `--color-border-subtle`, `-default` and `-strong` declared
   * because `view/run/` still spent them. Nothing does now, and a declared
   * token nothing spends is the shape `09` filed twenty-eight of: a name a
   * future author reaches for, believing it means something.
   */
  it('has retired the three roles it replaced, in both themes', () => {
    const theme = read(join(SRC, 'design/styles/theme.css'));
    for (const token of [
      '--color-border-subtle',
      '--color-border-default',
      '--color-border-strong',
    ]) {
      expect(code(theme)).not.toContain(token);
    }
    // Not only in CSS: the canvas sets SVG strokes to `var(--token)` from
    // TypeScript, where a dead name is a stroke that does not render.
    for (const path of filesUnder(SRC, ['.ts', '.tsx'])) {
      if (path.endsWith('.test.ts') || path.endsWith('.test.tsx')) continue;
      expect(read(path), under(path)).not.toMatch(/var\(--color-border-(subtle|default|strong)\)/);
    }
  });

  /**
   * The owner's sentence, as an assertion: *"the draggable border should
   * only be dark."* Full ink is spent in exactly two places and a pointer
   * can take hold of both — the run dock's lower edge, which
   * `.run-dock__grip` straddles with `cursor: ns-resize`, and the node
   * card's resize grip, which draws two edges.
   *
   * This replaces `view/run/oneBorderColourTwoWeights.test.ts`, which
   * asserted the same thing about the dock alone against a dock-local
   * token. Two censuses that can disagree is what `16` was filed to end;
   * the app-wide one is strictly the stronger statement, since it also
   * fails when a *fifth* declaration appears in a file the dock pin never
   * read.
   */
  const DRAGGABLE: ReadonlyArray<readonly [file: string, property: string]> = [
    ['view/nodes/NodeCard.css', 'border-right'],
    ['view/nodes/NodeCard.css', 'border-bottom'],
    ['view/run/RunDock.css', 'border-bottom'],
  ];

  it('spends full ink only where a pointer can drag', () => {
    const found = borderSites()
      .filter((s) => s.token === '--color-rule')
      .map((s) => `${s.file} ${s.property}`)
      .sort();
    expect(found).toEqual(DRAGGABLE.map(([file, property]) => `${file} ${property}`).sort());
  });

  /**
   * **The width half, which is `17`'s addition and the reason a third
   * complaint was needed to find it.**
   *
   * `16` asserted the ink and said nothing about the width, so the palette
   * edge could be — and was — a 2px line at 70% sitting beside a 2px line
   * at 100%. A census that measures only one of two values cannot see a
   * pair that has come apart. So the two are asserted together: every
   * declaration that spends full ink also spends rule width, and no
   * declaration anywhere else spends rule width.
   *
   * That is the whole two-weight system stated as one sentence a reader
   * can check — **2px full ink is draggable, 1px at 60% is everything
   * else** — and it is why `NodeCard.css`'s grip stopped writing `2px` as
   * a literal: a literal cannot be counted by the half of this pin that
   * counts the token.
   */
  it('gives the draggable weight one width as well as one ink', () => {
    const carrying = borderSites().filter((s) => s.token === '--color-rule');
    for (const site of carrying) {
      expect(site.value, `${site.file} ${site.property}`).toContain('var(--border-width-rule)');
    }
    const spending = [
      ...new Set(
        stylesheets().flatMap((path) =>
          [...read(path).matchAll(/--border-width-rule\)/g)].map(() => under(path)),
        ),
      ),
    ].sort();
    expect(spending).toEqual([...new Set(DRAGGABLE.map(([file]) => file))].sort());
  });

  it('leaves the grip and the dock edge actually draggable, not merely dark', () => {
    expect(read(join(SRC, 'view/nodes/NodeCard.css'))).toMatch(/cursor: nwse-resize/);
    expect(read(join(SRC, 'view/run/RunDock.css'))).toMatch(
      /\.run-dock__grip \{[^}]*cursor: ns-resize/s,
    );
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
    [
      '--color-bg-inverse',
      "the run dock's pressed transport button — its border is its own fill " +
        'reaching the edge so the control does not resize when pressed, not a line',
    ],
    [
      '--color-text-primary',
      "a timeline mark's own ink — the lane bar and the legend swatch that has to " +
        'match it, where the same token is also the fill (`.rtl__legend i[data-kind=model]`)',
    ],
    [
      '--color-text-quaternary',
      "an open-ended lane's mark — the dashed cap and the hatch behind it are one " +
        'value, deliberately faint because the lane never said it ended',
    ],
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

  it('leaves no border/outline/inset-ring colour outside the two weights or a named exception', () => {
    const allowed = new Set(['--color-border', '--color-rule']);
    const semantic = new Set(SEMANTIC_EXCEPTIONS.map(([token]) => token));
    const emphasisSites = new Set(EMPHASIS_SITES.map(([file, value]) => `${file} ${value}`));

    const violations = borderSites()
      .filter((s) => {
        if (allowed.has(s.token)) return false;
        if (semantic.has(s.token)) return false;
        if (/^rgba\(/.test(s.token)) return false; // named by site above
        if (s.token === '--color-border-emphasis')
          return !emphasisSites.has(`${s.file} ${s.value}`);
        return true;
      })
      .map((s) => `${s.file} ${s.property}: ${s.value} (${s.token})`);

    expect(violations).toEqual([]);
  });
});
