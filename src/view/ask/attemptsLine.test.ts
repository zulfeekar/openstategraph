import { describe, expect, it } from 'vitest';

import { attemptsLine } from './attemptsLine';

/**
 * `every-workflow-green` 21 — `chained-summarizer` has no grader, and the
 * panel told the user "2 attempts before the grader passed it".
 */
describe('attemptsLine', () => {
  it('says nothing about a grader, because the count is not about graders', () => {
    const line = attemptsLine({ attempts: 2, decisions: {} });
    expect(line).not.toMatch(/grader/i);
    expect(line).toContain('2');
  });

  it('is silent for a single step', () => {
    expect(attemptsLine({ attempts: 1, decisions: {} })).toBe('');
    expect(attemptsLine({ attempts: 0, decisions: {} })).toBe('');
  });

  it('still reports the count when a grader did run', () => {
    // The number is honest either way; what it must not do is attribute it.
    expect(attemptsLine({ attempts: 3, decisions: { grader1: 'pass' } })).toContain('3');
  });

  it('survives a missing or nonsense count', () => {
    expect(attemptsLine({ attempts: Number.NaN, decisions: {} })).toBe('');
  });
});
