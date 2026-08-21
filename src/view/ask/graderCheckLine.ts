/**
 * What a grader row says about *how* the grader reached its verdict.
 *
 * `production-ready` 92. `BaseGrader.grade` has two paths that a trace
 * rendered identically. `deterministic_checks` rejects an empty candidate, or
 * one beginning `Error`/`Traceback`/`Exception`, and returns **before** any
 * model is invoked — 0.021 ms, against 719-2024 ms for a judged verdict on a
 * live run. Ticket 84 exists because of exactly that: three grader rows that
 * returned instantly had one available reading, "the timer is broken", and it
 * cost a session plus a live model run to establish that the timer was right
 * and no model had ever been called. 84 settled how the *duration* prints;
 * this is what the row says *happened*.
 *
 * Three rules, each a claim this must not overstate:
 *
 * - **Silence is the default.** The two fields arrive together or not at all,
 *   and their absence means no deterministic check fired — which covers an
 *   ordinary pass *and* a model's own rejection. Saying anything there would
 *   tell a reader no model ran when one did.
 * - **The check is a fact; the reason is the sentence.** `check` is an
 *   internal marker from an open set — `BaseGrader.deterministic_checks`
 *   names `empty` and `error`, and any subclass overriding
 *   `deterministic_checks` may add its own — so it is never captioned or
 *   looked up. It is only the evidence that no model was asked.
 *   (Until 2026-08-21 this said "`Grader` adds `no_figure`". `Grader`
 *   overrides only `revise_payload`; `no_figure` was never a built-in check —
 *   it names a stricter grader defined inside `backend/tests/test_grader.py`,
 *   a test fixture.)
 * - **A missing reason is not a missing finding.** The skipped model call is
 *   the part of this a reader acts on, and it is true with or without prose
 *   attached.
 *
 * "model call" is deliberate wording: it names `self.model.invoke`, which is
 * the thing that did not happen, and collides with none of the user-facing
 * vocabulary `CLAUDE.md` fixes (revision loop, step budget, workflow node,
 * template, package, instance, slug, eval).
 */
export function graderCheckLine(row: {
  readonly check?: string;
  readonly reason?: string;
}): string {
  if (!(row.check ?? '').trim()) return '';
  const reason = (row.reason ?? '').trim();
  return reason ? `rejected without a model call — ${reason}` : 'rejected without a model call';
}
