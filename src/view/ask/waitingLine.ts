/**
 * What the panel says while the stream is honestly quiet.
 *
 * `launch-readiness/141`. The owner watched a real run and reported *"I don't
 * see anything for a few seconds"* against a measurement (`109`) that put the
 * first frame at 0.09 s. Both were true, and neither was the whole picture:
 *
 * - The wire, timestamped at the server on a 28-node package: `in1` at
 *   **0.06 s**,
 *   `router1` at **2.16 s**, `prefetch1` and the first narration frame at
 *   **4.99 s**, the first model token at **13.13 s**.
 * - The browser, timestamped at receipt and at the DOM mutation carrying it:
 *   frame one received at **15.9 ms**, on screen at **62.9 ms**.
 *
 * So the paint is prompt and the wire is quiet — the 0.09 s in `109` was the
 * `in1` update, which carries the reader's *own question* back and is
 * therefore not readable output at all. The seconds are real and they belong
 * to the workflow: three nodes run before anything with a voice does, and
 * narration covers the agent family only (`105`, still `partially`).
 *
 * A quiet wire is not a licence to show nothing. It is a licence to say what
 * is being waited **for** — which is the one thing that is honestly known.
 *
 * ## The two sentences, and why there are only two
 *
 * Nothing on the stream says what the *next* step will be. An `update` frame
 * fires when a node **completes** (LangGraph's `updates` mode), and its
 * `activeNode` is that same completed node — so after `router1` lands, the
 * identity of whatever is now in charge is genuinely unknown until it
 * narrates itself. A line naming a step would therefore be an invention, and
 * this surface has shipped two defects this month that were exactly that
 * shape.
 *
 * What *is* known is whether anything has come back at all. That is the only
 * distinction drawn here, and it is the distinction a reader actually wants:
 * "did my question reach it" is a different worry from "is it stuck".
 */

/** Nothing has come back yet — the question is in flight. */
export const WAITING_TO_START = 'Sent your question — waiting for the workflow to start.';

/**
 * Steps have finished and none of them has said a word about itself.
 *
 * Note the tense: it claims a wait, never work. The run *is* between frames,
 * so something is in flight; but which something, and what it is doing, is
 * not on the wire.
 */
export const WAITING_FOR_THE_NEXT_STEP =
  'Working — waiting for the next step to say what it is doing.';

export interface WaitingContext {
  /** Whether this turn's run is still open. */
  readonly running: boolean;
  /**
   * Whether a real narration line is on screen — **or has been, this turn**.
   *
   * Both halves are load-bearing, for two different failures. The placeholder
   * must never sit beside a real line: `launch-readiness/110` was a real line
   * erased by machinery one frame later, and a placeholder that outlives the
   * line it stood in for is the same defect wearing the other hat. And it
   * must not come back in the gaps *between* real lines — narration is
   * cleared by its own step completing (`liveLineAfterStep`), so a wait that
   * only asked "is a line on screen right now" looked fresh again every few
   * seconds. Measured live on `/chat`: the placeholder appeared and vanished
   * inside a millisecond three times between 7.9 s and 12.3 s of one run.
   *
   * So this line belongs to the **opening** silence: the one before the
   * surface has any voice at all.
   */
  readonly saidSomething: boolean;
  /** Whether model tokens are arriving — the answer typing itself out. */
  readonly streaming: boolean;
  /** Whether a human gate is holding the turn; the wait is then the reader's. */
  readonly awaitingApproval: boolean;
  /** How many steps have reported completion so far this turn. */
  readonly stepsSoFar: number;
}

/** The line to show, or `null` when the surface already has a better one. */
export function waitingLine(context: WaitingContext): string | null {
  if (!context.running) return null;
  if (context.awaitingApproval) return null;
  if (context.saidSomething) return null;
  if (context.streaming) return null;
  return context.stepsSoFar === 0 ? WAITING_TO_START : WAITING_FOR_THE_NEXT_STEP;
}
