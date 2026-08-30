import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

/**
 * No test in this repository measures a duration — `the-cost-of-one-more/19`.
 *
 * The two scaling files beside this one both used to. Each asserted a
 * wall-clock **ratio** across two document sizes, best-of-5 on
 * `performance.now()`, and one of them failed for two different sessions in a
 * single night — `0.890ms → 9.987ms` against a ceiling of 10, and `10.5` —
 * while passing alone every time. Nothing about the code under test had
 * changed; the machine was building a bundle and running the 6,700-test
 * backend suite alongside, which is the machine this repository is developed
 * on rather than an unlucky one.
 *
 * The failure mode is not "a test fails". It is the sequence this repository
 * has already written down: a gate that fails wrongly gets **suppressed** — a
 * `skip`, a raised ceiling, a `retry` — and a suppressed gate measures nothing
 * while still reading as coverage. So the census exists because the defect was
 * found by accident, in one file, while doing something else, and this
 * repository's recurring lesson is that such a defect is rarely alone. It was
 * two.
 *
 * **What this forbids is the clock, not the ratio.** Both files still assert a
 * ratio across two sizes; both now count operations the code performs
 * deterministically — walks, node visits, document reads — which a busy
 * machine cannot move. Counting turned out to be strictly more informative
 * than timing in both places, and in one of them it contradicted the claim the
 * timed assertion had been passing: see `concurrentProducers.scaling.test.ts`.
 *
 * **Scope, stated so the gap is not mistaken for coverage.** This reads
 * `performance.now()` only, and only in TypeScript test files. `Date.now()` is
 * deliberately not forbidden — three tests mint ids with it and no test
 * subtracts two of them. A `deadline = now + timeout` poll loop, which is what
 * the backend's timing calls almost all are, is a *wait*, not an assertion
 * about speed, and is not this defect. The one absolute wall-clock ceiling
 * that survives the census is Python and is argued in its own file:
 * `backend/tests/test_the_setup_path_stays_cheap.py` asserts a 5-second
 * ceiling on a path that measures milliseconds, so it detects a path that has
 * acquired a blocking cost rather than one that has slowed down, and its
 * margin is three orders of magnitude rather than the 12% that failed here.
 */

const SOURCE = join(import.meta.dirname, '..', '..');

function testFilesUnder(directory: string, found: string[] = []): string[] {
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      testFilesUnder(path, found);
      continue;
    }
    if (/\.(test|spec)\.tsx?$/.test(entry)) found.push(path);
  }
  return found;
}

/** Comments argue about the clock; only code reads one. */
function codeOf(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

describe('a scaling gate counts operations, it never times them', () => {
  it('finds no test file that reads a clock', () => {
    const offenders = testFilesUnder(SOURCE)
      // This file's own meter, below, holds the forbidden call as a string on
      // purpose. It is the one exemption and it is by exact path, so a second
      // file cannot acquire it by resembling this one.
      .filter((path) => path !== import.meta.filename)
      .filter((path) => codeOf(readFileSync(path, 'utf-8')).includes('performance.now'))
      .map((path) => relative(SOURCE, path));

    expect(
      offenders,
      'A timing assertion is flaky, and a flaky gate gets suppressed and then ' +
        'measures nothing. Count what the code does instead — every scaling ' +
        'property this repository has tried to measure turned out countable.',
    ).toEqual([]);
  });

  it('would see one, so the empty result above is a measurement', () => {
    // The meter checked against the shape it was built for: the deleted
    // assertion, verbatim enough to be recognisable, and the docstring form
    // that must stay allowed.
    const timed = 'const started = performance.now();\nwork();\n';
    const argued = '/** The old shape used performance.now() and was deleted. */\n';
    expect(codeOf(timed)).toContain('performance.now');
    expect(codeOf(argued)).not.toContain('performance.now');
  });
});
