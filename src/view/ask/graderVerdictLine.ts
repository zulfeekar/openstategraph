/**
 * What the approval card may say about the grader that produced the candidate.
 *
 * `workflow-gallery` 32. Grade-then-gate — the machine checks it, then a
 * person decides — is the natural shape for anything a person signs off, and
 * the reviewer was shown the draft with the one existing machine opinion of it
 * left in state. The interrupt frame now carries `verdict` and `reason`; this
 * turns them into the sentence beside the draft.
 *
 * Three rules, and each is a claim this must not overstate:
 *
 * - **No verdict, no sentence.** The two fields arrive together or not at all,
 *   and their absence says *no grader produced this candidate* — not *the
 *   grader had nothing to say*. Inventing a neutral line for that case would
 *   tell the reviewer a machine looked at it.
 * - **The verdict is reported, the reason is quoted.** `verdict` is one of two
 *   known labels; anything else is a value this build does not understand, and
 *   the honest move is to print the reason without captioning it with a word
 *   whose meaning we are guessing at.
 * - **A verdict with no reason is still worth saying.** An ordinary pass
 *   carries a generic reason and a deterministic rejection carries a specific
 *   one; either way the label alone already changes what a reviewer looks for.
 */
export function graderVerdictLine(approval: {
  readonly verdict: string;
  readonly reason: string;
}): string {
  const verdict = approval.verdict.trim();
  if (!verdict) return '';
  const reason = approval.reason.trim();

  if (verdict === 'pass') {
    return reason ? `The grader passed this — ${reason}` : 'The grader passed this.';
  }
  if (verdict === 'revise') {
    return reason
      ? `The grader asked for a revision — ${reason}`
      : 'The grader asked for a revision.';
  }
  return reason;
}
