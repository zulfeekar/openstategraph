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
});
