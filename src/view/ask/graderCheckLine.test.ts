import { describe, expect, it } from 'vitest';
import { graderCheckLine } from './graderCheckLine';

/**
 * `production-ready` 92. Both paths in every test, because a row that says the
 * same thing either way is the defect — a marker that merely survives the wire
 * proves nothing a reader can use.
 */
describe('graderCheckLine', () => {
  const judged = { check: '', reason: '' };

  it('says nothing at all for a verdict a model formed', () => {
    expect(graderCheckLine(judged)).toBe('');
  });

  it('distinguishes a skipped model call from a judged one', () => {
    const skipped = graderCheckLine({ check: 'empty', reason: 'The answer is empty.' });
    expect(skipped).not.toBe(graderCheckLine(judged));
    expect(skipped).toBe('rejected without a model call — The answer is empty.');
  });

  it('quotes the reason rather than captioning the check name', () => {
    // `check` is an open set: `BaseGrader.deterministic_checks` names
    // `empty` and `error`, and a subclass overriding `deterministic_checks`
    // may name its own (a fixture in `backend/tests/test_grader.py` adds
    // `no_figure`, which is not a built-in check). A lookup table would
    // print nothing for a name it had not met.
    expect(graderCheckLine({ check: 'no_figure', reason: 'No figure was cited.' })).toBe(
      'rejected without a model call — No figure was cited.',
    );
  });

  it('still reports the skipped call when the reason is missing', () => {
    expect(graderCheckLine({ check: 'empty', reason: '   ' })).toBe(
      'rejected without a model call',
    );
  });

  it('says nothing when a reason arrives with no check', () => {
    // Absence of `check` is the value — it means no deterministic check fired,
    // which covers an ordinary pass and a model's rejection alike. Speaking
    // here would tell a reader no model ran when one did.
    expect(graderCheckLine({ check: '', reason: 'The grader disliked the tone.' })).toBe('');
  });

  it('is undisturbed by a row that is not a grader at all', () => {
    expect(graderCheckLine({})).toBe('');
  });
});
