import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { contrastRatio } from '@view/overlays/contrastAudit';
import { BOARD_COLUMNS } from '@view/board/patrolBoardModel';

/**
 * `kanban-patrol/04`. The owner's words are settled (see the ticket's own
 * "Owner decision" section); this is the half that was still an assertion
 * rather than a number — *"make sure the contrast of existing tones works
 * well on dark mode as well"*, unmeasured.
 *
 * This resolves the **real** custom-property chain out of the checked-in
 * stylesheets — `tokens.css`'s primitives, `theme.css`'s semantic layer, both
 * themes — the same idiom `anAccentBadgeHasAColourOffCanvas.test.ts` and
 * `primaryContrast.test.ts` already use one level down, extended to chase a
 * `var()` reference to its literal value rather than reading one token deep.
 * A wrong resolution produces a false contrast number, which the ticket calls
 * worse than no number at all — so every step below is either a direct read
 * of a stylesheet or a small, tested pure function, never a guess.
 *
 * **Two surfaces, matching the ticket's own list:**
 * - The column **header** — `Badge`'s own background/text, self-painted, so
 *   its contrast is intrinsic to the badge and does not depend on what is
 *   behind it (`.badge--*` in `Indicators.css`).
 * - The in-card **status dot** — a filled circle with no background of its
 *   own, so its contrast is against whatever it actually sits on:
 *   `.patrol-card`'s background (`PatrolBoard.css`).
 *
 * **Which threshold applies to which, and why — WCAG 2.x, AA level:**
 * - **SC 1.4.3 (Contrast Minimum), 4.5:1** — ordinary text. The badge's
 *   content is a number set in `--type-label`
 *   (`var(--font-weight-semibold) var(--font-size-10)` — 10px, 600 weight),
 *   nowhere near the "large text" carve-out (24px, or 18.66px bold), so the
 *   ordinary 4.5:1 bar applies with no exception.
 * - **SC 1.4.11 (Non-text Contrast), 3:1** — "user interface components and
 *   graphical objects". A status dot carries no text at all; it is a
 *   graphical object standing in for a state, so it is held to 1.4.11's
 *   bar rather than 1.4.3's. This is the "large text/graphical objects"
 *   allowance the ticket names, cited to its own success criterion rather
 *   than asserted.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url));
const read = (relative: string): string =>
  readFileSync(HERE + relative, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

const TOKENS_CSS = read('tokens.css');
const THEME_CSS = read('theme.css');
const INDICATORS_CSS = readFileSync(
  fileURLToPath(new URL('../primitives/Indicators.css', import.meta.url)),
  'utf8',
).replace(/\/\*[\s\S]*?\*\//g, '');
const PATROL_BOARD_CSS = readFileSync(
  fileURLToPath(new URL('../../view/board/PatrolBoard.css', import.meta.url)),
  'utf8',
).replace(/\/\*[\s\S]*?\*\//g, '');

/**
 * Every top-level rule's selector and body — the exact idiom
 * `anAccentBadgeHasAColourOffCanvas.test.ts` already uses, not nested-brace
 * aware beyond the one level every file here actually needs (comments are
 * already stripped above, which is where a stray brace in prose could
 * otherwise desync this).
 */
function rulesWithSelector(
  css: string,
  selectorPattern: { test(selector: string): boolean },
): string[] {
  const bodies: string[] = [];
  const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
  let match: RegExpExecArray | null;
  while ((match = ruleRe.exec(css))) {
    const selector = (match[1] ?? '').trim();
    if (selectorPattern.test(selector)) bodies.push(match[2] ?? '');
  }
  return bodies;
}

/** `name: value;` pairs out of one rule body — custom properties only. */
function customProperties(body: string): Map<string, string> {
  const map = new Map<string, string>();
  const declRe = /(--[a-z0-9-]+)\s*:\s*([^;]+);/gi;
  let match: RegExpExecArray | null;
  while ((match = declRe.exec(body))) {
    const name = match[1];
    const value = match[2];
    if (name && value) map.set(name, value.trim());
  }
  return map;
}

