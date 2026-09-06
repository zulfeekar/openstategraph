import { describe, expect, it } from 'vitest';
import type { RecordedRun } from './RecordedRunsClient';
import { groupRecordedRuns, sittingLabel, NO_SITTING } from './recordedRunTree';

const run = (
  at: string,
  sessionId: string,
  threadId: string,
  workflowSlug = 'chinook-assistant',
): RecordedRun => ({
  at,
  workflowSlug,
  threadId,
  sessionId,
  question: `q@${at}`,
  answer: 'a',
  seconds: 1,
  attempts: 0,
  failed: false,
  usage: [{ model: 'gpt-oss:120b-cloud', inputTokens: 4, outputTokens: 6, totalTokens: 10 }],
  bursts: [],
});

/** The listing's own order: newest first, as the store's index produced it. */
const LISTING: readonly RecordedRun[] = [
  run('2026-08-30T09:06:00+0000', '', 't-d', 'stress-review'),
  run('2026-08-30T09:05:00+0000', 's-2', 't-c', 'stress-review'),
  run('2026-08-30T09:02:00+0000', 's-1', 't-b'),
  run('2026-08-30T09:00:30+0000', 's-1', 't-a'),
  run('2026-08-30T09:00:00+0000', 's-1', 't-a'),
];

describe('the levels that genuinely exist', () => {
  it('groups a sitting, then a conversation, then its turns', () => {
    const tree = groupRecordedRuns(LISTING);
    expect(tree.map((sitting) => sitting.sessionId)).toEqual(['', 's-2', 's-1']);
    expect(tree[2]?.threads.map((thread) => thread.threadId)).toEqual(['t-b', 't-a']);
    expect(tree[2]?.threads[1]?.turns).toHaveLength(2);
  });

  it('keeps the order it was handed at every level', () => {
    // `the-cost-of-one-more/11`: newest-first is a derived indexed sort key on
    // the server, because `at` is local wall clock with an offset and does not
    // sort as text. Grouping preserves encounter order rather than re-sorting,
    // so the wrong order cannot be reintroduced here.
    const tree = groupRecordedRuns(LISTING);
    expect(tree.flatMap((s) => s.threads.flatMap((t) => t.turns.map((r) => r.at)))).toEqual(
      LISTING.map((r) => r.at),
    );
  });

  it('gives a sitting nobody minted its own group rather than folding it away', () => {
    // The MCP and CLI doors mint no session, and `''` means *this run had no
    // sitting*. A group that quietly merged those into some other sitting
    // would claim a browser tab that never existed.
    const tree = groupRecordedRuns(LISTING);
    expect(tree[0]?.sessionId).toBe('');
    expect(tree[0]?.threads.map((thread) => thread.threadId)).toEqual(['t-d']);
  });

  it('does not invent a fourth level', () => {
    // The owner asked for session -> thread -> subthread. Nothing in this
    // store records a subthread and nothing here mints one: the third rung is
    // a **turn**, which is what `RunRecord` calls a row and what the store
    // actually appends one of per question asked.
    const tree = groupRecordedRuns(LISTING);
    expect(Object.keys(tree[2]?.threads[1] ?? {}).sort()).toEqual([
      'threadId',
      'totalTokens',
      'turns',
      'workflowSlug',
    ]);
  });

  it('carries the workflow onto the conversation, because a thread has exactly one', () => {
    expect(groupRecordedRuns(LISTING)[1]?.threads[0]?.workflowSlug).toBe('stress-review');
  });

  it('adds a conversation up from the turns it holds', () => {
    expect(groupRecordedRuns(LISTING)[2]?.threads[1]?.totalTokens).toBe(20);
  });

  it('says nothing rather than zero when no turn reported a spend', () => {
    const untold = LISTING.map((turn) => ({ ...turn, usage: null }));
    expect(groupRecordedRuns(untold)[0]?.threads[0]?.totalTokens).toBeNull();
  });

  it('is empty for an empty store, which is an answer', () => {
    expect(groupRecordedRuns([])).toEqual([]);
  });
});

describe('what a sitting is called', () => {
  it('names the sitting it has', () => {
    expect(sittingLabel('s-1')).toBe('Sitting s-1');
  });

  it('says an absent sitting is absent, and never guesses one', () => {
    expect(sittingLabel('')).toBe(NO_SITTING);
    expect(NO_SITTING).toMatch(/no sitting/i);
  });
});
