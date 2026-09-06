import { describe, expect, it } from 'vitest';

import { graderVerdictLine } from './graderVerdictLine';

describe('graderVerdictLine', () => {
  it('says nothing at all when no grader produced the candidate', () => {
    expect(graderVerdictLine({ verdict: '', reason: '' })).toBe('');
  });

  it('reports a revision request with the grader’s own sentence', () => {
    expect(graderVerdictLine({ verdict: 'revise', reason: "'if appropriate' is a hedge." })).toBe(
      "The grader asked for a revision — 'if appropriate' is a hedge.",
    );
  });

  it('reports a pass with the grader’s own sentence', () => {
    // `workflow-gallery` 53. This case used to read `reason: 'Grader passed it'`
    // — a fixture faithfully copying a backend constant that restated
    // `passed=true` and told the reviewer nothing. `BaseGrader.normalise` now
    // carries whatever the model wrote after the keyword, condensed to one
    // bounded line, so the two halves of this sentence no longer say the same
    // thing twice.
    expect(
      graderVerdictLine({
        verdict: 'pass',
        reason: 'It apologises plainly and commits to a date, with no hedging.',
      }),
    ).toBe(
      'The grader passed this — It apologises plainly and commits to a date, with no hedging.',
    );
  });

  it('reports a pass the grader did not explain, as an absence', () => {
    // A bare `PASS` is a legitimate and common reply, and the backend reports
    // it as an absence rather than inventing prose. What matters here is that
    // a reviewer can tell it apart from the case above — *the grader said why*
    // versus *the grader just said pass* — which is exactly what the old
    // constant made impossible.
    expect(graderVerdictLine({ verdict: 'pass', reason: 'No reason given' })).toBe(
      'The grader passed this — No reason given',
    );
  });

  it('still names the verdict when the grader gave no reason', () => {
    expect(graderVerdictLine({ verdict: 'revise', reason: '   ' })).toBe(
      'The grader asked for a revision.',
    );
  });

  it('quotes the reason without captioning it when the label is unknown', () => {
    // A label this build does not understand is not a licence to guess which
    // of the two known meanings it had.
    expect(graderVerdictLine({ verdict: 'sideways', reason: 'something else happened' })).toBe(
      'something else happened',
    );
  });
  it('tells a reviewer when no model formed the revision opinion', () => {
    // `production-ready` 92: the gate is the second door onto one judgement,
    // and it must not disagree with the trace row. Both paths here, because a
    // card that reads the same either way is the same defect the trace had.
    const judged = graderVerdictLine({
      verdict: 'revise',
      reason: "'if appropriate' is a hedge.",
    });
    const skipped = graderVerdictLine({
      verdict: 'revise',
      reason: 'The answer is empty.',
      check: 'empty',
    });
    expect(judged).toBe("The grader asked for a revision — 'if appropriate' is a hedge.");
    expect(skipped).toBe(
      'The grader asked for a revision without a model call — The answer is empty.',
    );
    expect(skipped).not.toBe(judged);
  });

  it('keeps the clause when the reason is missing', () => {
    expect(graderVerdictLine({ verdict: 'revise', reason: '', check: 'empty' })).toBe(
      'The grader asked for a revision without a model call.',
    );
  });
});
