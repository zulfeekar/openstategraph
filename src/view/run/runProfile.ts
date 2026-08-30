import type { RunLanes } from '../ask/timeline';

/**
 * The strip above the chart: what the whole run *did*, in five numbers.
 *
 * `memory-and-replay` 58, ported from the design prototype's KPI row. Every
 * one of these is derived from the fold `50` and `57` already produce — **no
 * field was added to the wire for this strip**, which is the third ticket on
 * this map to find the data was already there and unread.
 *
 * Two deliberate departures from the prototype, and both are honesty rather
 * than taste:
 *
 * - **"Steps", not "Supersteps".** A superstep is LangGraph's own tick, and a
 *   fan-out costs several per lap; what this counts is bars, which is node
 *   completions. Printing one word over the other number would be a claim
 *   about the runtime made from data that cannot support it — and it is the
 *   same word `CLAUDE.md` already forbids on the step budget.
 * - **No token total, still — and now for a better reason.** The prototype's
 *   sixth KPI shipped with `memory-and-replay` 61, and it is in the dock's
 *   *header*, not here. Every number in this strip is derived from the fold;
 *   a token count is a number the **run reported**, and putting the two in one
 *   row would leave a reader unable to tell which of them the fold could be
 *   wrong about. It is also `tall`-gated where it sits, and an identity you
 *   check once has to be readable at every height. See `runCost`.
 */
export interface RunProfile {
  /** The run's own wall clock. `null` when it reported none — never `0`. */
  readonly totalMs: number | null;
  /** Bars, across every lane. */
  readonly steps: number;
  readonly modelCalls: number;
  readonly toolCalls: number;
  /**
   * Bars that are a second or later visit to their lane's node — the revise
   * laps, which is the number an evaluator-optimizer graph is built around.
   */
  readonly reviseLaps: number;
  /** Bars the run dated at both ends (`57`), as against spans between frames. */
  readonly measured: number;
  /** Lanes the run never closed (`50`) — a fact about the recording. */
  readonly openEnded: number;
}

export function runProfile({ lanes, totalMs }: RunLanes): RunProfile {
  const steps = lanes.flatMap((lane) => lane.steps);
  return {
    totalMs,
    steps: steps.length,
    modelCalls: steps.reduce((sum, step) => sum + step.modelCalls, 0),
    toolCalls: steps.reduce((sum, step) => sum + step.toolCalls, 0),
    reviseLaps: steps.filter((step) => step.visit > 1).length,
    measured: steps.filter((step) => step.measured).length,
    openEnded: lanes.filter((lane) => lane.openEnded).length,
  };
}
