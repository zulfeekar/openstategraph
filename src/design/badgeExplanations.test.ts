import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * **A word on a badge is a claim, and a claim owes the reader a sentence.**
 *
 * `say-it-on-the-surface` 05. The palette printed **Hidden** beside two
 * packages; the owner asked what it meant. The sentence existed and was hung
 * off the *row's* native `title`, which is a second of delay, anchored at the
 * pointer rather than at the word, invisible to keyboard focus, and
 * concatenated behind the row's own hint. The reason nobody had fixed it is
 * that `Badge` had no way to carry an explanation at all — so the rule and the
 * means landed together, and this is the part that fails.
 *
 * The rule, stated so it can be checked:
 *
 * > A `Badge` whose content is a **word** takes an `explanation`.
 * > A `numeric` badge — a count beside the thing it counts — does not.
 *
 * A census rather than a paragraph, in the spirit of
 * `publicSurfaceCeiling.test.ts`: the number of unexplained word badges is
 * pinned, each one is named, and each name carries the argument for it. A new
 * one is a red test. Removing one means editing this list, which is the point
 * — the exception has to be *said*, not inherited.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    if (!path.endsWith('.tsx')) return [];
    if (path.endsWith('.test.tsx')) return [];
    return [path];
  });
}

interface BadgeUse {
  readonly file: string;
  readonly line: number;
  readonly opening: string;
}

/** Every `<Badge …>` in the app, with the text of its opening tag. */
function badgeUses(): readonly BadgeUse[] {
  const uses: BadgeUse[] = [];
  for (const file of sources(SRC)) {
    const text = readFileSync(file, 'utf8');
    const lines = text.split('\n');
    lines.forEach((line, index) => {
      let from = line.indexOf('<Badge');
      while (from !== -1) {
        // The opening tag may wrap across lines, so read forward to the first
        // `>` rather than trusting this line to hold the whole of it.
        const tail = lines.slice(index).join('\n').slice(from);
        const close = tail.indexOf('>');
        uses.push({
          file: file.slice(SRC.length),
          line: index + 1,
          opening: close === -1 ? tail.slice(0, 200) : tail.slice(0, close + 1),
        });
        from = line.indexOf('<Badge', from + 1);
      }
    });
  }
  return uses;
}

/**
 * Word badges that carry no explanation, each with the argument for it.
 *
 * These are exceptions, not a backlog to ignore: every one is a claim whose
 * meaning is carried by something else *on the same surface*, named here. If
 * you cannot write that sentence for a new badge, the badge needs an
 * `explanation` instead of a row in this list.
 */
const UNEXPLAINED_BY_DESIGN: Record<string, string> = {
  'view/inspector/Inspector.tsx':
    'Port names and a ready/error verdict, each printed inside a labelled section that already says what it is describing.',
  'view/nodes/FieldRenderer.tsx':
    'A validator verdict rendered immediately under the field it judged, with the reason beside it.',
  'view/overlays/McpServersDialog.tsx':
    'default/project provenance and a reachability verdict; `mcpConsequences` writes the sentence into the row body rather than into a hover.',
  'view/overlays/CredentialsDialog.tsx':
    'Provider configuration state, sitting on the row whose fields are the explanation.',
};

describe('a word on a badge', () => {
  const uses = badgeUses();

  it('finds every Badge in the app, so the census cannot go quiet', () => {
    // A guard on the walker itself: if this collapses to nothing, every
    // assertion below passes vacuously.
    expect(uses.length).toBeGreaterThan(10);
  });

  it('explains itself, unless it is a count or a recorded exception', () => {
    const offenders = uses
      .filter((use) => !use.opening.includes('numeric'))
      .filter((use) => !use.opening.includes('explanation'))
      .filter((use) => !(use.file in UNEXPLAINED_BY_DESIGN))
      .map((use) => `${use.file}:${use.line}`);

    expect(offenders).toEqual([]);
  });

  it('every recorded exception is real, and carries its argument', () => {
    for (const [file, why] of Object.entries(UNEXPLAINED_BY_DESIGN)) {
      // A stale exception is worse than none: it silently exempts a file that
      // no longer has the badge the argument was written about.
      expect(uses.some((use) => use.file === file)).toBe(true);
      expect(why.length).toBeGreaterThan(40);
    }
  });

  it('the reported one — Hidden — is explained, at the mark and by keyboard', () => {
    const palette = readFileSync(join(SRC, 'view/palette/Palette.tsx'), 'utf8');
    expect(palette).toMatch(/<Badge[\s\S]{0,120}explanation=\{HIDDEN_PACKAGE_NOTE\}/);
    // And the sentence is no longer smuggled into the row's native title,
    // where it arrived behind the row's own hint and after a second's delay.
    expect(palette).not.toContain('${hint}\\n\\n${HIDDEN_PACKAGE_NOTE}');

    const indicators = readFileSync(join(SRC, 'design/primitives/Indicators.tsx'), 'utf8');
    // Focusable, because a hover-only explanation is the same defect one input
    // device along — the complaint restated rather than answered.
    expect(indicators).toContain('tabIndex: 0');
    expect(indicators).toContain('<Tooltip content={explanation} multiline>');
  });
});
