import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The instrument for `the-look-has-an-author-now/02`, and the argument for
 * its shape is `07`.
 *
 * `07` found that `Archivo` was declared in `package.json`, self-hosted
 * correctly in `fonts.css`, named by `--osg-font-display` — and **never
 * installed**, so Vite emitted no `woff2`, every face reported
 * `status: "error"`, and the entire product rendered in Helvetica while
 * `npm run build`, `npm run verify` and every gate in the repository passed
 * green. Nothing in this codebase measured any of it.
 *
 * So this file is deliberately **not** only the obvious census. A hex-literal
 * rule would not have caught `07` — there was no literal, there was a
 * reference to something that did not exist. Three of the six checks below
 * are about that shape instead: **a name a stylesheet spends must resolve to
 * something.** A font file on disk, a custom property somebody declared, a
 * colour role that exists in both themes rather than one.
 *
 * ---
 *
 * **What a pin costs when it fires wrongly.** A pin that fails wrongly gets
 * suppressed and then measures nothing, so every rule here is narrowed until
 * the failures it can produce are all real, and the narrowing is written down
 * beside it rather than implied by an exemption list. Three narrowings carry
 * most of that weight:
 *
 * - The colour rule is scoped to **declarations whose property consumes a
 *   colour**, not to every `#` in a file. `canvas/canvas.css`'s six
 *   `linear-gradient(#000 0 0)` and `RunDock.css`'s `mask-image` gradient are
 *   opacity channels for `mask-composite`, where literal black is required by
 *   the spec and has nothing to do with a theme. Property scoping excludes
 *   them **by construction**, which is why this file needs no file-level
 *   exemption for either — `07` exempted `canvas/canvas.css` outright for its
 *   *border widths*, and that argument does not transfer to colour.
 * - The colour rule is scoped to **hex**. An `rgba()` in a component is
 *   usually an alpha composition over a ground the token layer does not name,
 *   and forbidding those would fire on legitimate work. That is a **recorded
 *   gap, not a claim of coverage**: `--color-scrim` was minted this session
 *   precisely because one such literal had been copied into a second file,
 *   and nothing here would have caught it.
 * - The font-size rule forbids **absolute** literals only. `0.85em` on a chip
 *   inside caption type and `0.9em` on a caret are relative to a parent that
 *   already names a token; that is a different pattern from an absolute
 *   measurement and the tokens do not own it. Also a recorded gap: `0.85em`
 *   of `--font-size-11` is 9.35px, below the smallest authored step, which is
 *   a design question for whoever owns the type scale rather than something a
 *   census should decide by failing.
 *
 * **None of this runs in CI.** No job has started since 2026-08-29 21:43Z —
 * every run fails in about three seconds on a GitHub account spending limit,
 * which is exactly why the `clean-install` job that would have caught `07`
 * did not. `npm run verify` on a developer's machine is the only place these
 * checks execute.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url));
const SRC = fileURLToPath(new URL('../../', import.meta.url));
const REPO = fileURLToPath(new URL('../../../', import.meta.url));

/** A path as this repository writes it — `view/run/RunDock.css`. */
const under = (path: string): string => relative(SRC, path).split(sep).join('/');

const read = (path: string): string => readFileSync(path, 'utf8');

/**
 * Comments are prose, and this file is being read by rules that would
 * otherwise fail on a paragraph *explaining* a defect. Stripping them first
 * is not a convenience: the `--color-scrim` block in `theme.css` quotes the
 * dead reference it replaced, and an unstripped census would have counted it.
 */
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

/** Every `.css` under `src/`, so a new stylesheet is covered the day it lands. */
const stylesheets = (): string[] => filesUnder(SRC, ['.css']);

/** The declared value of a custom property, from the first block that sets it. */
function declared(css: string, token: string): string {
  return (new RegExp(`${token}\\s*:\\s*([^;]+);`).exec(css)?.[1] ?? '').replace(/\s+/g, ' ').trim();
}

/** One `property: value;` declaration, as written. */
interface Declaration {
  readonly file: string;
  readonly property: string;
  readonly value: string;
}

function declarations(): Declaration[] {
  const out: Declaration[] = [];
  for (const path of stylesheets()) {
    for (const match of code(read(path)).matchAll(/([-a-zA-Z]+)\s*:\s*([^;{}]+);/g)) {
      out.push({ file: under(path), property: match[1] ?? '', value: (match[2] ?? '').trim() });
    }
  }
  return out;
}

/* ------------------------------------------------------------------ *
 * 1. Colour
 * ------------------------------------------------------------------ */

