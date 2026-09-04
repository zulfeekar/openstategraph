import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';
import { contrastRatio } from '@view/overlays/contrastAudit';

/**
 * `stable-beta-public/02`. **Depth is a border and a ground, never a blur.**
 *
 * The owner, 2026-09-04, with Miro open beside the editor: *remove the
 * shadows and give a border, everywhere, except the draggable grip, whose
 * style is correct and stands out on purpose.*
 *
 * The census that ticket was filed on: **74 `box-shadow` declarations in 24
 * files**, none of them reached through a token — `--shadow-xs/sm/md/lg/xl`
 * and three node rings existed in `theme.css`, but half the sites wrote
 * `inset 0 0 0 1px var(--color-border)` by hand and the rest wrote a literal
 * (`0 18px 50px rgb(0 0 0 / 0.25)` under the graph preview, `0 1px 2px rgb(0
 * 0 0 / 6%)` under a selected chat tab). Two things were tangled together
 * under one property, and separating them is the whole fix:
 *
 * - **A ring flush with the box edge** — `inset 0 0 0 1px <colour>` — which
 *   is a border drawn by the wrong property. Forty-odd of them. Re-expressed
 *   as `border`, at the one hairline weight.
 * - **A drop shadow** — an offset, sometimes a blur — which is the thing the
 *   owner asked to be gone. Deleted, and what said "above" is now the
 *   opaque ground the layer paints plus that same hairline.
 *
 * **The grip turned out never to have used a shadow, and that is worth
 * recording rather than quietly discovering twice.** `.run-dock__grip`,
 * `.app-shell__column-grip` and `NodeCard`'s resize corner stand out with
 * 2px of full ink (`--color-rule` / `--color-primary`), the draggable weight
 * `aBorderIsDraggableOrItIsNot.test.ts` already pins. So the exception the
 * ticket names costs this file no allowance at all — the allowances below
 * are all rings — and the third test asserts the grips are still there,
 * still drawn without one.
 *
 * **What is allowed, and why it is not a shadow.** A focus ring is a ring:
 * `tokens.css`'s own focus-ring block names two mechanisms for one
 * appearance — an `outline` where focus lands on the element, a `box-shadow`
 * halo where it lands on a child — so taking the halo away would leave
 * inputs and selects with no focus indication at all. Every allowed value
 * below has **zero blur and zero offset**, which is the mechanical form of
 * "this is a ring, not a shadow", and that is asserted rather than trusted.
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

/**
 * Every `box-shadow` **declaration**, as written. Comments are stripped
 * first and the property name is matched exactly, so neither the prose above
 * nor a `transition: box-shadow …` is counted — a transition names a
 * property, it does not paint one.
 */