/** One ordinary (non-custom) property's value out of one rule body. */
function property(body: string, name: string): string | undefined {
  const declRe = new RegExp(`(?:^|;)\\s*${name}\\s*:\\s*([^;]+);`, 'i');
  return declRe.exec(body)?.[1]?.trim();
}

/**
 * Builds a full theme's custom-property table, in cascade order — later
 * merges win, matching how the browser would resolve the same selectors
 * against the real `<html>` element. `index.css` loads `tokens.css` then
 * `theme.css`, in that order, and within `theme.css` the plain `:root`
 * accent-default block sits **after** the `[data-theme='dark']` block in
 * source order — both are read here in exactly that order, verified against
 * the real files rather than assumed.
 */
function propertyTable(theme: 'light' | 'dark'): Map<string, string> {
  const table = new Map<string, string>();
  const merge = (body: string | undefined) => {
    if (!body) return;
    for (const [name, value] of customProperties(body)) table.set(name, value);
  };

  // A selector matched by its exact trimmed text — `:root` alone, never the
  // combined `:root, [data-theme='light']` selector, which also *contains*
  // the substring `:root` and would otherwise re-merge the light semantic
  // block back on top of the dark one in the loop below. This bug was real,
  // caught by the "Needs You" dark-mode assertion below before this comment
  // was written: `--color-danger-subtle` measured as its *light* value
  // (`#fde8e4`) while the theme under test was dark, because the generic
  // `:root`-substring pattern first tried here matched both blocks.
  const exact = (selector: string) => (candidate: string) => candidate.trim() === selector;
  const contains = (needle: RegExp) => (candidate: string) => needle.test(candidate);

  // tokens.css :root — theme-independent primitives, always in scope.
  merge(rulesWithSelector(TOKENS_CSS, { test: exact(':root') })[0]);
  if (theme === 'dark') {
    // tokens.css [data-theme='dark'] — the small `--osg-*` override set.
    merge(
      rulesWithSelector(TOKENS_CSS, {
        test: contains(/\[data-theme=['"]?dark['"]?\]/),
      })[0],
    );
  }
  // theme.css's tier-2 semantic layer, one theme's block only — the two
  // blocks never both match one `<html>` element, so only one is merged.
  if (theme === 'light') {
    merge(
      rulesWithSelector(THEME_CSS, {
        test: contains(/\[data-theme=['"]?light['"]?\]/),
      })[0],
    );
  } else {
    // The *exact* dark selector, not a substring test — `theme.css` also
    // carries `[data-theme='dark'] [data-accent='blue']` and its seven
    // siblings, which contain the same substring and must not be read here:
    // none of them apply without a `data-accent` attribute this board never
    // sets (verified against `PatrolColumn.tsx`/`PatrolCard.tsx`).
    merge(
      rulesWithSelector(THEME_CSS, {
        test: exact("[data-theme='dark']"),
      })[0],
    );
  }
  // theme.css's unconditional `:root` accent defaults — `kanban-patrol/14`.
  // Matches in both themes and, in the real cascade, comes after the dark
  // block above; nothing it declares conflicts with the dark block's own
  // names, so simple last-merge-wins reproduces the real result. `exact`,
  // not a substring test — see the comment at the top of this function for
  // the bug that taught this.
  merge(rulesWithSelector(THEME_CSS, { test: exact(':root') })[0]);
  return table;
}

/**
 * Chases a `var(--name)` reference to a literal colour, through as many
 * indirections as the real chain needs — `--color-danger` →
 * `--osg-node-error` → `--osg-accent-700` is three deep on its own. A bounded
 * loop rather than unbounded recursion, so a genuine cycle in the
 * stylesheet is a thrown error here rather than a stack overflow that looks
 * like an unrelated crash.
 */
function resolveVar(value: string, table: Map<string, string>): string {
  let current = value.trim();
  for (let step = 0; step < 20; step += 1) {
    const match = /^var\(\s*(--[a-z0-9-]+)\s*(?:,\s*([\s\S]+))?\)$/i.exec(current);
    if (!match) return current;
    const [, name, fallback] = match;
    const declared = name ? table.get(name) : undefined;
    if (declared !== undefined) {
      current = declared;
      continue;
    }
    if (fallback !== undefined) {
      current = fallback.trim();
      continue;
    }
    throw new Error(`${name} has no declaration in this theme's table and no fallback`);
  }
  throw new Error(`var() chain did not resolve to a literal within 20 steps: ${value}`);
}

/** `rgba(r, g, b, a)` → `[r, g, b, a]`, or `null` for anything else. */
function parseRgba(value: string): [number, number, number, number] | null {
  const match = /rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)/i.exec(
    value,
  );
  if (!match) return null;
  const [, r, g, b, a] = match;
  let alpha = 1;
  if (a !== undefined) alpha = a.endsWith('%') ? Number(a.slice(0, -1)) / 100 : Number(a);
  return [Number(r), Number(g), Number(b), alpha];
}

/**
 * Flattens a possibly-transparent colour onto an opaque one beneath it —
 * standard alpha "over" compositing, per channel. Needed because
 * `--color-primary-subtle` and `--color-danger-subtle` are **not** opaque in
 * dark mode (`rgba(…, 0.14)`), unlike their light-mode counterparts (solid
 * hex) — a badge painted with either sits on `.patrol-column__head`'s own
 * background, and the rendered colour a person actually sees is the blend,
 * not the raw rgba channel values. Skipping this step would understate how
 * much of the header's ground shows through and report a contrast number for
 * a colour nobody's screen ever shows.
 */
function flatten(foreground: string, backgroundHex: string): string {
  const fg = parseRgba(foreground);
  if (!fg) return foreground; // already opaque — hex, or rgb() with no alpha
  const [fr, fg_, fb, alpha] = fg;
  if (alpha >= 1) return `rgb(${fr}, ${fg_}, ${fb})`;
  const bg = parseRgba(backgroundHex) ?? hexToRgb(backgroundHex);
  if (!bg) throw new Error(`background ${backgroundHex} is not a colour this test can parse`);
  const [br, bgG, bb] = bg;
  const r = fr * alpha + br * (1 - alpha);
  const g = fg_ * alpha + bgG * (1 - alpha);
  const b = fb * alpha + bb * (1 - alpha);
  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

function hexToRgb(hex: string): [number, number, number, number] | null {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!match?.[1]) return null;
  const digits =
    match[1].length === 3
      ? match[1]
          .split('')
          .map((c) => c + c)
          .join('')
      : match[1];
  return [
    Number.parseInt(digits.slice(0, 2), 16),
    Number.parseInt(digits.slice(2, 4), 16),
    Number.parseInt(digits.slice(4, 6), 16),
    1,
  ];
}

/** One theme's resolved colour for a custom property, opaque already. */
function resolveOpaque(name: string, table: Map<string, string>): string {
  const raw = table.get(name);
  if (raw === undefined) throw new Error(`${name} is not declared in this theme`);
  const resolved = resolveVar(raw, table);
  const rgba = parseRgba(resolved);
  if (rgba && rgba[3] < 1) {
    throw new Error(`${name} resolved to a transparent colour (${resolved}) — flatten it first`);
  }
  return resolved;
}

/* -------------------------------------------------------------------- *
 * The four `Badge` tones' own background + text, as `Indicators.css`
 * actually declares them — `tone !== 'neutral'` gets no `badge--${tone}`
 * class (`Indicators.tsx`), so the neutral case reads the base `.badge`
 * rule rather than a `.badge--neutral` that does not exist.
 * -------------------------------------------------------------------- */

const BADGE_TONE_PROPERTIES: Record<
  'neutral' | 'accent' | 'success' | 'danger',
  {
    background: string;
    color: string;
  }
> = (() => {
  const base = rulesWithSelector(INDICATORS_CSS, /^\.badge$/)[0];
  const accent = rulesWithSelector(INDICATORS_CSS, /^\.badge--accent$/)[0];
  const success = rulesWithSelector(INDICATORS_CSS, /^\.badge--success$/)[0];
  const danger = rulesWithSelector(INDICATORS_CSS, /^\.badge--danger$/)[0];
  const props = (body: string | undefined, label: string) => {
    const background = property(body ?? '', 'background');
    const color = property(body ?? '', 'color');
    if (!background || !color) throw new Error(`could not read background+color for ${label}`);
    return { background, color };
  };
  return {
    neutral: props(base, '.badge'),
    accent: props(accent, '.badge--accent'),
    success: props(success, '.badge--success'),
    danger: props(danger, '.badge--danger'),
  };
})();

/* -------------------------------------------------------------------- *
 * The four `StatusDot` tones the board actually uses, and what a card
 * renders behind them.
 * -------------------------------------------------------------------- */

const DOT_TONE_BACKGROUND: Record<'idle' | 'error' | 'running' | 'success', string> = (() => {
  // `.status-dot` (the base rule) carries the idle colour; `tone !== 'idle'`
  // is the only case that gets a `status-dot--${tone}` modifier
  // (`Indicators.tsx`), same asymmetry as `.badge`/`.badge--*` above.
  const base = rulesWithSelector(INDICATORS_CSS, /^\.status-dot$/)[0];
  const running = rulesWithSelector(INDICATORS_CSS, /^\.status-dot--running$/)[0];
  const success = rulesWithSelector(INDICATORS_CSS, /^\.status-dot--success$/)[0];
  const error = rulesWithSelector(INDICATORS_CSS, /^\.status-dot--error$/)[0];
  const bg = (body: string | undefined, label: string) => {
    const background = property(body ?? '', 'background');
    if (!background) throw new Error(`could not read background for ${label}`);
    return background;
  };
  return {
    idle: bg(base, '.status-dot'),
    running: bg(running, '.status-dot--running'),
    success: bg(success, '.status-dot--success'),
    error: bg(error, '.status-dot--error'),
  };
})();

const COLUMN_HEADER_BG = property(
  rulesWithSelector(PATROL_BOARD_CSS, /^\.patrol-column__head$/)[0] ?? '',
  'background',
);
const CARD_BG = property(
  rulesWithSelector(PATROL_BOARD_CSS, /^\.patrol-card$/)[0] ?? '',
  'background',
);
if (!COLUMN_HEADER_BG || !CARD_BG) {
  throw new Error('could not read .patrol-column__head or .patrol-card background');
}

/* -------------------------------------------------------------------- *
 * The measurement itself.
 * -------------------------------------------------------------------- */

const TEXT_MINIMUM = 4.5; // WCAG AA, SC 1.4.3 — the badge's number is 10px text.
const GRAPHICAL_MINIMUM = 3; // WCAG AA, SC 1.4.11 — the dot has no text at all.

/**
 * The three real failures `kanban-patrol/04`'s 2026-09-02 measurement found
 * are fixed, per its follow-up resolution — see that ticket for the
 * before/after numbers and why each fix is a re-tuned existing token rather
 * than a new one:
 *
 * - `Detected`'s in-card dot (both themes) — `--osg-node-idle` was
 *   `--osg-neutral-300`, designed as a *hollow ring* on the graph canvas and
 *   never measured as a small filled dot on a card (1.43:1 light, 1.91:1
 *   dark). Re-pointed to the existing `--neutral-500` step of the same
 *   derived ink ramp — still "idle grey", just the shade of it that clears
 *   SC 1.4.11's 3:1 floor against both a white and a near-black card.
 * - `Resolved`'s header badge, dark theme — `.badge--success` read
 *   `--color-primary` as its *text* colour, which is the same token tuned as
 *   a *fill* under white text elsewhere and 2.38:1 as ink on its own dark
 *   tint. `--color-text-success` already exists for exactly this
 *   fill-vs-ink distinction (`theme.css`'s own comment on the token) and is
 *   identical to `--color-primary` in light mode, so light is untouched.
 *
 * Nothing remains in `KNOWN_GAPS` — every surface below is now held to its
 * real WCAG AA floor.
 */
const KNOWN_GAPS = new Set<string>([]);

interface Row {
  column: string;
  theme: 'light' | 'dark';
  headerRatio: number;
  dotRatio: number;
}

const rows: Row[] = [];

describe.each(['light', 'dark'] as const)('kanban board contrast — %s theme', (theme) => {
  const table = propertyTable(theme);
  const surfaceBg = resolveOpaque(COLUMN_HEADER_BG.replace(/^var\((.+)\)$/, '$1'), table);
  const cardBg = resolveOpaque(CARD_BG.replace(/^var\((.+)\)$/, '$1'), table);

  it.each(BOARD_COLUMNS)('$label — header badge ($tone) and in-card dot ($dot)', (column) => {
    const badge = BADGE_TONE_PROPERTIES[column.tone];
    const badgeBgRaw = resolveVar(badge.background, table);
    const badgeFgRaw = resolveVar(badge.color, table);
    const badgeBg = flatten(badgeBgRaw, surfaceBg);
    const badgeFg = flatten(badgeFgRaw, surfaceBg);
    const headerRatio = contrastRatio(badgeBg, badgeFg);

    const dotTone = column.dot as 'idle' | 'error' | 'running' | 'success';
    const dotColorRaw = resolveVar(DOT_TONE_BACKGROUND[dotTone], table);
    const dotColor = flatten(dotColorRaw, cardBg);
    const dotRatio = contrastRatio(dotColor, cardBg);

    expect(headerRatio, `${column.label} header badge (${theme})`).not.toBeNull();
    expect(dotRatio, `${column.label} in-card dot (${theme})`).not.toBeNull();

    rows.push({
      column: column.label,
      theme,
      headerRatio: headerRatio ?? 0,
      dotRatio: dotRatio ?? 0,
    });

    const headerGap = KNOWN_GAPS.has(`${column.label}|${theme}|header`);
    const dotGap = KNOWN_GAPS.has(`${column.label}|${theme}|dot`);

    if (headerGap) {
      // A recorded, open finding — not a passing number and not silently
      // dropped. If this ever exceeds the floor, the assertion below fails
      // and the line moves out of `KNOWN_GAPS`, which is the point: closing
      // the gap is required to make this pass again, not just convenient.
      expect(
        headerRatio ?? 0,
        `${column.label} header badge in ${theme} mode is a known, escalated gap`,
      ).toBeLessThan(TEXT_MINIMUM);
    } else {
      expect(
        headerRatio ?? 0,
        `${column.label} header badge in ${theme} mode: ${badgeBg} on ${badgeFg} = ` +
          `${(headerRatio ?? 0).toFixed(2)}:1, needs ${TEXT_MINIMUM}:1`,
      ).toBeGreaterThanOrEqual(TEXT_MINIMUM);
    }

    if (dotGap) {
      expect(
        dotRatio ?? 0,
        `${column.label} in-card dot in ${theme} mode is a known, escalated gap`,
      ).toBeLessThan(GRAPHICAL_MINIMUM);
    } else {
      expect(
        dotRatio ?? 0,
        `${column.label} in-card dot in ${theme} mode: ${dotColor} on ${cardBg} = ` +
          `${(dotRatio ?? 0).toFixed(2)}:1, needs ${GRAPHICAL_MINIMUM}:1`,
      ).toBeGreaterThanOrEqual(GRAPHICAL_MINIMUM);
    }
  });
});

describe('the full measured table', () => {
  it('prints every column x theme x surface, as real numbers', () => {
    // Nothing asserted here beyond "the rows exist" — this test exists so a
    // reader running the suite sees the actual table printed, which is the
    // whole point of `04`: a recorded number, not a good-faith claim.
    // `console.info` rather than a snapshot: the ticket asks for the numbers
    // to be seen, not frozen against the next re-tint.
    expect(rows.length).toBeGreaterThan(0);
    console.info(
      '\nkanban-patrol/04 — measured contrast\n' +
        rows
          .map(
            (row) =>
              `  ${row.column.padEnd(12)} ${row.theme.padEnd(6)} header ${row.headerRatio.toFixed(2)}:1  dot ${row.dotRatio.toFixed(2)}:1`,
          )
          .join('\n'),
    );
  });
});
