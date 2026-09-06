import { describe, expect, it } from 'vitest';

import { DETECTOR_MAX_LENGTH, validateDetector } from './detectorPattern';

/**
 * Guardrails ticket 05. The card's half of "this pattern is not a pattern";
 * the ladder's half is `detector_problem` in `abc/guardrail.py` and the two are
 * pinned together by `backend/tests/test_a_detector_is_checked_before_it_runs.py`.
 */
describe('the Pattern field refuses a value before it is saved', () => {
  it('accepts the pattern a shipped example already carries', () => {
    // `examples/guarded-lookup/workflow.json`.
    expect(validateDetector('\\+\\d[\\d\\s()\\-]{6,}\\d')).toBeNull();
  });

  it('accepts blank, which is how every built-in entity is spelled', () => {
    expect(validateDetector('')).toBeNull();
  });

  it('names an unbalanced group rather than waiting for the run', () => {
    expect(validateDetector('(unclosed')).toContain('Not a valid pattern');
  });

  it('refuses a pattern past the cap, saying the cap', () => {
    const problem = validateDetector('a'.repeat(DETECTOR_MAX_LENGTH + 1));

    expect(problem).toContain(String(DETECTOR_MAX_LENGTH));
  });

  it('does not pretend the cap is a defence against backtracking', () => {
    // Six characters, and the reason the cap's docstring says what it does.
    expect(validateDetector('(a+)+$')).toBeNull();
  });

  it("stays out of Python's dialect rather than inventing a rule", () => {
    // `new RegExp` cannot parse either of these; Python's `re` runs both, and
    // the card refusing them would be a rule the runtime does not have.
    expect(validateDetector('(?P<year>\\d{4})')).toBeNull();
    expect(validateDetector('(?i)hello')).toBeNull();
  });

  it('still checks a pattern that only looks Python-flavoured', () => {
    // The control for the escape hatch above: `(?:` is ordinary in both
    // dialects, so a broken one must still be caught.
    expect(validateDetector('(?:unclosed')).toContain('Not a valid pattern');
  });
});
