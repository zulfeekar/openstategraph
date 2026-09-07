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
 * 1. **A repeated line is kept, and that is a reversal.** Until
 *    `launch-readiness/145` this function collapsed a line repeated back to
 *    back, and the reason it gave was one sentence: `"Thinking about the next
 *    step."` fired from `before_model` on every lap of a tool loop, so a
 *    four-tool answer stacked it four times with nothing between.
 *
 *    `145` stopped authoring that line — `before_model` knows nothing, and a
 *    sentence that is identical every step is half the panel — so the rule
 *    outlived its only reason. What it still did was the harm: two *genuinely*
 *    repeated tool calls rendered as one. An agent that reads the same file
 *    six times running is `launch-readiness/146`, and collapsing that storm
 *    into a single line erases the evidence exactly where it matters. A panel
 *    exists to say what happened, and "it happened twice" is part of what
 *    happened.
 *
 *    The de-duplicating cure is also the one `145` explicitly rules out: it
 *    hides a line nobody should be authoring rather than not authoring it. If
 *    a repeat ever reads as noise again, the fix is upstream — stop emitting
 *    the line, or give it a finding that differs (`143`, `144`) — never here.
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
 * `existing` plus `text`, or `existing` unchanged when the frame said nothing.
 *
 * Returning the **same array reference** when nothing changed is load-bearing
 * rather than an optimisation: the caller writes this straight into the model,
 * and a fresh array for a frame carrying no line would re-render every card
 * for nothing.
 */
export function pushNarration(
  existing: readonly string[],
  text: string,
  limit: number = NARRATION_STACK_LIMIT,
): readonly string[] {
  const line = text.trim();
  if (!line) return existing;
  const next = [...existing, line];
  return next.length > limit ? next.slice(next.length - limit) : next;
}
