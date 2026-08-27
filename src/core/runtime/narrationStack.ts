/**
 * What a card has said about itself so far, as a `progress` frame lands.
 *
 * `launch-readiness/140`. A pure function rather than three lines inside
 * `AskPanel`'s event handler, for the same reason `liveLine.ts` and
 * `progressLine.ts` are: what goes wrong on this surface is invisible from
 * the panel. `launch-readiness/105` shipped a narration line that erased
 * itself one frame later with both suites green, and the fix (`110`) was a
 * rule nobody could see because it was inlined.
 *
 * Three rules, and each one is a real frame sequence rather than a
 * precaution:
 *
 * 1. **Consecutive repeats collapse.** `"Thinking about the next step."`
 *    fires from `before_model` on every lap of a tool loop, so a four-tool
 *    answer stacks it four times with nothing between. A panel that reads
 *    *Thinking… Thinking… Thinking…* looks like progress and carries none —
 *    which the ticket says is worse than no panel. A repeat that is *not*
 *    consecutive is kept: coming back to the same work after doing something
 *    else is a different fact from never having left it.
 * 2. **The stack is capped.** A long run can emit hundreds of lines, and an
 *    unbounded array on a canvas card is a memory leak with a scrollbar. The
 *    cap keeps the most recent, because the newest line is the one a reader
 *    is watching for.
 * 3. **Blank frames are dropped.** A `progress` frame with an empty message
 *    is a frame that said nothing, and an empty row in the stack reads as a
 *    line that failed to render.
 */

/**
 * How many lines one card keeps. Generous enough that the whole account of an
 * ordinary run survives to be scrolled back through, bounded enough that a
 * runaway loop cannot grow a card's state without limit. The 420 px ceiling
 * the ticket sets is a *visual* one and is enforced by the panel that renders
 * this, not here — `core/` owes nothing to a pixel.
 */
export const NARRATION_STACK_LIMIT = 200;

/**
 * `existing` plus `text`, or `existing` unchanged when the line adds nothing.
 *
 * Returning the **same array reference** when nothing changed is load-bearing
 * rather than an optimisation: the caller writes this straight into the model,
 * and a fresh array every frame would re-render every card on every repeated
 * line.
 */
export function pushNarration(
  existing: readonly string[],
  text: string,
  limit: number = NARRATION_STACK_LIMIT,
): readonly string[] {
  const line = text.trim();
  if (!line) return existing;
  if (existing[existing.length - 1] === line) return existing;
  const next = [...existing, line];
  return next.length > limit ? next.slice(next.length - limit) : next;
}