describe('a colour is a role the design layer names, never a literal', () => {
  /**
   * Every property that puts a colour on screen. `mask`, `mask-image` and
   * their `-webkit-` twins are deliberately absent — a mask's `#000` is an
   * alpha channel, not a colour — and so is `background-image` where the
   * only such literals in this repository are those masks.
   */
  const CONSUMES_COLOUR = new Set([
    'color',
    'background',
    'background-color',
    'border-color',
    'border-top-color',
    'border-right-color',
    'border-bottom-color',
    'border-left-color',
    'border',
    'border-top',
    'border-right',
    'border-bottom',
    'border-left',
    'outline',
    'outline-color',
    'fill',
    'stroke',
    'box-shadow',
    'text-decoration-color',
    'caret-color',
    'accent-color',
    'column-rule-color',
  ]);

  /**
   * The two files that *are* the declaration layer. A hex belongs in exactly
   * one place and this is it — `tokens.css` holds the authored `--osg-*`
   * values the owner supplied, `theme.css` holds the roles derived from them.
   */
  const DECLARATION_LAYER = ['design/styles/tokens.css', 'design/styles/theme.css'];

  /**
   * **The quarantine, and it is a ratchet rather than an exemption.**
   *
   * `02` names these two literals as the defect it exists to catch: `#a78bfa`
   * is the resolved value of `--accent-on-tint` under
   * `[data-theme='dark'] [data-accent='violet']`, hand-typed into a component
   * instead of referenced.
   *
   * **The reason they survive has changed, and that is the honest record.**
   * Until `09`'s remainder was swept (`the-look-has-an-author-now/09`, second
   * half) the sentence here said `src/view/ask/` was held by a concurrent
   * worktree, so editing it would have written a merge conflict into somebody
   * else's work. That was true and is no longer: the directory was reachable,
   * and every dead *name* in it was repaired in the same commit that repaired
   * this paragraph. These two are still literals because they are a **colour
   * decision, not an access problem** — and it is not this pin's to make.
   *
   * `.ask__decision-branch` and `.timeline__lane[data-repeat='true']` are
   * violet on purpose in *both* themes: `--violet-50` / `--violet-600` in
   * light, and these two hand-typed values in dark. Referencing
   * `--accent-on-tint` would resolve, and would make a decision branch follow
   * whichever of the nine accents the workflow carries — a different product,
   * not a de-duplication. Minting a fixed violet role instead is the move
   * `09` refused for `--color-accent-subtle`: a second spelling of a colour in
   * a system whose identity has one accent voice. Which way that goes is
   * `the-look-has-an-author-now/06`, and it belongs to the owner.
   *
   * The row asserts the count **exactly**, so it cannot quietly grow, and it
   * goes red the day the two are decided — which is the only kind of exemption
   * that removes itself.
   */
  const QUARANTINED: ReadonlyArray<readonly [file: string, count: number]> = [
    ['view/ask/AskPanel.css', 2],
  ];

  const hexes = (): Declaration[] =>
    declarations().filter(
      (d) =>
        CONSUMES_COLOUR.has(d.property) &&
        !DECLARATION_LAYER.includes(d.file) &&
        /#[0-9a-fA-F]{3,8}\b/.test(d.value),
    );

  it('leaves no hex literal in a colour-consuming declaration', () => {
    const quarantined = new Set(QUARANTINED.map(([file]) => file));
    expect(
      hexes()
        .filter((d) => !quarantined.has(d.file))
        .map((d) => `${d.file}: ${d.property}: ${d.value}`),
    ).toEqual([]);
  });

  it.each(QUARANTINED)(
    '%s still carries exactly %i, and that is a debt with a ticket',
    (file, n) => {
      expect(hexes().filter((d) => d.file === file)).toHaveLength(n);
    },
  );

  /**
   * **A hex behind a `var()` is still a hex, and it is the worse one.**
   *
   * `var(--color-status-danger, #ef4444)` reads in review as a safety net
   * over a token. It was not: this product has never declared
   * `--color-status-danger`, so the fallback was the value in force, in both
   * themes, and the health dot was a Tailwind red rather than the authored
   * accent. `GraphPreview.css` was the same defect five times over —
   * `--color-bg`, `--color-surface`, `--color-text`, `--color-border` and
   * `--color-text-muted` are all names this repository has never had, so the
   * whole overlay rendered `#fff` on `#111` in the dark theme too.
   *
   * A fallback cannot fail, which is the entire problem: it renders something
   * plausible and reports nothing. Naming the real role is the fix, and this
   * check is the same census as the one above — stated separately because the
   * shape is what a reader has to learn to recognise.
   */
  it('leaves no hex hiding in a var() fallback', () => {
    expect(
      declarations()
        .filter(
          (d) =>
            !DECLARATION_LAYER.includes(d.file) &&
            /var\(\s*--[a-zA-Z0-9-]+\s*,[^)]*#[0-9a-fA-F]{3,8}/.test(d.value),
        )
        .map((d) => `${d.file}: ${d.value}`),
    ).toEqual([]);
  });
});

/* ------------------------------------------------------------------ *
 * 2. Type
 * ------------------------------------------------------------------ */

