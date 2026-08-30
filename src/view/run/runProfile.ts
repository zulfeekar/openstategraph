import type { RunLanes, TimelineStep } from '../ask/timeline';

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
  /**
   * Model calls, counted as the bars the chart draws for them.
   *
   * Derived from `TimelineStep.events` rather than from the counters beside
   * them, so the strip and the chart cannot come to disagree about a number a
   * reader is invited to check by counting (`memory-and-replay` 66).
   */
  readonly modelCalls: number;
  /**
   * Tool **calls** — not the laps its loop took.
   *
   * Until `66` this summed `TimelineStep.toolCalls`, which counts internal
   * frames named `tools`: the loop's tool *step*, which runs once per lap and
   * executes every call the model asked for in that lap. A lap asking for
   * three tools counted one. The two agreed on the recorded run only because
   * every lap there made exactly one call, which is why nobody saw it.
   *
   * `invoked` is the count of calls and has been on the wire since `55`. Now
   * that the chart draws one bar per call, the strip has to say the same
   * number or a reader cannot tell which of the two lied.
   *
   * **`null` is a third answer and it is the important one**: this run's loop
   * took tool laps and the recording does not say how many calls they made.
   * That is every run captured before `55`, and every stream whose tool names
   * the audience boundary withheld. Printing `0` there would say no tool ran,
   * which is false; printing the lap count would put laps and calls under one
   * label, which is the confusion this field exists to end. The dash is
   * `launch-readiness` 108's rule — a number the recording does not carry is
   * not a zero — and it is the one value that keeps the promise the rest of
   * this field makes: whenever a number is printed, that many bars can be
   * counted on the chart.
   */
  readonly toolCalls: number | null;
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
  const events = steps.flatMap((step) => step.events);
  return {
    totalMs,
    steps: steps.length,
    modelCalls: events.filter((each) => each.kind === 'model').length,
    toolCalls: toolCalls(steps, events),
    reviseLaps: steps.filter((step) => step.visit > 1).length,
    measured: steps.filter((step) => step.measured).length,
    openEnded: lanes.filter((lane) => lane.openEnded).length,
  };
}

/** See `RunProfile.toolCalls` — three answers, and the third is `null`. */
function toolCalls(steps: readonly TimelineStep[], events: readonly TimelineStep[]): number | null {
  const calls = events.filter((each) => each.kind === 'tool').length;
  if (calls > 0) return calls;
  // Laps its loop took, which is what `TimelineStep.toolCalls` counts. Read
  // here only to tell "no tool ran" from "the recording does not say".
  return steps.some((step) => step.toolCalls > 0) ? null : 0;
}