function shadowDeclarations(): ReadonlyArray<{ file: string; value: string }> {
  const out: { file: string; value: string }[] = [];
  for (const path of filesUnder(SRC, ['.css'])) {
    for (const match of code(read(path)).matchAll(/(^|[;{])\s*box-shadow\s*:\s*([^;{}]+);/g)) {
      out.push({ file: under(path), value: (match[2] ?? '').replace(/\s+/g, ' ').trim() });
    }
  }
  return out;
}

/**
 * The complete allowance, one row per declaration, each carrying the reason
 * it is not a drop shadow. A row is a `(file, value)` pair rather than a file
 * name, so a second declaration appearing in an already-listed file is a red
 * test — which is the failure mode a file-level allowlist cannot see.
 */
const ALLOWED: ReadonlyArray<readonly [file: string, value: string, why: string]> = [
  [
    'design/primitives/Field.css',
    '0 0 0 var(--focus-ring-width) var(--focus-ring-soft)',
    'the focus ring — `Field`’s focus lands on a child input, which is the case `tokens.css` says gets the halo mechanism rather than an `outline`',
  ],
  [
    'design/primitives/Field.css',
    '0 0 0 var(--focus-ring-width) var(--invalid-ring-soft)',
    'the same ring in its danger tint, so "focused" never paints over "wrong"',
  ],
  [
    'design/primitives/Select.css',
    '0 0 0 var(--focus-ring-width) var(--focus-ring-soft)',
    'the focus ring — same child-focus case as `Field`',
  ],
  [
    'design/primitives/Select.css',
    '0 0 0 var(--focus-ring-width) var(--invalid-ring-soft)',
    'the same ring in its danger tint',
  ],
  [
    'design/primitives/Slider.css',
    '0 0 0 3px color-mix(in srgb, var(--color-focus-ring) 30%, transparent)',
    'the focus ring on the thumb, which is a pseudo-element an `outline` cannot reach (WebKit)',
  ],
  [
    'design/primitives/Slider.css',
    '0 0 0 4px color-mix(in srgb, var(--accent-solid) 16%, transparent)',
    'the thumb’s pressed halo — the same ring geometry one step wider, on the same pseudo-element, and no blur',
  ],
  [
    'view/nodes/NodeCard.css',
    '0 0 0 var(--focus-ring-width) var(--focus-ring-soft)',
    'the focus ring on a repeatable row’s bare control, which has no `Field` to inherit one from',
  ],
  [
    'design/primitives/Indicators.css',
    '0 0 0 0 color-mix(in srgb, var(--color-status-running) 45%, transparent)',
    'the running status dot’s pulse, at rest — a ring that grows and fades, keyframed',
  ],
  [
    'design/primitives/Indicators.css',
    '0 0 0 3px color-mix(in srgb, var(--color-status-running) 0%, transparent)',
    'the same pulse at its widest, already fully transparent',
  ],
  [
    'design/primitives/Thinking.css',
    '0 0 0 0 color-mix(in srgb, var(--color-status-running) 45%, transparent)',
    'the thinking indicator’s pulse, at rest — the same ring as the status dot',
  ],
  [
    'design/primitives/Thinking.css',
    '0 0 0 3px color-mix(in srgb, var(--color-status-running) 0%, transparent)',
    'the same pulse at its widest',
  ],
  [
    'view/ask/AskPanel.css',
    'none',
    'draws nothing at all — it cancels `Field`’s focus halo inside a composer that states focus with a ground tint instead (`stable-beta-public/12`)',
  ],
];

describe('nothing in this product draws depth with a shadow', () => {
  it('finds the declarations, so the allowance below is not vacuous', () => {
    expect(shadowDeclarations().length).toBeGreaterThan(8);
  });

  it('allows a box-shadow only at a recorded ring, and nowhere else', () => {
    const allowed = new Set(ALLOWED.map(([file, value]) => `${file} :: ${value}`));
    const offenders = shadowDeclarations()
      .map((d) => `${d.file} :: ${d.value}`)
      .filter((row) => !allowed.has(row));
    expect(offenders).toEqual([]);
  });

  /** The other direction: a row kept here after its declaration is gone is a
   *  stale allowance, and a stale allowance is how the next drop shadow
   *  arrives without anybody noticing. */
  it('keeps no allowance for a declaration that no longer exists', () => {
    const present = new Set(shadowDeclarations().map((d) => `${d.file} :: ${d.value}`));
    const stale = ALLOWED.map(([file, value]) => `${file} :: ${value}`).filter(
      (row) => !present.has(row),
    );
    expect(stale).toEqual([]);
  });

  /**
   * The mechanical half of "a ring is not a shadow": `0 0 0 <spread>`. A
   * value with a non-zero offset or a non-zero blur is a shadow whatever the
   * reason beside it says, and would be admitted by the list above on the
   * strength of its prose alone. `none` is the one other shape allowed,
   * because it paints nothing.
   */
  it('lets every allowance be a ring — zero offset, zero blur', () => {
    for (const [file, value] of ALLOWED) {
      if (value === 'none') continue;
      expect(value, `${file} :: ${value}`).toMatch(
        /^0 0 0 (?:0|[\d.]+px|var\(--focus-ring-width\))(?:\s|$)/,
      );
    }
  });

  it('finds no inline shadow in a component either', () => {
    for (const path of filesUnder(SRC, ['.ts', '.tsx'])) {
      if (/\.test\.tsx?$/.test(path)) continue;
      expect(read(path), under(path)).not.toMatch(/boxShadow|dropShadow|drop-shadow/);
    }
  });
});

describe('the draggable grip is the exception, and it never needed a shadow', () => {
  const GRIPS: ReadonlyArray<readonly [file: string, selector: string]> = [
    ['view/run/RunDock.css', '.run-dock__grip'],
    ['view/AppShell.css', '.app-shell__column-grip'],
    ['view/nodes/NodeCard.css', '.node__resize'],
  ];

  it.each(GRIPS)('%s still declares %s', (file, selector) => {
    expect(code(read(join(SRC, file)))).toContain(`${selector} {`);
  });

  it('draws all three without a box-shadow', () => {
    const files = new Set(GRIPS.map(([file]) => file));
    const inGripFiles = shadowDeclarations().filter((d) => files.has(d.file));
    // The only shadow left in any of these three files is the repeatable
    // row's focus ring in `NodeCard.css`, allowed above and nothing to do
    // with a grip.
    expect(inGripFiles.map((d) => d.value)).toEqual([
      '0 0 0 var(--focus-ring-width) var(--focus-ring-soft)',
    ]);
  });
});

/* ---------------------------------------------------------------- *
 * The border that replaced them, measured.
 * ---------------------------------------------------------------- */

const TOKENS_CSS = code(read(join(SRC, 'design/styles/tokens.css')));
const THEME_CSS = code(read(join(SRC, 'design/styles/theme.css')));

function rulesWithSelector(css: string, matches: (selector: string) => boolean): string[] {
  const bodies: string[] = [];
  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (matches((match[1] ?? '').trim())) bodies.push(match[2] ?? '');
  }
  return bodies;
}

