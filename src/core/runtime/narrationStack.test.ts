import { describe, expect, it } from 'vitest';
import { NARRATION_STACK_LIMIT, pushNarration } from './narrationStack';

describe('pushNarration', () => {
  it('appends a line', () => {
    expect(pushNarration([], 'Searching the web.')).toEqual(['Searching the web.']);
  });

  it('keeps a line repeated back to back, because twice is not once', () => {
    // `launch-readiness/145` reverses the collapse this function shipped
    // with. Its only stated reason was `before_model`'s identical line, which
    // `145` stopped authoring; what it still did was hide a real repeat. An
    // agent reading the same file six times running is `146`, and a panel
    // that shows that once is a panel that lost the evidence.
    const once = pushNarration([], 'Reading a file it has open.');
    const twice = pushNarration(once, 'Reading a file it has open.');
    expect(twice).toEqual(['Reading a file it has open.', 'Reading a file it has open.']);
  });

  it('shows a storm of identical calls as a storm', () => {
    let stack: readonly string[] = [];
    for (let i = 0; i < 6; i += 1) stack = pushNarration(stack, 'Reading a file it has open.');
    expect(stack).toHaveLength(6);
  });

  it('returns the same reference for a frame that said nothing, so no card re-renders', () => {
    const once = pushNarration([], 'Searching the web.');
    expect(pushNarration(once, '   ')).toBe(once);
    expect(pushNarration(once, '')).toBe(once);
  });

  it('keeps a repeat that is not consecutive', () => {
    let stack = pushNarration([], 'Running a query against the data.');
    stack = pushNarration(stack, 'Found 68 rows across 2 columns.');
    stack = pushNarration(stack, 'Running a query against the data.');
    expect(stack).toEqual([
      'Running a query against the data.',
      'Found 68 rows across 2 columns.',
      'Running a query against the data.',
    ]);
  });

  it('drops a frame that said nothing', () => {
    expect(pushNarration([], '')).toEqual([]);
    expect(pushNarration([], '  \n ')).toEqual([]);
  });

  it('trims the line it stores', () => {
    expect(pushNarration([], '  Searching the web.  ')).toEqual(['Searching the web.']);
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
