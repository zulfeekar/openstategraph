import type { Spend } from '@core/runtime/RuntimeClient';

/**
 * The four things the status bar says, as strings.
 *
 * Pure, and deliberately not a component's business: the bar's one real rule
 * — **a dash is not a zero** — is a decision about what the product claims to
 * know, and a decision like that belongs somewhere a test can reach without a
 * DOM (`stable-beta-public/03`).
 */
export interface SpendCells {
  readonly grandTotal: string;
  /** `'—'` when no provider reported a cache figure. */
  readonly cached: string;
  readonly session: string;
  /** `'model n · model n'`, or `''` when this sitting has run nothing. */
  readonly sessionModels: string;
}

/** What a cell says when there is nothing to say. */
const NOTHING_REPORTED = '—';

/**
 * The response as four sentences — or four dashes before it has arrived.
 *
 * `null` is *the answer is not here yet*, which covers the first paint and an
 * unreachable backend alike. Neither is evidence that anything cost zero.
 */
export function cellsFor(spend: Spend | null): SpendCells {
  if (spend === null) {
    return {
      grandTotal: NOTHING_REPORTED,
      cached: NOTHING_REPORTED,
      session: NOTHING_REPORTED,
      sessionModels: '',
    };
  }
  return {
    grandTotal: formatTokens(spend.grandTotal),
    cached: reported(spend.cachedTotal),
    session: formatTokens(spend.sessionTotal),
    sessionModels: spend.sessionByModel
      .map((row) => `${row.model} ${formatTokens(row.totalTokens)}`)
      .join(' · '),
  };
}

/**
 * A three-valued figure, as one word.
 *
 * The whole tri-state, in one function so there is one place to read it:
 * `null` is *nobody told us* and prints as a dash; `0` is *we were told, and
 * it was nothing* and prints as a zero.
 */
function reported(value: number | null): string {
  return value === null ? NOTHING_REPORTED : formatTokens(value);
}

/**
 * `1284910` → `'1,284,910'`.
 *
 * Grouped by hand rather than with `toLocaleString()`: the latter answers
 * differently on a machine set to `de-DE`, which would make this a property of
 * whoever ran the suite. A comma every three digits is what the mockup shows
 * and what the tests pin.
 */
export function formatTokens(count: number): string {
  const digits = String(Math.trunc(Math.abs(count)));
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return count < 0 ? `-${grouped}` : grouped;
}