describe('a font-size is a step on a scale, never a measurement', () => {
  /**
   * Seven steps — 10, 11, 12, 13, 14, 16, 20 — and the top of it is a
   * statement `07` made on purpose: the authored file runs to
   * `--osg-text-60` because it was authored for document surfaces, and this
   * is a canvas tool whose densest surface is a 252px node card.
   */
  it('declares the seven steps and nothing between them', () => {
    const scale = [...code(read(join(HERE, 'tokens.css'))).matchAll(/--font-size-(\d+)\s*:/g)].map(
      (m) => Number(m[1]),
    );
    expect(scale).toEqual([10, 11, 12, 13, 14, 16, 20]);
  });

  /**
   * Absolute only. `18px` on the repeatable-group remove button and `10px`
   * on a run-timeline bar label were the two live instances — one off the
   * scale entirely, one sitting exactly on `--font-size-10` and simply not
   * saying so. The second is the more instructive: a literal that happens to
   * agree with a token today is the one that drifts silently tomorrow.
   */
  it('leaves no absolute font-size literal in any stylesheet', () => {
    expect(
      declarations()
        .filter((d) => d.property === 'font-size' && /(^|\s)[\d.]+(px|rem|pt)\b/.test(d.value))
        .map((d) => `${d.file}: ${d.value}`),
    ).toEqual([]);
  });
});

/* ------------------------------------------------------------------ *
 * 3. The name resolves — the shape `07` was actually made of
 * ------------------------------------------------------------------ */

describe('a face the product declares is a face it can load', () => {
  const FONTS = code(read(join(HERE, 'fonts.css')));

  /**
   * **This is the check that would have caught `07`.**
   *
   * `fonts.css` was never at fault — Vite resolves a bare specifier the
   * moment the package exists. All three packages were declared in
   * `package.json` and `package-lock.json` and **none of the three was
   * installed**, so the build emitted no `woff2` and left
   * `url(@fontsource-variable/archivo/files/...)` unresolved, which the dev
   * server answers with `index.html` at `text/html`. The product rendered in
   * Helvetica for as long as it took somebody to look at it with a colour
   * picker.
   *
   * `clean-install` in CI would have caught it. CI has started no job since
   * 2026-08-29 21:43Z, so this is the only gate that does.
   */
  it('resolves every @font-face src to a file on disk', () => {
    const specifiers = [...FONTS.matchAll(/src:\s*url\('([^']+)'\)/g)].map((m) => m[1] ?? '');
    expect(specifiers.length).toBe(6);
    expect(specifiers.filter((s) => !existsSync(join(REPO, 'node_modules', s)))).toEqual([]);
  });

  /** And a family the tokens name has to be a family this file declares. */
  it('declares every family the authored tokens name', () => {
    const TOKENS = code(read(join(HERE, 'tokens.css')));
    for (const role of ['--osg-font-display', '--osg-font-text', '--osg-font-mono']) {
      const first = /^\s*'?([^',]+)'?/.exec(declared(TOKENS, role))?.[1] ?? '';
      expect(first).not.toBe('');
      expect(FONTS).toContain(`font-family: '${first}'`);
    }
  });
});

