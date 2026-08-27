import { describe, expect, it } from 'vitest';
import { NARRATION_STACK_LIMIT, pushNarration } from './narrationStack';

describe('pushNarration', () => {
  it('appends a line', () => {
    expect(pushNarration([], 'Searching the web.')).toEqual(['Searching the web.']);
  });

  it('collapses a line repeated back to back', () => {
    const once = pushNarration([], 'Thinking about the next step.');
    const twice = pushNarration(once, 'Thinking about the next step.');
    expect(twice).toEqual(['Thinking about the next step.']);
  });

  it('returns the same reference when nothing changed, so no card re-renders', () => {
    const once = pushNarration([], 'Thinking about the next step.');
    expect(pushNarration(once, 'Thinking about the next step.')).toBe(once);
    expect(pushNarration(once, '   ')).toBe(once);
  });

  it('keeps a repeat that is not consecutive', () => {
    let stack = pushNarration([], 'Running a query against the data.');
    stack = pushNarration(stack, 'Thinking about the next step.');
    stack = pushNarration(stack, 'Running a query against the data.');
    expect(stack).toEqual([
      'Running a query against the data.',
      'Thinking about the next step.',
      'Running a query against the data.',
    ]);
  });

  it('drops a frame that said nothing', () => {
    expect(pushNarration([], '')).toEqual([]);
    expect(pushNarration([], '  \n ')).toEqual([]);
  });

  it('trims, so whitespace does not defeat the repeat check', () => {
    const once = pushNarration([], 'Searching the web.');
    expect(pushNarration(once, '  Searching the web.  ')).toBe(once);
  });

  it('caps the stack, keeping the most recent lines', () => {
    let stack: readonly string[] = [];
    for (let i = 0; i < 10; i += 1) stack = pushNarration(stack, `line ${i}`, 4);
    expect(stack).toEqual(['line 6', 'line 7', 'line 8', 'line 9']);
  });

  it('has a limit generous enough for an ordinary run', () => {
    expect(NARRATION_STACK_LIMIT).toBeGreaterThanOrEqual(100);
  });
});
