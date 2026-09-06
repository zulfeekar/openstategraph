import type { RunUsage } from '@core/runtime/RuntimeClient';

/**
 * What the run cost, said only as far as the run said it.
 *
 * `memory-and-replay` 61 — the prototype's sixth KPI, which `58` shipped
 * without and named the reason for: *"a token count is the number a reader is
 * most likely to quote, so an estimate would be the worst possible field to
 * guess."* Nothing is estimated here and nothing is derived from the fold;
 * this reads `usage`, which has ridden the terminal frames since `56`.
 *
 * **A mirroring job, not a new capability.** `RunUsage` has been parsed by
 * `RuntimeClient` and carried on `RunResult` and the `done` frame since 56,
 * and reached no surface at all — the drift census's own rule from `14` is
 * that a mirrored field must be read by a named surface, and until this module
 * `usage` was the field with no reader.
 *
 * # Three answers, and they are three
 *
 * | `usage` | shows | because |
 * | --- | --- | --- |
 * | a list | the sum | the run said what it spent |
 * | `[]` | **`0`** | no model was called — a measurement, and a real one |
 * | `null` | **`—`** | this reader was not told (56). Not zero |
 *
 * The `—`/`0` split is `launch-readiness` 108's rule applied to tokens rather
 * than to a duration: *nobody counted this* and *this counted nothing* are two
 * facts, and one glyph for both is the defect that rule exists to stop.
 *
 * # And a live run has no partial
 *
 * 61 asked what a running total looks like beside a final one, warning that
 * *"a strip that switches silently between them is the shape this map keeps
 * closing."* It does not have to: usage rides the **terminal** frames, so a
 * run in flight has reported no total rather than an incomplete one, and the
 * honest control is a dash with a sentence saying when the number arrives.
 * A `usage` in hand while `running` is a previous turn's, and is refused.
 */
export interface RunCost {
  /** The number, grouped for reading — or `—`. Never a guess. */
  readonly total: string;
  /** What the number is, or why there is not one. Always present. */
  readonly caption: string;
}

export function runCost({
  usage,
  running,
}: {
  readonly usage: readonly RunUsage[] | null;
  readonly running: boolean;
}): RunCost {
  if (running) {
    return {
      total: '—',
      caption: 'Tokens are reported when it finishes — a run in flight has not counted them yet.',
    };
  }
  if (usage === null) {
    return { total: '—', caption: 'This run did not report what it spent.' };
  }
  if (usage.length === 0) {
    return { total: '0', caption: 'No model was called.' };
  }
  const total = usage.reduce((sum, row) => sum + row.totalTokens, 0);
  const caption =
    usage.length === 1
      ? `Input and output, on ${usage[0]?.model}.`
      : `Input and output, across ${usage.length} models.`;
  return { total: total.toLocaleString('en-US'), caption };
}
