import type { RecordedRun } from './RecordedRunsClient';

/**
 * The stored runs, grouped by the levels this store genuinely records.
 *
 * `memory-and-replay` 73. The owner asked for **session → thread → subthread →
 * timeline**. Three of those four exist and one does not, and this module is
 * where that is settled rather than papered over:
 *
 * | asked for | in the store | here |
 * | --- | --- | --- |
 * | session | `session_id`, a column, indexed, minted per browser tab | a sitting |
 * | thread | `thread_id`, LangGraph's own key for one conversation | a conversation |
 * | subthread | **nothing** — the word appears nowhere in this repository | — |
 * | | `runs` is appended one row per **turn** | a turn |
 *
 * So the third rung is a turn: one question asked and answered inside a
 * conversation. That is a real level with a real row behind it, and it is what
 * a reader actually picks a recording from. **A hierarchy with an empty rung
 * is worse than three honest levels**, so no fourth is minted, and
 * `recordedRunTree.test.ts` pins the shape against a level being invented
 * later to satisfy the sentence.
 *
 * ## The order is the server's, at every level
 *
 * `the-cost-of-one-more/11` made *newest first* a derived indexed sort key,
 * because `at` is local wall clock with an offset and sorting it as text sorts
 * the same instant a day apart. This groups by **encounter order** — a sitting
 * takes the position of its newest run, a conversation the position of its
 * newest turn — so the listing's order survives grouping instead of being
 * replaced by an opinion formed here.
 *
 * Framework-free and pure: `core/` owes nothing to a view, and the whole
 * interesting part is the grouping, which is tested directly.
 */

/** One conversation — every turn of it that the store kept. */
export interface RecordedThread {
  readonly threadId: string;
  /** A thread belongs to exactly one workflow: it is half the store's own key. */
  readonly workflowSlug: string;
  /** Newest first, as listed. */
  readonly turns: readonly RecordedRun[];
  /**
   * Every turn's reported spend, added up — or `null` when **no** turn in it
   * reported any.
   *
   * A sum is the right shape *here* and only here: this is a row in a picker,
   * and the question it answers is *how heavy was this conversation*. The
   * per-model rows are on every turn and are what the dock reads, so the rule
   * the store states — keyed by model, never summed — is kept where it decides
   * anything. `null` is *nobody told us*, and `0` is *nothing was spent*.
   */
  readonly totalTokens: number | null;
}

/** One sitting — the conversations one browser tab held. */
export interface RecordedSession {
  /** `''` for a run that came through a door that mints none. */
  readonly sessionId: string;
  readonly threads: readonly RecordedThread[];
}

/**
 * What a run with no sitting is called.
 *
 * Never folded into another group and never given a borrowed name: the MCP and
 * CLI doors mint no session, so `''` means *this run had no sitting* rather
 * than *one was lost*, and those are different facts.
 */
export const NO_SITTING = 'Runs with no sitting';

export function sittingLabel(sessionId: string): string {
  return sessionId === '' ? NO_SITTING : `Sitting ${sessionId}`;
}

/**
 * What a conversation spent, or `null` if none of its turns said.
 *
 * A turn with `usage: null` contributes nothing rather than a zero — the
 * `—`-not-`0` rule, one level up from the bar it was written for.
 */
function spendOf(turns: readonly RecordedRun[]): number | null {
  const reported = turns.flatMap((turn) => turn.usage ?? []);
  return turns.every((turn) => turn.usage === null)
    ? null
    : reported.reduce((sum, row) => sum + row.totalTokens, 0);
}

export function groupRecordedRuns(runs: readonly RecordedRun[]): readonly RecordedSession[] {
  const sittings = new Map<string, Map<string, RecordedRun[]>>();
  for (const run of runs) {
    const threads = sittings.get(run.sessionId) ?? new Map<string, RecordedRun[]>();
    sittings.set(run.sessionId, threads);
    const turns = threads.get(run.threadId) ?? [];
    threads.set(run.threadId, turns);
    turns.push(run);
  }
  // Insertion order, both times — which is the listing's order, which is the
  // index's. `Map` iteration is insertion-ordered by specification, so this is
  // the property being relied on rather than a coincidence.
  return [...sittings].map(([sessionId, threads]) => ({
    sessionId,
    threads: [...threads].map(([threadId, turns]) => ({
      threadId,
      workflowSlug: turns[0]?.workflowSlug ?? '',
      turns,
      totalTokens: spendOf(turns),
    })),
  }));
}
