import { describe, expect, it } from 'vitest';

import type { ModelSpend, SessionSpend, Spend } from '@core/runtime/RuntimeClient';

import { sessionSpan, tablesFor } from './spendDialogModel';

/**
 * The breakdown's three tables, decided without a renderer.
 *
 * `stable-beta-public/03`, slice 5. Same split as `spendModel.test.ts`: what
 * a cell *says* is a judgement about what the product claims to know — the
 * dash rule, which sitting is this tab's, what order the rows are in — and a
 * judgement is checkable without a DOM. `SpendDialog.tsx` is then markup.
 */
const NOTHING_REPORTED = '—';

function model(over: Partial<ModelSpend> = {}): ModelSpend {
  return {
    model: 'gpt-oss:120b-cloud',
    inputTokens: 1000,
    outputTokens: 200,
    totalTokens: 1200,
    cachedTokens: null,
    cacheCreationTokens: null,
    reasoningTokens: null,
    runs: 3,
    ...over,
  };
}

function sitting(over: Partial<SessionSpend> = {}): SessionSpend {
  return {
    sessionId: 'tab-a',
    firstAt: '2026-09-04T09:12:03+02:00',
    lastAt: '2026-09-04T11:30:41+02:00',
    runs: 14,
    totalTokens: 201880,
    ...over,
  };
}

function spend(over: Partial<Spend> = {}): Spend {
  return {
    grandTotal: 1200,
    cachedTotal: null,
    byModel: [model()],
    sessionByModel: [],
    sessionTotal: 0,
    sessions: [sitting()],
    ...over,
  };
}

describe('the grand total table', () => {
  it('prints one row per model and a footer for all of them', () => {
    const tables = tablesFor(
      spend({
        grandTotal: 1_284_910,
        byModel: [
          model({ model: 'gpt-oss:120b-cloud', inputTokens: 804_100, outputTokens: 210_300 }),
          model({ model: 'claude-sonnet-5', inputTokens: 190_200, outputTokens: 80_310 }),
        ],
      }),
      'tab-a',
    );

    expect(tables.byModel.map((row) => row.model)).toEqual([
      'gpt-oss:120b-cloud',
      'claude-sonnet-5',
    ]);
    expect(tables.allModels.input).toBe('994,300');
    expect(tables.allModels.output).toBe('290,610');
    // The footer's total is the *server's* grand total, not a second sum of
    // the same rows: one definition of what the work cost, published once.
    expect(tables.allModels.total).toBe('1,284,910');
  });

  it('prints a dash for a detail nobody reported and a zero for one that was', () => {
    const tables = tablesFor(
      spend({
        cachedTotal: 0,
        byModel: [model({ cachedTokens: 0, reasoningTokens: null })],
      }),
      'tab-a',
    );

    expect(tables.byModel[0]?.cached).toBe('0');
    expect(tables.byModel[0]?.reasoning).toBe(NOTHING_REPORTED);
    expect(tables.allModels.cached).toBe('0');
    expect(tables.allModels.reasoning).toBe(NOTHING_REPORTED);
  });

  it('sums a reasoning figure only across the rows that carry one', () => {
    const tables = tablesFor(
      spend({
        byModel: [
          model({ model: 'a', reasoningTokens: 900 }),
          model({ model: 'b', reasoningTokens: null }),
        ],
      }),
      'tab-a',
    );

    // 900, never 900 + 0: the second model did not report nothing, it
    // reported nothing at all.
    expect(tables.allModels.reasoning).toBe('900');
  });
});

describe("this session's table", () => {
  it('carries runs, cache and total for each model in the response order', () => {
    const tables = tablesFor(
      spend({
        sessionByModel: [
          model({
            model: 'gpt-oss:120b-cloud',
            runs: 5,
            cachedTokens: 12_000,
            totalTokens: 41_900,
          }),
          model({ model: 'claude-sonnet-5', runs: 1, cachedTokens: null, totalTokens: 6_310 }),
        ],
      }),
      'tab-a',
    );

    expect(tables.session).toEqual([
      { model: 'gpt-oss:120b-cloud', runs: '5', cached: '12,000', total: '41,900' },
      { model: 'claude-sonnet-5', runs: '1', cached: NOTHING_REPORTED, total: '6,310' },
    ]);
  });

  it('is empty when this sitting has run nothing', () => {
    expect(tablesFor(spend(), 'tab-a').session).toEqual([]);
  });
});

describe('the sessions table', () => {
  it('marks the current tab and nothing else', () => {
    const tables = tablesFor(
      spend({
        sessions: [
          sitting({ sessionId: 'tab-b' }),
          sitting({ sessionId: 'tab-a' }),
          sitting({ sessionId: 'tab-c' }),
        ],
      }),
      'tab-a',
    );

    expect(tables.sessions.map((row) => row.current)).toEqual([false, true, false]);
  });

  it('marks nothing when this tab has no recorded sitting yet', () => {
    const tables = tablesFor(spend({ sessions: [sitting({ sessionId: 'tab-b' })] }), 'tab-a');

    expect(tables.sessions.some((row) => row.current)).toBe(false);
  });

  it('keeps the order the server sent, newest first', () => {
    // `SessionSpend.lastAt` carries an offset and does not sort as text
    // (`the-cost-of-one-more/11`), so the ordering is the server's derived
    // key and this model must never re-sort it.
    const tables = tablesFor(
      spend({
        sessions: [
          sitting({ sessionId: 'newest', lastAt: '2026-09-04T11:30:41+02:00' }),
          sitting({ sessionId: 'older', lastAt: '2026-09-04T12:30:41+09:00' }),
        ],
      }),
      'tab-a',
    );

    expect(tables.sessions.map((row) => row.sessionId)).toEqual(['newest', 'older']);
  });
});

describe('a sitting reads as a span', () => {
  it('prints the day once when it started and ended on the same one', () => {
    expect(sessionSpan('2026-09-04T09:12:03+02:00', '2026-09-04T11:30:41+02:00')).toBe(
      '2026-09-04 09:12 — 11:30',
    );
  });

  it('prints both days when it crossed one', () => {
    expect(sessionSpan('2026-09-04T23:12:03+02:00', '2026-09-05T01:30:41+02:00')).toBe(
      '2026-09-04 23:12 — 2026-09-05 01:30',
    );
  });

  it('shows a stamp it cannot read rather than guessing at one', () => {
    // The stored spelling is the truth and is never re-parsed into a `Date`:
    // that would shift it into whatever zone the browser is in and quietly
    // relabel a run somebody remembers making at nine in the morning.
    expect(sessionSpan('unknown', 'also unknown')).toBe('unknown — also unknown');
  });
});
