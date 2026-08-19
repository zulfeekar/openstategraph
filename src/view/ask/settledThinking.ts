/**
 * Whether a finished turn should still show its streamed-token block.
 *
 * `thinking` is a flat concatenation of *every* token frame in a run
 * (`AskPanel` appends `event.content` unconditionally), so the last node to
 * stream is whatever produced the answer — which means a settled `thinking`
 * **ends with the answer by construction**. Rendering both printed the whole
 * answer twice, back to back, on every workflow whose answer streams
 * (`every-workflow-green` 10; observed on `concierge` through a mount and on
 * `workflow-2026` directly).
 *
 * The rule is about what the block is *for* rather than about what it contains:
 * while tokens arrive it is the only sign anything is happening, and that is
 * the whole of its job. Once the turn has settled and an answer exists, the
 * answer is the better rendering of the same text and the trace holds the
 * per-node detail this block flattens away.
 *
 * Deliberately **not** a comparison between the two strings. The answer here
 * was the thinking plus a routing footer — near-identical, not equal — so any
 * equality or prefix test would have passed it through, and would silently
 * stop working the day an output node reformats. A rule that depends on the
 * text is a rule that fails without telling anyone.
 *
 * A pending human decision counts the same way, and is the worse case of the
 * two: `support-triage` paused at its gate rendered the draft reply as settled
 * thinking *and* inside the approval card, word for word. The card is a
 * decision surface — a reviewer who sees the same paragraph twice cannot tell
 * whether the copy above is a second draft they are also accountable for.
 *
 * This is the interim. The full fix is to attribute tokens to the node that
 * produced them and fold them into the trace, which removes the flat block
 * rather than choosing when to hide it; a token frame already knows its node.
 */
export function showsThinking(turn: {
  readonly thinking: string;
  readonly running: boolean;
  readonly answer: string;
  /** A human gate is holding this turn, and its card is showing the draft. */
  readonly awaitingApproval: boolean;
}): boolean {
  if (!turn.thinking) return false;
  if (turn.running) return true;
  if (turn.awaitingApproval) return false;
  // Settled with nothing presented anywhere: the tokens are all the user has,
  // and hiding them would leave a turn that shows no model output at all.
  return !turn.answer.trim();
}
