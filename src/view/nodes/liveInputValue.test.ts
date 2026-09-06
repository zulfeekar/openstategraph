import { describe, expect, it } from 'vitest';
import { liveInputValue } from './liveInputValue';

describe('liveInputValue — the question the run is carrying', () => {
  const saved = 'Which genre earns the most revenue? Name the genre and the figure.';

  it('reports the live question when it differs from the saved one', () => {
    // The reported bug: a mounted child's card showed `saved` throughout a run
    // that was asking something else entirely.
    expect(liveInputValue('Which five artists earn the most?', saved)).toBe(
      'Which five artists earn the most?',
    );
  });

  it('says nothing when the run used the saved prompt', () => {
    // Repeating the field under a second heading is noise, not truth.
    expect(liveInputValue(saved, saved)).toBeNull();
  });

  it('ignores whitespace-only disagreement', () => {
    expect(liveInputValue(`  ${saved}\n`, saved)).toBeNull();
  });

  it('says nothing before anything has run', () => {
    expect(liveInputValue(null, saved)).toBeNull();
    expect(liveInputValue(undefined, saved)).toBeNull();
    expect(liveInputValue('', saved)).toBeNull();
    expect(liveInputValue('   ', saved)).toBeNull();
  });

  it('says nothing for a non-string output', () => {
    // `runtime.output` is typed loosely; a node that reported a structure has
    // not reported a question.
    expect(liveInputValue({ question: 'x' }, saved)).toBeNull();
    expect(liveInputValue(42, saved)).toBeNull();
  });

  it('reports the live question when nothing is saved at all', () => {
    // `concierge`'s own entry node is deliberately blank — its question always
    // arrives at run time, so this note is the only place it is ever visible
    // on the card.
    expect(liveInputValue('Hello there', '')).toBe('Hello there');
  });
});
