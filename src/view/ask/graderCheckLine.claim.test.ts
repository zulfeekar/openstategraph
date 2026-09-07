import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Pins `production-ready` 99: `no_figure` is not a built-in `Grader` check.
 *
 * `docs/api.md` and `backend/openstategraph/compile/node_runtime.py` said the
 * built-in `Grader` adds a deterministic check named `no_figure`
 * (`production-ready` 95 corrected those two). This file and its test carried
 * the same false claim in TypeScript — `Grader` overrides only
 * `revise_payload`; `no_figure` names a stricter grader defined *inside*
 * `backend/tests/test_grader.py`, a test fixture, never a built-in check.
 *
 * `no_figure` legitimately appears in both files below as an example value —
 * `check` is an open set, and a subclass (a test fixture, here) is allowed to
 * name its own. What must never reappear is the specific false claim that
 * `Grader` (or `BaseGrader`) is the one adding it. A number — or a check name
 * — in prose has no way to fail, so this pins the exact retracted wording
 * rather than re-asserting the corrected one, which could drift the same way.
 */
describe('no_figure is never re-claimed as a built-in Grader check', () => {
  const cases: Array<{ file: string; retracted: string }> = [
    {
      file: 'src/view/ask/graderCheckLine.ts',
      retracted: 'Grader` adds `no_figure`, and any subclass overriding',
    },
    {
      file: 'src/view/ask/graderCheckLine.test.ts',
      retracted: 'Grader` adds `no_figure`, and a subclass',
    },
  ];

  for (const { file, retracted } of cases) {
    it(`${file} does not restate the retracted claim`, () => {
      const text = readFileSync(join(process.cwd(), file), 'utf-8');
      expect(text).not.toContain(retracted);
    });
  }
});