/** One theme's custom-property table, merged in the cascade order
 *  `index.css` actually loads — the same construction, and the same
 *  `exact`-selector care, `kanbanColumnContrastIsMeasured.test.ts` explains
 *  at length; only the tokens read at the end differ. */
function propertyTable(theme: 'light' | 'dark'): Map<string, string> {
  const table = new Map<string, string>();
  const merge = (body: string | undefined): void => {
    if (!body) return;
    for (const match of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)) {
      table.set(match[1] ?? '', (match[2] ?? '').trim());
    }
  };
  const exact = (selector: string) => (candidate: string) => candidate === selector;
  merge(rulesWithSelector(TOKENS_CSS, exact(':root'))[0]);
  if (theme === 'dark') {
    merge(rulesWithSelector(TOKENS_CSS, (s) => /\[data-theme=['"]?dark['"]?\]/.test(s))[0]);
  }
  // `theme.css`'s light block is selected as `:root, [data-theme='light']`,
  // and `:root` matches a dark page too — so in the real cascade it applies
  // in **both** themes and the dark block below overrides what it needs to.
  // Merging it for dark as well is therefore not a bug but the cascade: it
  // is where `--color-border` is declared, once, as a mix of an `--osg-`
  // ink that itself flips.
  merge(rulesWithSelector(THEME_CSS, (s) => /\[data-theme=['"]?light['"]?\]/.test(s))[0]);
  if (theme === 'dark') {
    merge(rulesWithSelector(THEME_CSS, exact("[data-theme='dark']"))[0]);
  }
  merge(rulesWithSelector(THEME_CSS, exact(':root'))[0]);
  return table;
}

function resolveVar(value: string, table: Map<string, string>): string {
  let current = value.trim();
  for (let step = 0; step < 20; step += 1) {
    const match = /^var\(\s*(--[a-z0-9-]+)\s*(?:,\s*([\s\S]+))?\)$/i.exec(current);
    if (!match) return current;
    const declared = match[1] ? table.get(match[1]) : undefined;
    if (declared !== undefined) {
      current = declared;
      continue;
    }
    if (match[2] !== undefined) {
      current = match[2].trim();
      continue;
    }
    throw new Error(`${match[1]} has no declaration in this theme`);
  }
  throw new Error(`var() chain did not resolve within 20 steps: ${value}`);
}

function toRgb(value: string): [number, number, number] {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value.trim());
  if (hex?.[1]) {
    const digits =
      hex[1].length === 3
        ? hex[1]
            .split('')
            .map((c) => c + c)
            .join('')
        : hex[1];
    return [
      Number.parseInt(digits.slice(0, 2), 16),
      Number.parseInt(digits.slice(2, 4), 16),
      Number.parseInt(digits.slice(4, 6), 16),
    ];
  }
  const rgb = /rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(value);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  throw new Error(`not a colour this test can read: ${value}`);
}

/**
 * `--color-border` is `color-mix(in srgb, var(--osg-divider) 60%, transparent)`
 * — a translucent line, so what a person sees is the ink composited over
 * whichever ground it is drawn on. Flattened here per channel, exactly as
 * `kanbanColumnContrastIsMeasured.test.ts` flattens its own rgba badges;
 * reading the raw mix instead would report a contrast nobody's screen shows.
 */
function borderOverGround(theme: 'light' | 'dark', groundToken: string): number {
  const table = propertyTable(theme);
  const declared = table.get('--color-border');
  if (declared === undefined) throw new Error('--color-border is not declared');
  const mix = /^color-mix\(in srgb,\s*(.+?)\s+([\d.]+)%,\s*transparent\)$/i.exec(declared);
  if (!mix) throw new Error(`--color-border is no longer a color-mix: ${declared}`);
  const ink = toRgb(resolveVar(mix[1] ?? '', table));
  const alpha = Number(mix[2]) / 100;
  const ground = toRgb(resolveVar(`var(${groundToken})`, table));
  const flattened = ink.map((c, i) => Math.round(c * alpha + (ground[i] ?? 0) * (1 - alpha)));
  const ratio = contrastRatio(`rgb(${flattened.join(', ')})`, `rgb(${ground.join(', ')})`);
  if (ratio === null) throw new Error('contrastRatio could not read these colours');
  return ratio;
}

/**
 * **The floor, and the argument for it.**
 *
 * WCAG has no criterion for a hairline that separates two surfaces: SC
 * 1.4.11 (3:1) governs a *graphical object needed to understand content*,
 * and a panel edge is not one — the panel is legible with no edge at all.
 * So the number is a legibility floor rather than a conformance bar, and the
 * ticket names it: **1.5:1**, the point below which a 1px line stops reading
 * as a line. It is not invented here either — `the-look-has-an-author-now/15`
 * shipped a border at **1.25:1** and the owner reported it as *absent*, which
 * is the only direct evidence this product has about where the floor is.
 *
 * Every measurement below clears it by more than a factor of two, in both
 * themes, which is the answer to the question the shadows used to beg: a
 * hairline alone is enough to hold an edge, so nothing has to be lifted off
 * the page to be seen.
 */
describe('the hairline that replaced the shadows is legible on every ground', () => {
  const FLOOR = 1.5;

  const GROUNDS: ReadonlyArray<readonly [theme: 'light' | 'dark', ground: string]> = [
    ['light', '--color-bg-canvas'],
    ['light', '--color-bg-surface'],
    ['light', '--color-bg-surface-raised'],
    ['light', '--color-bg-surface-sunken'],
    ['dark', '--color-bg-canvas'],
    ['dark', '--color-bg-surface'],
    ['dark', '--color-bg-surface-raised'],
    ['dark', '--color-bg-surface-sunken'],
  ];

  it.each(GROUNDS)('--color-border on %s %s clears the 1.5:1 floor', (theme, ground) => {
    expect(borderOverGround(theme, ground)).toBeGreaterThanOrEqual(FLOOR);
  });

  /**
   * The measured table, asserted to one decimal so it is a record rather
   * than a range. The worst case is the light canvas at 4.32:1 — the ground
   * a node card sits on, and the thinnest line in the product.
   */
  it('measures the same numbers this file reports', () => {
    const at = (theme: 'light' | 'dark', ground: string): number =>
      Math.round(borderOverGround(theme, ground) * 100) / 100;
    expect(at('light', '--color-bg-canvas')).toBeCloseTo(4.32, 1);
    expect(at('light', '--color-bg-surface')).toBeCloseTo(4.41, 1);
    expect(at('dark', '--color-bg-canvas')).toBeCloseTo(6.62, 1);
    expect(at('dark', '--color-bg-surface')).toBeCloseTo(6.33, 1);
  });
});
