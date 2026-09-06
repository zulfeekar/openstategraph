import { describe, expect, it } from 'vitest';

import type { Spend } from '@core/runtime/RuntimeClient';

import { cellsFor, formatTokens } from './spendModel';

/**
 * The bar's words, decided away from React.
 *
 * `stable-beta-public/03`. The one rule the whole feature turns on lives here
 * rather than in the component: **a cell says `—` when nobody reported a
 * figure, and `0` when somebody reported nothing spent.** Those are different
 * sentences about different worlds, and the moment a `?? 0` appears anywhere
 * between the wire and the pixel the product starts claiming a measurement it
 * never made.
 */
const EMPTY: Spend = {
  grandTotal: 0,
  cachedTotal: null,
  byModel: [],
  sessionByModel: [],
  sessionTotal: 0,
  sessions: [],
};

describe('what a spend cell says', () => {
  it('says nothing at all before the first answer arrives', () => {
    // Slice 1's whole visible behaviour: the bar is on screen with no numbers
    // in it yet. Four dashes, not four zeros — the backend has not answered.
    expect(cellsFor(null)).toEqual({
      grandTotal: '—',
      cached: '—',
      session: '—',
      sessionModels: '',
    });
  });

  it('prints a reported zero as a zero', () => {
    // A fresh install really has spent nothing, and that is a measurement.
    expect(cellsFor(EMPTY).grandTotal).toBe('0');
    expect(cellsFor(EMPTY).session).toBe('0');
  });

  it('prints an unreported figure as a dash even when the rest is known', () => {
    // The tri-state, at the one place a reader meets it. `cachedTotal: null`
    // is *no provider told us*, and it must not borrow the zero next to it.
    expect(cellsFor({ ...EMPTY, grandTotal: 12, cachedTotal: null }).cached).toBe('—');
    expect(cellsFor({ ...EMPTY, cachedTotal: 0 }).cached).toBe('0');
  });

  it('groups thousands the same way on every machine', () => {
    // Pinned rather than `toLocaleString()`: a suite that passed in en-US and
    // failed in de-DE would be a test about the machine, not about the bar.
    expect(formatTokens(1284910)).toBe('1,284,910');
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(999)).toBe('999');
    expect(formatTokens(1000)).toBe('1,000');
  });

  it('lists this sitting"s models in the order the server sent them', () => {
    const spend: Spend = {
      ...EMPTY,
      sessionByModel: [
        {
          model: 'gpt-oss:120b-cloud',
          inputTokens: 10,
          outputTokens: 5,
          totalTokens: 15,
          cachedTokens: null,
          cacheCreationTokens: null,
          reasoningTokens: null,
          runs: 1,
        },
        {
          model: 'claude-sonnet-4',
          inputTokens: 2000,
          outputTokens: 100,
          totalTokens: 2100,
          cachedTokens: 40,
          cacheCreationTokens: null,
          reasoningTokens: null,
          runs: 2,
        },
      ],
    };

    // Largest-first is the *server's* decision (`by_model` is ordered there);
    // re-sorting here would be a second opinion about it, which is the defect
    // `the-cost-of-one-more/11` records for the sessions list.
    expect(cellsFor(spend).sessionModels).toBe('gpt-oss:120b-cloud 15 · claude-sonnet-4 2,100');
  });

  it('says nothing rather than an empty separator when no model ran', () => {
    expect(cellsFor(EMPTY).sessionModels).toBe('');
  });
});
