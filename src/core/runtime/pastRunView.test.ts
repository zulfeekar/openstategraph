import { describe, expect, it } from 'vitest';
import type { PastRun, PastRunStep } from './RuntimeClient';
import { describeRun, relativeTime, stepLines, stepTitle } from './pastRunView';

const NOW = Date.parse('2026-08-11T12:00:00Z');

const run = (patch: Partial<PastRun> = {}): PastRun => ({
  threadId: 'th-1',
  workflowSlug: 'chinook-assistant',
  sessionId: '',
  userEmail: '',
  updatedAt: '2026-08-11T11:59:30Z',
  steps: 4,
  question: 'Which genre earned the most revenue?',
  answer: 'Rock, $826.65.',
  status: 'finished',
  ...patch,
});

describe('relativeTime', () => {
  it('says just now inside a minute', () => {
    expect(relativeTime('2026-08-11T11:59:30Z', NOW)).toBe('just now');
  });

  it('counts minutes, then hours, then days', () => {
    expect(relativeTime('2026-08-11T11:40:00Z', NOW)).toBe('20 min ago');
    expect(relativeTime('2026-08-11T09:00:00Z', NOW)).toBe('3 h ago');
    expect(relativeTime('2026-08-09T12:00:00Z', NOW)).toBe('2 d ago');
  });

  it('falls back to the raw stamp rather than inventing a time', () => {
    expect(relativeTime('', NOW)).toBe('');
    expect(relativeTime('not a date', NOW)).toBe('not a date');
  });

  it('never reports a negative age — a clock skew reads as just now', () => {
    expect(relativeTime('2026-08-11T12:00:30Z', NOW)).toBe('just now');
  });
});

describe('describeRun', () => {
  it('titles a run by its question', () => {
    expect(describeRun(run(), NOW).title).toBe('Which genre earned the most revenue?');
  });

  it('says so plainly when a run recorded no question', () => {
    expect(describeRun(run({ question: '' }), NOW).title).toBe('(no question recorded)');
  });

  it('shows identity only when the run carried it', () => {
    expect(describeRun(run(), NOW).identity).toBe('');
    expect(describeRun(run({ userEmail: 'me@example.com' }), NOW).identity).toBe('me@example.com');
    expect(describeRun(run({ sessionId: 'sess-7' }), NOW).identity).toBe('sess-7');
    expect(
      describeRun(run({ userEmail: 'me@example.com', sessionId: 'sess-7' }), NOW).identity,
    ).toBe('me@example.com · sess-7');
  });

  it('reads a paused run as resumable and a finished one as done', () => {
    expect(describeRun(run({ status: 'paused' }), NOW).statusLabel).toBe('waiting for you');
    expect(describeRun(run(), NOW).statusLabel).toBe('finished');
  });

  it('counts steps in words a reader can act on', () => {
    expect(describeRun(run({ steps: 1 }), NOW).meta).toBe('1 step · just now');
    expect(describeRun(run({ steps: 4 }), NOW).meta).toBe('4 steps · just now');
  });
});

describe('stepLines', () => {
  const step = (values: Record<string, string>): PastRunStep => ({
    checkpointId: 'cp-1',
    step: 2,
    at: '2026-08-11T11:59:00Z',
    source: 'loop',
    values,
  });

  it('drops a channel that serialized to an empty container', () => {
    // `{}` and `[]` are what an untouched dict/list channel renders as. They
    // are blank facts printed as punctuation, and a checkpoint of eight of
    // them buries the one line that changed.
    expect(stepLines(step({ outputs: '{}', subtasks: '[]', answer: 'Rock' }))).toEqual([
      { key: 'answer', value: 'Rock' },
    ]);
  });

  it('keeps a container that actually holds something', () => {
    expect(stepLines(step({ outputs: '{"in1": "hi"}' }))).toEqual([
      { key: 'outputs', value: '{"in1": "hi"}' },
    ]);
  });

  it('drops empty values — a blank channel is noise, not history', () => {
    expect(stepLines(step({ question: 'q', answer: '', feedback: '   ' }))).toEqual([
      { key: 'question', value: 'q' },
    ]);
  });

  it('leads with the channels a reader looks for first', () => {
    const lines = stepLines(step({ zeta: 'z', answer: 'a', question: 'q', outputs: 'o' }));
    expect(lines.map((line) => line.key)).toEqual(['question', 'answer', 'outputs', 'zeta']);
  });

  it('is empty for a checkpoint that recorded nothing readable', () => {
    expect(stepLines(step({}))).toEqual([]);
  });
});

describe('stepTitle', () => {
  it('names the superstep and where it came from', () => {
    expect(stepTitle({ checkpointId: 'c', step: 3, at: '', source: 'loop', values: {} })).toBe(
      'Step 3 · loop',
    );
  });

  it('calls the pre-run checkpoint what it is', () => {
    expect(stepTitle({ checkpointId: 'c', step: -1, at: '', source: 'input', values: {} })).toBe(
      'Input · input',
    );
  });

  it('omits an unrecorded source rather than printing an empty tail', () => {
    expect(stepTitle({ checkpointId: 'c', step: 1, at: '', source: '', values: {} })).toBe(
      'Step 1',
    );
  });
});
