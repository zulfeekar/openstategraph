import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The instrument for `the-look-has-an-author-now/14`: the palette's hint
 * paragraph ran wider than the search field above it and the section blocks
 * below it, and the Ask panel's message list rendered one column of content
 * at three or four different left edges — a bubble flush to the raw panel
 * edge, an error row whose icon hung outside where every other row's text
 * started, a "New conversation" divider at yet another inset. In both
 * panels the root cause was the same shape: most rows carried the column's
 * horizontal inset themselves (`var(--space-3)`, the same token
 * `panel-section` in `Panel.css` already uses), and one or two did not.
 *
 * **What this file checks, and what it deliberately does not.** A census
 * over every `padding`/`margin` in these two stylesheets would flag dozens
 * of legitimate declarations that have nothing to do with a column edge — a
 * badge's own text padding, a bubble's own content padding, a nested
 * reply's own indent. Those are content-relative or a documented "indent a
 * child under its row" pattern, not a competing left/right edge of the
 * scrolling column. So the check below is narrowed the way this repo's own
 * censuses are narrowed (see `tokensDoNotDriftBack.test.ts`'s docstring):
 *
 * - **Padding never draws a column edge here.** Every class that puts a
 *   real box on screen (declares its own `border` or `background`) may pad
 *   its content however the content needs — the box's own edge already IS
 *   the row's edge, and there is nothing left for its padding to
 *   contradict. The same is true one BEM step further in (`ask__tool-name`
 *   inside the boxed `ask__tool`): that padding styles the inside of a box
 *   it does not itself draw. Outside of that, a horizontal padding is
 *   checked exactly like a margin below.
 * - **Margin always draws a column edge**, box or not — a margin is a
 *   distance from the parent, which in this column IS the edge in
 *   question. So every horizontal margin declared by a class under `ask__`
 *   or `palette` is checked, with two small, named, argued exceptions
 *   (`NESTED_INDENT_MARGIN`, `INLINE_TRAILING_MARGIN` below) rather than a
 *   pattern that would swallow a real regression along with them.
 * - **The container that owns the inset is excluded from the row census**
 *   and checked positively instead (`declares the canonical inset`,
 *   below) — a row and the frame around all the rows are different
 *   questions, and conflating them either lets the frame's supplemental
 *   scrollbar padding fail the row check or lets a missing frame padding
 *   hide behind "well, no row added its own."
 *
 * None of this walks the TSX, so it cannot tell a genuinely new, isolated
 * one-off badge from a new row of the scrolling column — anything matching
 * `ask__`/`palette` is in scope. That is a recorded gap, not a claim of
 * completeness: a false failure here still means opening this file and
 * reading why, which is cheaper than the four-edges defect this file exists
 * to catch going unnoticed again.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const read = (relative: string): string => readFileSync(SRC + relative, 'utf8');

const PALETTE_CSS = read('view/palette/Palette.css');
const ASK_CSS = read('view/ask/AskPanel.css');

/** The one horizontal inset both panels' columns share. */
const CANONICAL = 'var(--space-3)';

function stripCss(css: string): string {
  const noComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  // `@media (query) {\n  .rule { … }\n}\n` — the outer brace sits alone at
  // column 0 in every stylesheet this file reads, so `\n}\n` finds it and
  // not one of the indented inner rule braces.
  return noComments.replace(/@media[^{]*\{[\s\S]*?\n\}\n/g, '');
}

interface Rule {
  readonly selector: string;
  readonly decls: Readonly<Record<string, string>>;
}

function parseRules(css: string): Rule[] {
  const rules: Rule[] = [];
  for (const m of stripCss(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = (m[1] ?? '').trim();
    const decls: Record<string, string> = {};
    for (const d of (m[2] ?? '').matchAll(/([-a-zA-Z]+)\s*:\s*([^;]+);/g)) {
      decls[d[1] ?? ''] = (d[2] ?? '').trim();
    }
    rules.push({ selector, decls });
  }
  return rules;
}

const classesIn = (selector: string): string[] =>
  [...selector.matchAll(/\.([a-zA-Z0-9_-]+)/g)].map((m) => m[1] ?? '');

/** Every declaration this stylesheet makes for a class, merged across every
 *  rule whose FIRST class token is this one — covers `:hover`, `:disabled`
 *  and compound-selector variants of the same element. */
function declsForClass(rules: readonly Rule[], cls: string): Record<string, string> {
  const merged: Record<string, string> = {};
  for (const r of rules) {
    if (classesIn(r.selector)[0] === cls) Object.assign(merged, r.decls);
  }
  return merged;
}

function declsForSelector(rules: readonly Rule[], selector: string): Record<string, string> {
  const merged: Record<string, string> = {};
  for (const r of rules) {
    if (r.selector === selector) Object.assign(merged, r.decls);
  }
  return merged;
}

const isBoxed = (decls: Readonly<Record<string, string>>): boolean =>
  Object.keys(decls).some((p) => /^background/.test(p) || (/^border/.test(p) && !/radius/.test(p)));

function splitTopLevel(value: string): string[] {
  const tokens: string[] = [];
  let depth = 0;
  let cur = '';
  for (const ch of value) {
    if (ch === '(') depth += 1;
    if (ch === ')') depth -= 1;
    if (ch === ' ' && depth === 0) {
      if (cur) tokens.push(cur);
      cur = '';
    } else {
      cur += ch;
    }
  }
  if (cur) tokens.push(cur);
  return tokens;
}

/** The left/right components of a box-model shorthand, by CSS's own
 *  1/2/3/4-value rule (2 and 3 values share the same horizontal token). */
function horizontalOf(value: string): { left: string; right: string } {
  const t = splitTopLevel(value);
  if (t.length <= 1) return { left: t[0] ?? '0', right: t[0] ?? '0' };
  if (t.length <= 3) return { left: t[1] ?? '0', right: t[1] ?? '0' };
  return { left: t[3] ?? '0', right: t[1] ?? '0' };
}

function horizontalMargin(decls: Readonly<Record<string, string>>): {
  left: string;
  right: string;
} {
  let left = '0';
  let right = '0';
  if (decls.margin) ({ left, right } = horizontalOf(decls.margin));
  if (decls['margin-left']) left = decls['margin-left'];
  if (decls['margin-right']) right = decls['margin-right'];
  return { left, right };
}

function horizontalPadding(decls: Readonly<Record<string, string>>): {
  left: string;
  right: string;
} {
  let left = '0';
  let right = '0';
  if (decls.padding) ({ left, right } = horizontalOf(decls.padding));
  if (decls['padding-left']) left = decls['padding-left'];
  if (decls['padding-right']) right = decls['padding-right'];
  return { left, right };
}

/** True for a class that either draws its own box, or is a further BEM
 *  refinement of a class in this same file that does (`ask__tool-name`
 *  under the boxed `ask__tool`). Its padding styles the inside of a box —
 *  the box's own edge is the row's edge, so the padding is never in
 *  competition with a sibling row's inset. */
function boxedOrNestedInBoxed(cls: string, boxedRoots: ReadonlySet<string>): boolean {
  if (boxedRoots.has(cls)) return true;
  for (const root of boxedRoots) {
    if (cls !== root && cls.startsWith(root) && /^[-_]/.test(cls.slice(root.length))) return true;
  }
  return false;
}

/**
 * Every one of these pairs a `margin-left` with a `border-left` in the same
 * rule: a spawned child, a nested reply, a trace step's own output are
 * drawn one rung further in than the row that owns them, and the border is
 * the rung marker. Documented at the declaration itself
 * (`src/view/ask/AskPanel.css`) — this is a second, deliberate vocabulary
 * ("indent a child under its parent row"), not a competing column edge.
 */
const NESTED_INDENT_MARGIN_LEFT: ReadonlySet<string> = new Set([
  'ask__activity-row--child',
  'ask__activity-row--spawn',
  'ask__trace-output',
]);

/**
 * `ask__spawned-label`'s `margin-right` is the gap between a label and the
 * row of pills that follow it on the SAME line — an inter-element gap, not
 * a right column edge. The one instance of this shape in either file today.
 */
const INLINE_TRAILING_MARGIN_RIGHT: ReadonlySet<string> = new Set(['ask__spawned-label']);

/** The container that already carries the column's canonical inset — a
 *  row is checked against it (below), not folded into the row census. */
const CONTAINER_CLASSES: ReadonlySet<string> = new Set(['ask__thread']);

function marginViolations(css: string, prefix: RegExp): string[] {
  const rules = parseRules(css);
  const classes = [...new Set(rules.flatMap((r) => classesIn(r.selector)))].filter((c) =>
    prefix.test(c),
  );
  const bad: string[] = [];
  for (const cls of classes) {
    if (CONTAINER_CLASSES.has(cls)) continue;
    const { left, right } = horizontalMargin(declsForClass(rules, cls));
    const allowed = (v: string) => v === '0' || v === 'auto' || v === CANONICAL;
    if (!allowed(left) && !NESTED_INDENT_MARGIN_LEFT.has(cls)) {
      bad.push(`${cls} margin-left: ${left}`);
    }
    if (!allowed(right) && !INLINE_TRAILING_MARGIN_RIGHT.has(cls)) {
      bad.push(`${cls} margin-right: ${right}`);
    }
  }
  return bad;
}

function paddingViolations(css: string, prefix: RegExp): string[] {
  const rules = parseRules(css);
  const classes = [...new Set(rules.flatMap((r) => classesIn(r.selector)))].filter((c) =>
    prefix.test(c),
  );
  const boxedRoots = new Set(classes.filter((c) => isBoxed(declsForClass(rules, c))));
  const bad: string[] = [];
  for (const cls of classes) {
    if (CONTAINER_CLASSES.has(cls)) continue;
    if (boxedOrNestedInBoxed(cls, boxedRoots)) continue;
    const { left, right } = horizontalPadding(declsForClass(rules, cls));
    const allowed = (v: string) => v === '0' || v === CANONICAL;
    if (!allowed(left)) bad.push(`${cls} padding-left: ${left}`);
    if (!allowed(right)) bad.push(`${cls} padding-right: ${right}`);
  }
  return bad;
}

describe('a panel column has one left edge and one right edge', () => {
  it('no palette row declares its own non-canonical horizontal margin', () => {
    expect(marginViolations(PALETTE_CSS, /^palette/)).toEqual([]);
  });

  it('no palette row declares its own non-canonical horizontal padding, box content aside', () => {
    expect(paddingViolations(PALETTE_CSS, /^palette/)).toEqual([]);
  });

  it('no ask row declares its own non-canonical horizontal margin', () => {
    expect(marginViolations(ASK_CSS, /^ask__/)).toEqual([]);
  });

  it('no ask row declares its own non-canonical horizontal padding, box content aside', () => {
    expect(paddingViolations(ASK_CSS, /^ask__/)).toEqual([]);
  });

  /**
   * The positive half. A census that only forbids drift would stay green
   * the day somebody deletes the fix outright — the palette's rows losing
   * their own inset (as `palette-howto` did) or the Ask column's container
   * losing its padding (as it always had, until this ticket) both leave
   * every row at an equally-wrong, equally-consistent zero.
   */
  describe('the canonical inset is actually declared where each panel expects it', () => {
    const paletteRules = parseRules(PALETTE_CSS);
    const askRules = parseRules(ASK_CSS);

    it.each(['palette-group-label', 'palette-footnote'])(
      '%s carries the column inset itself, as padding — Palette has no padded ancestor',
      (cls) => {
        const { left, right } = horizontalPadding(declsForClass(paletteRules, cls));
        expect({ left, right }).toEqual({ left: CANONICAL, right: CANONICAL });
      },
    );

    it('palette-howto carries the column inset itself, as margin — Palette has no padded ancestor', () => {
      const { left, right } = horizontalMargin(declsForClass(paletteRules, 'palette-howto'));
      expect({ left, right }).toEqual({ left: CANONICAL, right: CANONICAL });
    });

    it('palette-warnings carries the column inset as margin — it draws its own box', () => {
      const { left, right } = horizontalMargin(declsForClass(paletteRules, 'palette-warnings'));
      expect({ left, right }).toEqual({ left: CANONICAL, right: CANONICAL });
    });

    it('the Ask column’s shared body declares the canonical inset once, for every row', () => {
      const { left, right } = horizontalPadding(declsForSelector(askRules, '.ask .panel__body'));
      expect({ left, right }).toEqual({ left: CANONICAL, right: CANONICAL });
    });
  });
});
