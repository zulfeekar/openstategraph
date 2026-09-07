import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The settled words, held to.
 *
 * CLAUDE.md fixes a small lexicon because two of its terms collide with
 * something else, and a collision "lands exactly where a user reads". The UI
 * had drifted (reviews-2026-08-14 ticket 06): a diagnostic said *"contains a
 * revise loop"* where the word is **revision loop**, and `recursion_limit` is
 * never to be called "max iterations" because it counts supersteps, so one lap
 * with fan-out costs several.
 *
 * Scoped to **user-visible strings** — quoted text in `src/`, minus tests and
 * comments-only matches — because the internal vocabulary is allowed to differ
 * and often should.
 */
const SRC = fileURLToPath(new URL('..', import.meta.url));
const REPO = fileURLToPath(new URL('../../', import.meta.url));

/** Every non-test source file under `src/`. */
function sources(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      sources(path, found);
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      found.push(path);
    }
  }
  return found;
}

/** Lines that are wholly a comment are the internal register, not UI copy. */
function uiLines(path: string): { line: string; number: number }[] {
  return readFileSync(path, 'utf8')
    .split('\n')
    .map((line, index) => ({ line, number: index + 1 }))
    .filter(({ line }) => {
      const trimmed = line.trim();
      return !trimmed.startsWith('//') && !trimmed.startsWith('*') && !trimmed.startsWith('/*');
    });
}

const BANNED: { pattern: RegExp; instead: string }[] = [
  { pattern: /revise loop/i, instead: '"revision loop" — the settled user-facing term' },
  {
    pattern: /max iterations/i,
    instead: '"step budget" — recursion_limit counts supersteps, not laps',
  },
];

/**
 * The same guard, over the documents rather than the app.
 *
 * `src/` is one surface of several, and the architecture review of 2026-08-16
 * (F10, F12) found the word `package` used in its forbidden PyPI sense in the
 * three documents a stranger reads first — outside a guard that has only ever
 * walked `src/`. So this leg walks the prose trees too.
 *
 * **One pattern, not the whole lexicon.** Widening the *roots* is cheap;
 * widening the *pattern list* to `revise loop` and `instance default` over
 * these trees is not, because a Python docstring is the internal register in a
 * way `//` comments make obvious in TypeScript and nothing makes obvious in
 * `.py` — a distinction that has to be argued before it is asserted, and it is
 * ticket 43's to argue. What lands here is the one class F10 is about, held
 * everywhere it can appear rather than in the three places a reviewer noticed.
 */
const DOC_ROOTS = [
  'README.md',
  'docs',
  'site',
  'backend/openstategraph',
  // A commented sample a user copies and reads, and the one place *instance
  // default* survived a hand sweep of the prose (ticket 43, F9).
  'openstategraph.example.yaml',
];
const DOC_SKIP = /node_modules|__pycache__|[/\\]decisions[/\\]/;

function documents(path: string, found: string[] = []): string[] {
  if (DOC_SKIP.test(path)) return found;
  if (statSync(path).isDirectory()) {
    for (const entry of readdirSync(path)) documents(join(path, entry), found);
  } else if (/\.(md|html|py|ya?ml|tsx?)$/.test(path) && !/\.test\.tsx?$/.test(path)) {
    found.push(path);
  }
  return found;
}

/**
 * `package` in the distribution sense — "a four-package core", where the
 * settled word means `workflows/<slug>/` and the thing being counted is a
 * dependency.
 *
 * Two shapes, because the counting is what makes it the wrong sense and
 * counting alone is not enough: **"nine package tests"** and **"two packages
 * behind one classifier"** are the settled sense counted, and both are in this
 * repository. So the compound form is caught outright, and the loose form only
 * beside a word that can only mean the dependency graph.
 */
const NUMBER = 'two|three|four|five|six|seven|eight|nine|ten|\\d+';
const DEPENDENCY = 'floor|lean core|dependenc|venv|wheel|pip install|resolved';
const DISTRIBUTION_PACKAGE = [
  new RegExp(`\\b(?:${NUMBER})-packages?\\b`, 'i'),
  new RegExp(`(?:${DEPENDENCY})[^.\\n]{0,60}?\\b(?:${NUMBER}) packages?\\b`, 'i'),
  new RegExp(`\\b(?:${NUMBER}) packages?\\b[^.\\n]{0,60}?(?:${DEPENDENCY})`, 'i'),
];

