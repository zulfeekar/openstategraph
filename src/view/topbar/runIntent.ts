/**
 * What pressing the toolbar's Run button means, right now.
 *
 * ## The finding this exists because of (ticket 21)
 *
 * Run on `concierge` did **nothing**: no panel, no toast, no error, nothing
 * in the console, across two clicks. The button stayed green and enabled to
 * look at.
 *
 * The cause was `disabled={!canRun}` with `canRun = question !== ''`, and
 * `concierge`'s Text Input is deliberately blank because its question arrives
 * at run time from the chat composer (ticket 22 is the same root cause seen
 * from the Diagnostics panel). The tooltip on the wrapping `<span>` already
 * said "Type a question in the Input node first" and never appeared either —
 * a `disabled` button dispatches no mouse events at all, so the click and the
 * hover both died in the same place. The one explanation that existed was
 * reachable only by someone who did not need it.
 *
 * The refusal was arguably *correct*; being inaudible is what made it a bug,
 * and the map's standard is explicit: **no gesture that silently does
 * nothing.** So the button stays live and every press produces one of exactly
 * three outcomes — none of them silence.
 *
 * ## Why this is a module and not three lines in `TopBar`
 *
 * There is no component-test harness in this repo (`vite.config.ts` collects
 * `src/**\/*.test.ts` only), so a rule living inside a React closure is a rule
 * with no test — which is how this one was quietly reintroduced-by-omission
 * in the first place. The decision is pure, so it moves out to where it can
 * be pinned; `TopBar` keeps the gesture and the toast, which is its job.
 */

/** The reason Run gives when there is nothing for it to send. */
export const NO_ENTRY_QUESTION =
  'Nothing to run yet — this workflow takes its question at run time. ' +
  'Type one into the Text Input node to run it from here, or ask it in Chat.';

/** The three things a press of Run can mean. Never "nothing". */
export type RunIntent =
  | { readonly kind: 'stop' }
  | { readonly kind: 'run'; readonly question: string }
  | { readonly kind: 'explain'; readonly reason: string };

/**
 * @param question what `entryQuestion` says Run would send (`''` for none)
 * @param runInFlight whether a run is already streaming
 */
export function runIntent(question: string, runInFlight: boolean): RunIntent {
  // Checked first, and unconditionally: while a run streams, the button is a
  // Stop, and a Stop must work regardless of what the Input node now says.
  if (runInFlight) return { kind: 'stop' };
  const trimmed = question.trim();
  if (trimmed === '') return { kind: 'explain', reason: NO_ENTRY_QUESTION };
  return { kind: 'run', question: trimmed };
}
