/**
 * What a reply says about itself while a grader has still to judge it.
 *
 * `every-workflow-green/45`. A grader-checked run puts its first attempt on
 * screen the moment the model types it, complete and confident, and the run
 * that produced the ticket answered a money question with **$96,699.19** — the
 * database holds `$2,328.60` in total, and the settled answer thirteen seconds
 * later was `$826.65`. Two careful readers reported figures from that state as
 * results on the same day. The text was never the problem; the absence of any
 * mark on it was.
 *
 * The owner chose the middle of three options: **show the draft, mark it
 * plainly, replace it.** Showing nothing until the grader passes leaves a
 * reader watching a blank panel for the length of a lap, and a separate
 * "thinking" area is more machinery than this needs.
 *
 * ## The words
 *
 * Six of them, and each half is doing a job:
 *
 * - **"Draft"** is the noun a reader already has for *text somebody will
 *   revise*. It needs no training and it is not our vocabulary — unlike
 *   `attempt`, which is a state field, and `candidate`, which is the grader's
 *   word for it.
 * - **"not checked yet"** says the thing that is actually true: a check is
 *   coming. Not *"may be wrong"*, which is true of the settled answer too and
 *   would teach a reader to discount both.
 *
 * **It names no actor**, and that is deliberate rather than vague. `/chat`
 * says *our reviewer* to a customer and the editor says *the grader* to the
 * person who wired one; a sentence naming either would have to be written
 * twice, and this repository's own record on one fact spelled two ways is
 * `graderVerdictLine.parity.test.ts`. One sentence, both surfaces, pinned by
 * `draftNotice.parity.test.ts`.
 *
 * It also cannot be read as contradicting the banner `/chat` already shows
 * when the grader **exhausts** its attempts and a rejected answer is published
 * anyway (`launch-readiness/25`). That one speaks about a settled answer and
 * says a review happened; this one speaks about text still in flight and says
 * one has not.
 */
export const DRAFT_NOTICE = 'Draft — not checked yet';

/**
 * The mark's whole lifetime, as a rule rather than as a condition inlined at
 * two call sites.
 *
 * A draft is on screen exactly while there is draft text and the reply it
 * belongs to has not been replaced by a settled one. Deliberately the same
 * shape as `showsThinking`, whose docstring argues the case for the streamed
 * block generally; the difference here is only *which* buffer it is asked
 * about.
 *
 * The no-flicker property is not in this function and cannot be: it is the
 * emptiness of `draft`. A workflow with no grader downstream of the node that
 * answered produces no marked frame at all, so the buffer stays empty, so
 * nothing appears and nothing vanishes. That is why the backend emits the flag
 * true-only and why absence must never be read as "checked".
 */
export function showsDraft(turn: {
  readonly draft: string;
  readonly running: boolean;
  readonly answer: string;
  readonly awaitingApproval: boolean;
}): boolean {
  if (!turn.draft) return false;
  if (turn.running) return true;
  if (turn.awaitingApproval) return false;
  return !turn.answer.trim();
}