/**
 * The register question F12 left open, answered — and it is a real question,
 * not a technicality (ticket 43).
 *
 * In TypeScript a `//` line is obviously the internal register. In Python the
 * equivalent is not obvious, because a **docstring is both documentation and
 * the module\'s own reasoning**: `config_file.py` and `api/model_resolution.py`
 * spell out the precedence chain *instance default < config file < workflow
 * settings.model* in prose that is arguing with itself, not addressing a user.
 * Banning the phrase there would force those modules to misname the thing they
 * are explaining.
 *
 * So the split is: **a `.py` docstring or comment is internal; a quoted string
 * literal is user copy** — the same rule the `src/` leg has always used, in the
 * shape Python takes. Triple-quoted blocks are tracked rather than parsed,
 * which is an approximation and stated as one: a triple-quoted *user-facing*
 * help string would slip through. None exists today, and a real parser in a
 * lexicon test would be a second implementation of Python to keep working.
 *
 * `.md`, `.html` and `.yaml` are documents a person reads, so every line counts
 * — including the `AGENTS.md` files that ship *inside* copied examples, which
 * is where two of F9\'s hits were.
 */
function proseLines(path: string): { line: string; number: number }[] {
  const lines = readFileSync(path, 'utf8').split('\n');
  if (!path.endsWith('.py')) {
    return lines.map((line, index) => ({ line, number: index + 1 }));
  }
  const kept: { line: string; number: number }[] = [];
  let inDocstring = false;
  for (const [index, line] of lines.entries()) {
    const fences = (line.match(/"""|'''/g) ?? []).length;
    const opened = inDocstring;
    if (fences % 2 === 1) inDocstring = !inDocstring;
    // A line that opens, closes or sits inside a docstring is the module
    // talking to itself. A `#` comment is the same register.
    if (opened || fences > 0 || line.trim().startsWith('#')) continue;
    kept.push({ line, number: index + 1 });
  }
  return kept;
}

/**
 * The rest of the settled lexicon, over the same four trees (ticket 43, F9/F12).
 *
 * **`iterations` is deliberately not banned on its own.** The correct sentence
 * in this repository is *"`recursion_limit` counts supersteps, not
 * iterations"* — it appears in `docs/patterns.md`, in `mcp_server.py` and in a
 * shipped example\'s `AGENTS.md`, and a pattern that matched the word near
 * `recursion_limit` would fail on all three while catching nothing. What is
 * wrong is *labelling* the budget with it, so the labels are what is banned.
 *
 * **A line that forbids the word may say it.** `docs/patterns.md`,
 * `site/gallery.html` and two shipped `AGENTS.md` files each contain a sentence
 * whose whole content is *"never call it max iterations"* — the same allowance
 * `docs/decisions/` gets one exclusion up, for the same reason: a text whose
 * subject is the wrong word has to be able to name it. Narrow on purpose: the
 * marker must be in the phrase's own sentence — approximated as this line and
 * the one above it, because prose wraps and three of the four real cases put
 * the "never" on the previous line. A paragraph that says "never" two
 * sentences earlier and misuses the word later is still caught.
 */
/**
 * The header row of the markdown table `index` sits in, or `''`.
 *
 * The allowance above is *a line that forbids the word may say it*, and its
 * approximation is the line plus the one before it — which is right for prose
 * and blind to a table, where the word "never" lives in a **column heading**
 * several rows up. `CLAUDE.md`'s user-facing lexicon is exactly that shape:
 * `| User-facing word | Means | Must never mean |`, and every row under it is
 * a sentence whose subject is the wrong word.
 *
 * This sharpens the approximation rather than widening it. A row qualifies
 * only if it is a pipe row, only if an unbroken run of pipe rows reaches a
 * header, and only if that header itself carries a `FORBIDS` marker — so a
 * table about anything else is untouched, and a paragraph that says "never"
 * far above still fails. Found by `install-experience/25`, whose shipped brief
 * quotes that table verbatim by construction: the row was the canonical
 * statement forbidding the phrase, and the gate could not see the heading that
 * said so.
 */
function tableHeaderAbove(lines: { line: string }[], index: number): string {
  if (!lines[index]?.line.trimStart().startsWith('|')) return '';
  for (let at = index - 1; at >= 0; at -= 1) {
    const above = lines[at]?.line.trimStart() ?? '';
    if (!above.startsWith('|')) return '';
    if (!/^\|[\s:|-]+\|?\s*$/.test(above)) continue;
    return lines[at - 1]?.line ?? '';
  }
  return '';
}

const FORBIDS = /\bnever\b|\bnot\b|rather than|instead of|do not|mislabel|misnam|wrong word/i;
const DOCUMENT_BANNED: { pattern: RegExp; instead: string }[] = [
  {
    pattern: /instance default/i,
    instead: '"installation default" — CLAUDE.md fixes *instance* as one mount of a package',
  },
  {
    pattern: /max(?:imum)? (?:iterations|turns)|iteration (?:limit|budget)/i,
    instead: '"step budget" — recursion_limit counts supersteps, not laps',
  },
  {
    pattern: /revise loop/i,
    instead: '"revision loop" — the settled user-facing term',
  },
];

/**
 * `docs/decisions/` is excluded above for the reason comment lines are: a
 * record whose subject is the collision has to be able to name it. This is the
 * control that stops that exclusion from quietly becoming the whole tree.
 */
const KNOWN_DOCUMENT = 'README.md';

describe('the user-facing lexicon', () => {
  it.each(BANNED)('never says $pattern in UI copy', ({ pattern, instead }) => {
    const offenders: string[] = [];
    for (const path of sources(SRC)) {
      for (const { line, number } of uiLines(path)) {
        if (pattern.test(line)) {
          offenders.push(`${path.slice(SRC.length)}:${number}: ${line.trim().slice(0, 90)}`);
        }
      }
    }

    expect(offenders, `use ${instead}`).toEqual([]);
  });

  describe('in the documents, not only the app', () => {
    it('walks the trees it claims to', () => {
      // Anti-vacuity: four roots that resolved to nothing would make the
      // assertion below true of an empty set, which is the defect F12 names.
      const walked = DOC_ROOTS.flatMap((root) => documents(join(REPO, root)));

      expect(walked.length).toBeGreaterThan(150);
      expect(walked.some((path) => path.endsWith(KNOWN_DOCUMENT))).toBe(true);
      expect(walked.some((path) => path.endsWith('.py'))).toBe(true);
      expect(walked.some((path) => path.includes('site'))).toBe(true);
    });

    it.each(DOCUMENT_BANNED)('never says $pattern where a user reads', ({ pattern, instead }) => {
      const offenders: string[] = [];
      for (const root of DOC_ROOTS) {
        for (const path of documents(join(REPO, root))) {
          const lines = proseLines(path);
          for (const [index, { line, number }] of lines.entries()) {
            const sentence = `${lines[index - 1]?.line ?? ''} ${line} ${tableHeaderAbove(lines, index)}`;
            if (pattern.test(line) && !FORBIDS.test(sentence)) {
              offenders.push(`${path.slice(REPO.length)}:${number}: ${line.trim().slice(0, 90)}`);
            }
          }
        }
      }

      expect(offenders, `use ${instead}`).toEqual([]);
    });

    it('reads a python string literal but not a python docstring', () => {
      // The anti-vacuity control for the register split above: if `proseLines`
      // dropped every `.py` line, the assertion it guards would be true of an
      // empty set — which is the defect this whole ticket is about.
      const python = documents(join(REPO, 'backend/openstategraph')).filter((path) =>
        path.endsWith('.py'),
      );
      const kept = python.flatMap((path) => proseLines(path));

      expect(kept.length).toBeGreaterThan(1000);
      expect(kept.some(({ line }) => /"[^"]{20,}"/.test(line))).toBe(true);
      // And the register it must *not* reach: the precedence chain in
      // `config_file.py`'s docstring names the internal sense on purpose.
      expect(kept.some(({ line }) => /instance default/i.test(line))).toBe(false);
    });

    it('never counts a dependency in packages', () => {
      const offenders: string[] = [];
      for (const root of DOC_ROOTS) {
        for (const path of documents(join(REPO, root))) {
          readFileSync(path, 'utf8')
            .split('\n')
            .forEach((line, index) => {
              if (DISTRIBUTION_PACKAGE.some((pattern) => pattern.test(line))) {
                offenders.push(
                  `${path.slice(REPO.length)}:${index + 1}: ${line.trim().slice(0, 90)}`,
                );
              }
            });
        }
      }

      expect(
        offenders,
        'a "package" is `workflows/<slug>/` (CLAUDE.md) — say dependencies, or distributions',
      ).toEqual([]);
    });
  });
});
