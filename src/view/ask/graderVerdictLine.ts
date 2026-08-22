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
 * - **A verdict with no reason is still worth saying.** The label alone
 *   already changes what a reviewer looks for. (Until `workflow-gallery` 53
 *   this said an ordinary pass "carries a generic reason": it carried the
 *   literal `Grader passed it`, so this card's most-read line was *"The grader
 *   passed this — Grader passed it"*. A pass now carries whatever the model
 *   wrote after the keyword, already condensed to one line and bounded to 200
 *   characters by `BaseGrader`, or the words `No reason given` when it wrote
 *   nothing — so the length and the newline are handled before the string
 *   reaches here, and nothing on this side needs to truncate.)
 */
export interface GraderApproval {
  readonly verdict: string;
  readonly reason: string;
  readonly check?: string;
}

// Everything between these markers is copied verbatim into
// `backend/openstategraph/api/static/chat.html` by
// `scripts/render_grader_verdict_line.py`, with this one signature line
// rewritten to its untyped JavaScript equivalent. So the body below must be
// valid JavaScript as written: no type annotations, no `as`, no generics, and
// nothing imported. That constraint is the price of one sentence having one
// spelling, and it is cheap — the rules here are string handling.
// GENERATED-SOURCE-BEGIN graderVerdictLine
export function graderVerdictLine(approval: GraderApproval): string {
  const verdict = approval.verdict.trim();
  if (!verdict) return '';
  const reason = approval.reason.trim();
  // The fourth rule, added by `production-ready` 92: a reviewer told the
  // grader asked for a revision deserves to know whether a *model* formed
  // that opinion, or whether a rule rejected the text without asking one.
  // Same fact and same wording as the trace row — `graderCheckLine` — so the
  // two doors onto one judgement cannot say different things.
  const skipped = (approval.check ?? '').trim() ? ' without a model call' : '';

  if (verdict === 'pass') {
    return reason ? `The grader passed this — ${reason}` : 'The grader passed this.';
  }
  if (verdict === 'revise') {
    return reason
      ? `The grader asked for a revision${skipped} — ${reason}`
      : `The grader asked for a revision${skipped}.`;
  }
  return reason;
}
// GENERATED-SOURCE-END graderVerdictLine
