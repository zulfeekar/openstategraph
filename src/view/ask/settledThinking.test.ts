import { describe, expect, it } from 'vitest';

import { showsThinking } from './settledThinking';

/**
 * `every-workflow-green` 10 — the answer was printed twice, once as the
 * settled thinking block and once as the answer.
 */
describe('showsThinking', () => {
  const turn = (over: Partial<Parameters<typeof showsThinking>[0]> = {}) => ({
    thinking: 'Rock earns the most, $826.65.',
    running: false,
    answer: 'Rock earns the most, $826.65.\n\nrouter1 b-music',
    ...over,
  });

  it('shows the tokens while they are still arriving', () => {
    expect(showsThinking(turn({ running: true, answer: '' }))).toBe(true);
  });

  it('hides them once the turn has settled and an answer was published', () => {
    expect(showsThinking(turn())).toBe(false);
  });

  it('does not depend on the two strings matching', () => {
    // The observed case: the answer was the thinking *plus* a routing footer,
    // so an equality or prefix test would have let the duplicate through.
    expect(showsThinking(turn({ answer: 'A completely different sentence.' }))).toBe(false);
  });

  it('keeps them when the run settled without publishing an answer', () => {
    expect(showsThinking(turn({ answer: '' }))).toBe(true);
    expect(showsThinking(turn({ answer: '   ' }))).toBe(true);
  });

  it('shows nothing when no token ever arrived', () => {
    expect(showsThinking(turn({ thinking: '', running: true, answer: '' }))).toBe(false);
  });
});