describe('a token a stylesheet spends is a token something declares', () => {
  /**
   * The same shape as the missing font, one layer up. A `var(--color-border)`
   * naming nothing does not fail, does not warn and does not render: an
   * invalid `var()` inside a shorthand makes the whole declaration invalid at
   * computed-value time, so `border-left: 2px solid var(--color-border)` on
   * the inspector's locked row drew **no bar at all**, and had drawn none for
   * as long as the rule had existed.
   *
   * Twenty-nine of these were live when this file was written, across
   * fourteen stylesheets and twenty distinct names. `09` swept them: the
   * headline was `.rich-text th/td`, whose `border: … var(--color-border)`
   * measured `0px none` in both themes — **rendered Markdown tables in this
   * product had no gridlines** — beside a live pill mark and a runtime health
   * dot drawn in no colour at all, and an inspector badge pair the code says
   * "must not be mistaken for one control with two labels" rendering
   * identically because both had fallen to `currentColor` on transparent.
   *
   * Each was decided rather than aliased, and the decisions were of three
   * kinds: a **misspelling** of a role that exists (`--color-text` for
   * `--color-text-primary`, `--color-surface-sunken` for a declared ground),
   * a **role chosen freshly** because the name asked for something this
   * identity does not have (`--color-warning-*`, `--color-accent-*`), and one
   * **deletion** — `.pill:focus-visible` had invented a second focus geometry
   * and drawn none, so `reset.css`'s single ring took it back. **Nothing was
   * minted.** An alias for a name that should never have been used freezes
   * the mistake, and `--color-accent-subtle` would have been a second
   * spelling of `--color-danger-subtle` in a system with one accent voice.
   *
   * **The list is empty, and that is the whole of `09`.** Five survived its
   * first session, all in `src/view/ask/`, which a concurrent worktree held;
   * the second half of `09` reached that directory and repaired every one
   * against a live build rather than against this file:
   *
   * - `AskPanel.css --color-border`, `--color-surface`, `--color-text` — the
   *   rejection note's frame, ground and ink, all three on one declaration
   *   block. It measured `border: 0px none`, `background: rgba(0, 0, 0, 0)`
   *   and an inherited `color` in **both** themes: a textarea a person is
   *   asked to type a rejection into, drawn with no edge and no ground at all.
   *   Misspellings of `--color-border-default`, `--color-bg-surface` and
   *   `--color-text-primary`.
   * - `PastRuns.css --color-surface-sunken` — the same misspelling of
   *   `--color-bg-surface-sunken`, behind a `transparent` fallback, so one
   *   tool call's line had no ground to separate it from the lane.
   * - `PastRuns.css --type-code` — the one that is not a colour, and the one
   *   that shows what a fallback costs. It resolved to `--type-caption` and a
   *   `font-family` line beside it re-imposed the mono family, so the text
   *   *looked* right and the role it wanted, `--type-mono-sm`, already says
   *   both things in one token. Naming it made the second declaration
   *   redundant, which is the tell that the pair was one fact written twice.
   *
   * The set stays recorded **exactly**, which makes it a ratchet in both
   * directions: a first reference is red, and repairing one is red too until
   * its row is deleted. A list that can only be edited deliberately is the
   * difference between a debt and a suppression.
   *
   * ---
   *
   * **The shape this census catches by luck, and the one it cannot catch at
   * all.** The build door read
   * `border-left: 3px solid var(--color-border-strong, var(--color-border))`.
   * `--color-border-strong` was declared in both theme blocks at the time,
   * so the fallback behind it was **unreachable** — it could never render,
   * in any theme, on any element. (`the-look-has-an-author-now/16` retired
   * that name outright; the account below is of the state this census was
   * written against, and both halves of the pair are gone now.) Nothing about the screen would ever have reported it, and it was
   * reported here only because the name behind it happened to be dead: the
   * matcher below is global, so `var(--a, var(--b))` yields both names.
   *
   * Change the inner name to one that resolves and the whole thing goes
   * silent — dead code in CSS with no signature, which is `CLAUDE.md`'s
   * `TopBar.tsx` gap in another language. Two live instances remained
   * (`design/primitives/Pill.css`), and they were not the same as the five
   * `var(--accent-*, …)` fallbacks beside them: `--accent-solid` and
   * `--accent-on-tint` are declared under `[data-accent]` only, so an element
   * outside an accented subtree genuinely falls through.
   *
   * **That is no longer a gap.** `the-look-has-an-author-now/10` found the
   * rule to be exact rather than a proxy — a name declared by a selector list
   * containing a bare `:root` is in scope always, and nothing behind it can
   * render — so section 7 below pins it, the two Pill fallbacks are deleted,
   * and the five accent ones are asserted to survive.
   */
  const DEAD: readonly string[] = [];

  it('names the ones that resolve to nothing, and the list only shrinks by decision', () => {
    /* A custom property is declared in CSS, and also in TSX as
       `style={{ '--rtl-name': ... }}` — both count. */
    const names = new Set<string>();
    for (const path of filesUnder(SRC, ['.css', '.ts', '.tsx'])) {
      const source = path.endsWith('.css') ? code(read(path)) : read(path);
      for (const m of source.matchAll(/(--[a-zA-Z0-9_-]+)\s*:/g)) names.add(m[1] ?? '');
      for (const m of source.matchAll(/['"](--[a-zA-Z0-9_-]+)['"]/g)) names.add(m[1] ?? '');
    }
    const dead = new Set<string>();
    for (const path of stylesheets()) {
      for (const m of code(read(path)).matchAll(/var\(\s*(--[a-zA-Z0-9_-]+)/g)) {
        if (!names.has(m[1] ?? '')) dead.add(`${under(path)} ${m[1]}`);
      }
    }
    expect([...dead].sort()).toEqual([...DEAD].sort());
  });
});

/* ------------------------------------------------------------------ *
 * 4. Both themes
 * ------------------------------------------------------------------ */

describe('a colour role exists in both themes', () => {
  /**
   * A pin that reads only `:root` measures a third of the truth. Roles are
   * declared in a light block and redefined in a dark one, and a role present
   * in one and absent from the other renders the wrong theme's value with no
   * error anywhere.
   */
  const THEME = code(read(join(HERE, 'theme.css')));
  const roles = (selector: string): Set<string> => {
    const body = new RegExp(`${selector}\\s*\\{([\\s\\S]*?)\\n\\}`).exec(THEME)?.[1] ?? '';
    expect(body).not.toBe('');
    return new Set([...body.matchAll(/^\s*(--color-[a-z0-9-]+)\s*:/gm)].map((m) => m[1] ?? ''));
  };

  /**
   * Three, and each is correct by derivation rather than missing:
   * `--color-rule: var(--osg-divider)`, and `--osg-divider` is itself
   * redefined in `tokens.css`'s dark block — full ink on either ground. A
   * role that flips through an authored token does not restate itself.
   *
   * `--color-border` and `--color-border-emphasis` (`the-look-has-an-
   * author-now/15`) are the same shape one derivation further in:
   * `color-mix(in srgb, var(--osg-divider) N%, transparent)`, so the single
   * light-block declaration already carries the dark value and a second
   * one under `[data-theme='dark']` would only restate the formula.
   */
  const DERIVED_IN_BOTH = ['--color-rule', '--color-border', '--color-border-emphasis'];

  it('redefines every light role in the dark block, or derives it from one that flips', () => {
    const light = roles("\\[data-theme='light'\\]");
    const dark = roles("\\[data-theme='dark'\\]");
    expect([...light].filter((r) => !dark.has(r) && !DERIVED_IN_BOTH.includes(r))).toEqual([]);
    expect([...dark].filter((r) => !light.has(r))).toEqual([]);
  });

  /** The one minted this session, and the one thing worth saying about it. */
  it('states the scrim in both, at the same value, on purpose', () => {
    expect(roles("\\[data-theme='light'\\]").has('--color-scrim')).toBe(true);
    expect(roles("\\[data-theme='dark'\\]").has('--color-scrim')).toBe(true);
    const values = [...THEME.matchAll(/--color-scrim:\s*([^;]+);/g)].map((m) => m[1]);
    expect(values).toEqual(['rgba(9, 12, 17, 0.45)', 'rgba(9, 12, 17, 0.45)']);
  });
});

/* ------------------------------------------------------------------ *
 * 5. TypeScript
 * ------------------------------------------------------------------ */

describe('a colour literal in TypeScript is one of four, each with an argument', () => {
  /**
   * Not a rule but a **census**, because the honest answer to `02`'s question
   * about the crash screen is that all four of these are defensible and a
   * fifth probably is not. Recording the set exactly is what turns "we
   * decided these were fine" into something a future commit has to argue
   * with.
   *
   * - `main.tsx` and `ErrorBoundary.tsx` are the screen that renders when
   *   boot threw or React unmounted the tree. A custom property would in
   *   fact resolve — Vite links the stylesheet independently of the module
   *   graph — but the value of this surface is that it depends on as little
   *   as possible, and `#c00` on `#fff` needs no cascade at all.
   * - `exportWorkflow.ts` reads `--color-bg-canvas` off the live document and
   *   falls back only if that read returns empty. It writes into an exported
   *   SVG rather than the UI. `02` asked for a comment cross-referencing the
   *   token so the constant cannot go stale unnoticed; it has one.
   */
  const ALLOWED: ReadonlyArray<readonly [file: string, count: number, why: string]> = [
    ['main.tsx', 1, 'boot-failure screen: renders before anything is known to work'],
    ['view/ErrorBoundary.tsx', 2, 'the same screen, after React has unmounted the tree'],
    ['view/export/exportWorkflow.ts', 1, 'fallback for a computed-style read, into an SVG file'],
  ];

  it('finds colour literals in exactly those files, in exactly those counts', () => {
    const found = new Map<string, number>();
    for (const path of filesUnder(SRC, ['.ts', '.tsx'])) {
      if (path.endsWith('.test.ts') || path.endsWith('.test.tsx')) continue;
      const n = [...read(path).matchAll(/'#[0-9a-fA-F]{3,8}'/g)].length;
      if (n > 0) found.set(under(path), n);
    }
    expect([...found].sort()).toEqual(ALLOWED.map(([file, count]) => [file, count]).sort());
  });

  it('cross-references the token its fallback shadows', () => {
    expect(read(join(SRC, 'view/export/exportWorkflow.ts'))).toContain('--color-bg-canvas` in');
  });
});

/* ------------------------------------------------------------------ *
 * 6. The marker bar — `the-look-has-an-author-now/08`
 * ------------------------------------------------------------------ */

describe('a bar beside a block is a marker, and a marker has a name', () => {
  const TOKENS = code(read(join(HERE, 'tokens.css')));

  /**
   * `07` gave the product two widths and left a third kind of line as a
   * literal on purpose: the bars down the left of a blockquote, a quoted
   * run, an inspector row, a palette section. They share a number with the
   * rule and none of its meaning.
   *
   * The name has to make that unconfusable, so it says what the line does
   * rather than how thick it is: a **rule** is a seam *between* regions of
   * the shell, a **marker** is a bar *beside* a block of text. `accent` was
   * considered and rejected — it is the loudest word in this palette
   * (`--osg-accent`, `[data-accent]`, `--accent-on-tint`) and a width called
   * `--border-width-accent` would read as the accent colour's width.
   */
  it('derives the marker from the authored rule rather than picking a third number', () => {
    expect(declared(TOKENS, '--border-width-marker')).toBe('var(--osg-rule)');
  });

  /**
   * **The four blockquotes were not four bugs and not two weights — they
   * were one width guessed twice.** `.prose blockquote` in `typography.css`
   * and `.rich-text blockquote` in `RichText.css` are two implementations of
   * the same element, one at 2px and one at 3px; the ask panel's quoted
   * output and its build door are the same disagreement a second time.
   * Duplicated *knowledge* — what a quoted block looks like — spread over
   * five files, which is why the answer is one token and not a token per
   * weight. A token minted over an unresolved disagreement would have frozen
   * the disagreement.
   *
   * The last three landed with `09`'s remainder, and the build door is the one
   * that proves the paragraph above: it was the 3px half of the ask panel's
   * own disagreement, and it went to 2px because the disagreement was never a
   * decision. What distinguishes it from the trace output beside it survives
   * where it belongs — in the colour, which at the time was
   * `--color-border-strong` against `--color-border-default` and since `16`
   * is the one `--color-border`; "a different left edge" was reaching for a
   * distinction the two-weight system no longer draws.
   */
  const MARKERS: ReadonlyArray<readonly [file: string, selector: string]> = [
    ['design/styles/typography.css', '.prose blockquote'],
    ['view/common/RichText.css', '.rich-text blockquote'],
    ['view/inspector/Inspector.css', '.inspector__locked-row'],
    ['view/palette/Palette.css', '.palette-item--scoped'],
    ['view/ask/AskPanel.css', '.ask__trace-output'],
    ['view/ask/AskPanel.css', '.ask__suggestion--build'],
    ['view/ask/PastRuns.css', '.past-runs__lane'],
    // `memory-and-replay` 59. The selected step's payload, quoted verbatim in
    // the run dock — the same thing `.ask__trace-output` is, one surface over,
    // which is why it takes the same width rather than a second guess at it.
    ['view/run/RunDock.css', '.rtl__payload-text'],
  ];

  /**
   * **One marker, two spellings, and the token is the fact** —
   * `memory-and-replay/62`.
   *
   * This pattern used to be the literal string `border-left: var(...)`, which
   * made the per-selector half of the cage a rule about a **physical**
   * property while its own failure message talked about the **token**. A
   * marker authored `border-inline-start` — the logical, RTL-correct spelling
   * this codebase already ships (`RunDock.css` writes `border-inline-start`
   * and `border-inline-end` beside `insetInlineStart`) — was caged correctly
   * by the file-level assertion below and rejected here, so the first person
   * to write correct CSS would read a failure about a design token and
   * conclude the token was wrong.
   *
   * **The repository's position is that both spellings are one thing, and it
   * was already taking it in code before it was written down here.** Measured
   * rather than assumed: `padding-inline`, `margin-inline-start`,
   * `inset-inline-start`, `border-block-end` and `border-inline-start` are all
   * in shipped stylesheets. So this is not the place to legislate a house
   * style — a gate that forced one spelling would be deciding a layout
   * question it was not written to have an opinion on, which is exactly the
   * complaint that opened the ticket. What it is written to decide is that a
   * bar beside a block spends the **name** rather than a number, and that is
   * side-agnostic.
   *
   * Loosened here and **not** in the file-level cage, which is the assertion
   * that actually stops drift: this half only proves a registered selector
   * still draws one.
   */
  const MARKER_BAR = /border-(?:left|inline-start):\s*var\(--border-width-marker\)\s+solid/;

  /**
   * The matcher itself, before it is pointed at any stylesheet — the two
   * spellings it must accept, and the two near-misses it must still refuse.
   * Without this the loosening below could widen to "anything vaguely
   * border-ish" and nothing would say so.
   */
  it('reads a marker in either spelling, and still refuses a bar that is neither', () => {
    expect(
      MARKER_BAR.test('border-left: var(--border-width-marker) solid var(--color-border);'),
    ).toBe(true);
    expect(
      MARKER_BAR.test('border-inline-start: var(--border-width-marker) solid var(--color-border);'),
    ).toBe(true);
    // A bar on the other side is a different line, and a literal is the thing
    // the token exists to replace.
    expect(
      MARKER_BAR.test('border-right: var(--border-width-marker) solid var(--color-border);'),
    ).toBe(false);
    expect(MARKER_BAR.test('border-left: 2px solid var(--color-border);')).toBe(false);
  });

  it.each(MARKERS)('%s %s draws the marker', (file, selector) => {
    /* `.rich-text blockquote` has two blocks — one for margins and one for
       the bar — so every block carrying the selector is read, not the first. */
    const blocks = [
      ...read(join(SRC, file)).matchAll(
        new RegExp(`\\${selector.replace(/ /g, '\\s+')}\\s*\\{([^}]*)\\}`, 'g'),
      ),
    ].map((m) => m[1] ?? '');
    expect(blocks.length).toBeGreaterThan(0);
    expect(
      blocks.join(''),
      `${file} ${selector} does not spend \`--border-width-marker\` on a bar down its ` +
        `leading edge. Checked for \`border-left:\` and \`border-inline-start:\` — either ` +
        `spelling registers, so this is about the token and the side, not about which of ` +
        `the two you wrote.`,
    ).toMatch(MARKER_BAR);
  });

  /**
   * The cage test, and the mirror of `07`'s: a marker is not a rule, so no
   * file may spend both names on one line and the seams stay four. Any new
   * left bar joins `MARKERS` or explains itself.
   */
  it('is drawn in exactly the files that record a marker, and no others', () => {
    const drawn = stylesheets()
      .filter((path) => /--border-width-marker\)/.test(code(read(path))))
      .map(under);
    // By file, deduplicated: `AskPanel.css` records two markers and is one
    // stylesheet. The per-selector half of the cage is the `it.each` above.
    expect(drawn.sort()).toEqual([...new Set(MARKERS.map(([file]) => file))].sort());
  });

  /**
   * **Two of the nine lines `08` tabulated are not markers**, decided before
   * the token was minted rather than swept in by resemblance:
   *
   * - `NodeCard`'s `.node__resize` is a 14px corner drawn out of a
   *   `border-right` and a `border-bottom`. It is a **glyph**, not a bar
   *   beside anything, and giving it the marker would tie a drag affordance
   *   to the weight of a quotation.
   * - `Tabs`'s `border-bottom: 2px solid transparent` is a **selection
   *   slot** — space held open so the row does not move when a tab is
   *   chosen. Its width belongs to the underline it reserves, which is a
   *   state indicator rather than an indent.
   *
   * **`08` ruled that neither is a marker. It did not rule that either is a
   * literal**, and this test asserted the stronger thing — a bare `2px` —
   * for as long as no other token wanted the line. `the-look-has-an-author-now/17`
   * is the case where one does: `.node__resize` is one of the two places in
   * the product a pointer can drag a border, so it draws the draggable
   * weight, `--border-width-rule` at `--color-rule`, and `17`'s census
   * counts that token to prove the pair has not come apart. A literal
   * cannot be counted.
   *
   * `08`'s argument is untouched by that — a drag affordance still has
   * nothing to do with the weight of a quotation, and the marker is still
   * the wrong name for it. So the row survives with what `08` actually
   * decided under it: **not the marker**, and for the corner, the rule.
   * `.tabs__tab` keeps its literal, because the underline it reserves space
   * for is a state indicator that answers to no width token yet.
   */
  it.each([
    ['view/nodes/NodeCard.css', '.node__resize', 'a glyph, not a bar'],
    ['design/primitives/Tabs.css', '.tabs__tab', 'a selection slot, not an indent'],
  ])('%s %s is not a marker — %s', (file, selector) => {
    const css = read(join(SRC, file));
    const block = new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? '';
    expect(block).toMatch(/border-(right|bottom): (2px|var\(--border-width-rule\)) solid/);
    expect(block).not.toContain('--border-width-marker');
  });

  /**
   * **Zero, and the count is kept because it is the cage.**
   *
   * This was a quarantine of three — a quoted trace output, a past-run lane,
   * the build door at 3px — held open while a concurrent worktree owned
   * `src/view/ask/`. `09`'s remainder converted all three, and the assertion
   * is kept rather than deleted: a left bar written as a literal is how the
   * marker got guessed twice in the first place, and an emptied list is a
   * stronger rule than a list of three. The next `2px solid` down the left of
   * a block joins `MARKERS` or argues here.
   */
  it('leaves no literal left bar anywhere — every marker names the token', () => {
    const literal = declarations()
      .filter((d) => /^border-(left|inline-start)/.test(d.property) && /^\s*[23]px\s/.test(d.value))
      .map((d) => `${d.file}: ${d.property}: ${d.value}`);
    expect(
      literal.sort(),
      'a bar down a leading edge written as a bare 2px or 3px — in either spelling, ' +
        'since `border-inline-start` is the same line as `border-left`. Name ' +
        '`--border-width-marker` and join MARKERS, or argue here that it is not a marker.',
    ).toEqual([]);
  });
});

/* ------------------------------------------------------------------ *
 * 7. Unreachable fallbacks — `the-look-has-an-author-now/10`
 * ------------------------------------------------------------------ */

describe('a fallback behind a name that always resolves is dead code', () => {
  /**
   * `09` recorded this shape and declined to pin it, because telling the two
   * kinds apart needs a rule about **conditional declaration** and a pin that
   * fires wrongly gets suppressed. `10` is that rule, and it turned out to be
   * exact rather than a proxy.
   *
   * A `var()` fallback renders only when the outer custom property is not
   * *defined*. So the question is never "is this name spelled right" — `09`
   * answered that one — it is **"is there a state in which this name is out
   * of scope"**, and the selector a declaration sits under answers it:
   *
   * - A rule whose selector list contains a bare `:root` matches the document
   *   element **always**. `--color-border`, `--color-text-quaternary`
   *   and hundreds of others are declared there, so nothing behind them can
   *   ever render, in any theme, on any element. (The sample used to be
   *   `--color-border-strong`, which `the-look-has-an-author-now/16`
   *   retired — a vacuity check naming a token that can be deleted is a
   *   test that quietly stops testing.)
   * - `--accent-solid` and `--accent-on-tint` are declared under
   *   `[data-accent]` only. An element outside an accented subtree genuinely
   *   falls through, so the five `var(--accent-*, …)` fallbacks in
   *   `Slider.css`, `Select.css` and `Minimap.css` are load-bearing. A rule
   *   that condemned them would have been condemning working code, which is
   *   exactly the failure `09` was avoiding.
   *
   * That is why the rule reads the **selector**, not a list of token names:
   * a tenth accent, or a token moved out of `:root` into `[data-accent]`,
   * re-classifies itself.
   *
   * **`11` widened the scope from a nested `var(--a, var(--b))` to any
   * fallback at all**, which is one character in the matcher and a decision
   * that had to be taken first. `10` deferred it because a *literal* fallback
   * can be deliberate in a way a token alias is not: `var(--radius-sm, 6px)`
   * reads as "6px if the design system ever loses the name", which is an
   * argument, where an alias only reads as an author unsure which name
   * existed.
   *
   * Measured, the argument does not survive its own instance. The rule above
   * is not about likelihood — a name declared at bare `:root` is in scope on
   * every element in every theme, so the design system cannot *lose* it while
   * the stylesheet that spends it is loaded. There is no state to be
   * belt-and-braces against. And the twelve literals said so themselves: the
   * token behind `var(--focus-ring-width, 2px)` is `3px`, the one behind
   * `var(--letter-spacing-wide, 0.04em)` is `0.01em`, and `--radius-sm`
   * resolves through `--osg-radius: 0px` rather than the `4px` written beside
   * it three times. A fallback that disagrees with the token is a second
   * opinion nobody can ever read — belt-and-braces would at least have had to
   * agree with the belt.
   *
   * So: deleted, and the list stays a ratchet at empty rather than growing an
   * exemption by shape. What widening did add is a third kind, and it is why
   * the live assertion below no longer reads "every survivor is an accent".
   * `--canvas-empty-inset-left`, `--canvas-empty-inset-right` and
   * `--textarea-max-rows` are set **inline on one element** by `AppShell.tsx`
   * and `Field.tsx`, never at `:root`, so their literal fallbacks carry every
   * element the component has not measured yet. The selector rule classifies
   * them correctly with no help — which is the whole reason it reads
   * declarations instead of names.
   */

  /** Custom properties declared by a top-level rule that matches the root always. */
  const unconditional = (): Set<string> => {
    const names = new Set<string>();
    for (const path of stylesheets()) {
      const css = code(read(path));
      let cursor = 0;
      while (cursor < css.length) {
        const open = css.indexOf('{', cursor);
        if (open === -1) break;
        const selector = css.slice(cursor, open);
        let depth = 1;
        let end = open + 1;
        for (; end < css.length && depth > 0; end++) {
          if (css[end] === '{') depth += 1;
          else if (css[end] === '}') depth -= 1;
        }
        // `:root` as a whole selector in the list — never `:root[data-theme]`
        // and never a descendant, both of which are conditional.
        if (/(^|,)\s*:root\s*(,|$)/.test(selector)) {
          for (const m of css.slice(open + 1, end - 1).matchAll(/(--[a-zA-Z0-9_-]+)\s*:/g)) {
            names.add(m[1] ?? '');
          }
        }
        cursor = end;
      }
    }
    return names;
  };

  it('finds both kinds, so neither assertion below is vacuous', () => {
    const always = unconditional();
    expect(always.has('--color-border')).toBe(true);
    expect(always.has('--color-text-quaternary')).toBe(true);
    expect(always.has('--accent-solid')).toBe(false);
    expect(always.has('--accent-on-tint')).toBe(false);
  });

  const fallbacks = (): Array<{ site: string; token: string }> => {
    const found: Array<{ site: string; token: string }> = [];
    for (const path of stylesheets()) {
      const css = code(read(path));
      for (const m of css.matchAll(/var\(\s*(--[a-zA-Z0-9_-]+)\s*,/g)) {
        const line = css.slice(0, m.index).split('\n').length;
        found.push({ site: `${under(path)}:${line}`, token: m[1] ?? '' });
      }
    }
    return found;
  };

  /**
   * Three sites `11` could not reach, each with the same argument `10` gave
   * for deferring `view/ask/PastRuns.css`: a **concurrent worktree held the
   * directory**, and a three-token deletion is not worth a merge conflict in
   * somebody else's session. Every one is dead by the rule above and none is
   * defended — this is a ratchet that should empty, not an exemption list.
   * The next session in `view/topbar/` or `view/workflow/` deletes its own
   * and takes the row with it.
   */
  const HELD: readonly string[] = [
    'view/topbar/TopBar.css:142 --space-1',
    'view/workflow/WorkflowManager.css:85 --radius-full',
    'view/workflow/WorkflowManager.css:88 --color-bg-subtle',
  ];

  it('keeps the fallbacks that can fall through', () => {
    const always = unconditional();
    const live = fallbacks()
      .filter((f) => !always.has(f.token))
      .map((f) => `${f.site} ${f.token}`);

    // The five `var(--accent-*, …)` fallbacks `10` was written to spare. Named
    // by count rather than asserted as "every survivor", because widening to
    // literals brought in a second legitimate kind — a property set inline on
    // one element — and a rule saying only accents may fall through would now
    // be condemning `Field.css` and `canvas.css` for working code.
    expect(live.filter((s) => s.includes('--accent-')).length).toBe(5);

    // The other kind, by name: a custom property a component publishes onto
    // one element from TypeScript is out of scope everywhere else, so its
    // literal fallback is the value every unmeasured element renders.
    expect(live).toContain('design/primitives/Field.css:147 --textarea-max-rows');
  });

  it('leaves no fallback behind a name that is always in scope', () => {
    const always = unconditional();
    const dead = fallbacks()
      .filter((f) => always.has(f.token))
      .map((f) => `${f.site} ${f.token}`);
    expect(dead.sort()).toEqual([...HELD].sort());
  });
});
