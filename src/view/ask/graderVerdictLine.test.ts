import { describe, expect, it } from 'vitest';

import { graderVerdictLine } from './graderVerdictLine';

describe('graderVerdictLine', () => {
  it('says nothing at all when no grader produced the candidate', () => {
    expect(graderVerdictLine({ verdict: '', reason: '' })).toBe('');
  });

  it('reports a revision request with the grader’s own sentence', () => {
    expect(
      graderVerdictLine({ verdict: 'revise', reason: "'if appropriate' is a hedge." }),
    ).toBe("The grader asked for a revision — 'if appropriate' is a hedge.");
  });

  it('reports a pass', () => {
    expect(graderVerdictLine({ verdict: 'pass', reason: 'Grader passed it' })).toBe(
      'The grader passed this — Grader passed it',
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
});
