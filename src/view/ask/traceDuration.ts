/**
 * How a trace row prints the time it measured (ticket 84).
 *
 * A row's duration is a wall-clock gap between two stream frames, rounded to
 * whole milliseconds. That rounding has one output a reader cannot tell from a
 * broken row: `0 ms`.
 *
 * The case that produced ticket 84 is not hypothetical and not a lost gap. A
 * grader rejects *deterministically* when the candidate is empty or begins
 * `Error` — `BaseGrader.deterministic_checks`, before any model is invoked —
 * and that takes about 0.02 ms. So on the run that was reported, every
 * `grader-sql` row genuinely measured under half a millisecond, three times
 * running, because the agent above it had produced nothing each time and the
 * grader never called a model at all. The frames were on the wire in order,
 * with honest gaps; the trace tree charged them correctly; the number printed
 * was the truth. It simply read as a bug, and was filed as one.
 *
 * `<1 ms` says the thing `0 ms` cannot: *this was measured, and it is smaller
 * than this clock can show*. A step that took no measurable time is a fact
 * about the step — a grader that skipped its model call, a `tools` frame that
 * only bookkept — and the reader should be able to see that without deciding
 * whether the timer is broken.
 *
 * Never applied to a value that was never measured: a spawn row carries a
 * hardcoded zero because it is an announcement rather than a step, and it
 * renders no duration at all rather than a formatted one.
 */
export function formatDuration(durationMs: number): string {
  if (!Number.isFinite(durationMs) || durationMs < 0) return '—';
  if (durationMs < 1) return '<1 ms';
  return `${durationMs} ms`;
}
