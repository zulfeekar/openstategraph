import type { ModelSpend, Spend } from '@core/runtime/RuntimeClient';

import { formatTokens, reportedTokens } from './spendModel';

/**
 * The three tables the breakdown shows, as strings — pure, no React.
 *
 * `stable-beta-public/03`, slice 5. Same reason `spendModel.ts` exists: the
 * decisions in here are about what the product *claims to know* — a dash is
 * not a zero, this row is your tab, this order came from the server — and
 * none of them need a DOM to be wrong in. `SpendDialog.tsx` is markup over
 * this and holds no arithmetic of its own.
 */

/** One model's all-time line in the grand-total table, and its footer. */
export interface ModelTotalRow {
  readonly model: string;
  readonly input: string;
  readonly output: string;
  /** `'—'` when no run on this model reported a cache-read figure. */
  readonly cached: string;
  /** `'—'` when no run on this model reported a reasoning figure. */
  readonly reasoning: string;
  readonly total: string;
}

/** One model's line in this sitting's table. */
export interface SessionModelRow {
  readonly model: string;
  readonly runs: string;
  readonly cached: string;
  readonly total: string;
}

/** One sitting's line in the sessions table. */
export interface SittingRow {
  readonly sessionId: string;
  /** `'2026-09-04 09:12 — 11:30'`, from the stored spelling. */
  readonly span: string;
  readonly runs: string;
  readonly total: string;
  /** True for the sitting this browser tab is making right now. */
  readonly current: boolean;
}

export interface SpendTables {
  readonly byModel: readonly ModelTotalRow[];
  /**
   * The footer of the first table — every model at once.
   *
   * Its `total` and `cached` are the **server's own** `grandTotal` and
   * `cachedTotal` rather than a second sum over `byModel`. Two sums of one
   * quantity agree on the day they are written and drift on the first change
   * to either walk; the wire already publishes the answer, so this reads it.
   */
  readonly allModels: ModelTotalRow;
  readonly session: readonly SessionModelRow[];
  readonly sessions: readonly SittingRow[];
}

/** The label the footer row carries. One copy, so the test and the table
 *  cannot disagree about it. */
export const ALL_MODELS = 'All models';

/** The response as three tables, in the response's own order. */
export function tablesFor(spend: Spend, currentSessionId: string): SpendTables {
  return {
    byModel: spend.byModel.map((row) => ({
      model: row.model,
      input: formatTokens(row.inputTokens),
      output: formatTokens(row.outputTokens),
      cached: reportedTokens(row.cachedTokens),
      reasoning: reportedTokens(row.reasoningTokens),
      total: formatTokens(row.totalTokens),
    })),
    allModels: {
      model: ALL_MODELS,
      input: formatTokens(sum(spend.byModel, (row) => row.inputTokens)),
      output: formatTokens(sum(spend.byModel, (row) => row.outputTokens)),
      cached: reportedTokens(spend.cachedTotal),
      reasoning: reportedTokens(sumReported(spend.byModel, (row) => row.reasoningTokens)),
      total: formatTokens(spend.grandTotal),
    },
    session: spend.sessionByModel.map((row) => ({
      model: row.model,
      runs: formatTokens(row.runs),
      cached: reportedTokens(row.cachedTokens),
      total: formatTokens(row.totalTokens),
    })),
    // Never re-sorted: the order is the server's derived key
    // (`the-cost-of-one-more/11`), and `lastAt` carries an offset that does
    // not sort as text — a client that re-ordered it would put the wrong
    // order back.
    sessions: spend.sessions.map((row) => ({
      sessionId: row.sessionId,
      span: sessionSpan(row.firstAt, row.lastAt),
      runs: formatTokens(row.runs),
      total: formatTokens(row.totalTokens),
      current: row.sessionId === currentSessionId,
    })),
  };
}

function sum(rows: readonly ModelSpend[], of: (row: ModelSpend) => number): number {
  return rows.reduce((running, row) => running + of(row), 0);
}

/**
 * The tri-state, summed: `null` unless at least one row reported a figure.
 *
 * A missing detail is not a zero, so a table of rows that all said nothing
 * must total to *nothing* rather than to `0` — the same rule the store
 * applies to `cached_total`, applied to the columns the wire does not total
 * for us.
 */
function sumReported(
  rows: readonly ModelSpend[],
  of: (row: ModelSpend) => number | null,
): number | null {
  const reported = rows.map(of).filter((value): value is number => value !== null);
  return reported.length === 0 ? null : reported.reduce((running, value) => running + value, 0);
}

/**
 * `'2026-09-04 09:12 — 11:30'` — when a sitting ran, as stored.
 *
 * **Sliced, never parsed.** These stamps carry an offset and the store keeps
 * the spelling the run was recorded with; handing one to `new Date()` would
 * re-render it in whatever zone the reader's browser is in, quietly relabelling
 * a run somebody remembers making at nine in the morning. A stamp this cannot
 * read is shown as it arrived rather than guessed at.
 */
export function sessionSpan(firstAt: string, lastAt: string): string {
  const from = stamp(firstAt);
  const to = stamp(lastAt);
  if (from === null || to === null) return `${firstAt} — ${lastAt}`;
  // The day is dropped from the end only when it is the same day — a sitting
  // that ran past midnight says so.
  const end = from.day === to.day ? to.minute : `${to.day} ${to.minute}`;
  return `${from.day} ${from.minute} — ${end}`;
}

/** `'2026-09-04T09:12:03+02:00'` → day and minute, or `null`. */
function stamp(value: string): { day: string; minute: string } | null {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value);
  if (match === null) return null;
  return { day: match[1] ?? '', minute: match[2] ?? '' };
}
