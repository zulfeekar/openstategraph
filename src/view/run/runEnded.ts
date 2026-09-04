import type { RunView } from './runView';

/**
 * What a run's ending is worth to the shell.
 *
 * `totalTokens` is `null` when the run reported no usage at all — a failure
 * that never reached a model, or one whose terminal frame carried nothing.
 * `null` is the run's own word for *it did not say*, the same reading
 * `RunView.usage` documents, and it is passed on rather than replaced with a
 * zero the run never claimed.
 */
export interface RunEnded {
  readonly totalTokens: number | null;
  /** The toast, or `null` when there is no number honest enough to put in one. */
  readonly toast: string | null;
}

/**
 * Whether a run just ended, from the two snapshots either side of a publish.
 *
 * `stable-beta-public/14`. The shell had one source for this and it was the
 * wrong one: `workbench.engine`'s `run:finish`, which belongs to the canvas's
 * own sequential preview walk. Nothing in the shipped app calls
 * `engine.run()` any more — the toolbar's Run opens the chat and streams a
 * backend run — so the toast and the token bar's refresh were hung off an
 * event that could not fire, and the bar caught up only on window focus.
 *
 * The snapshot the run dock and the first-run starter already read is the one
 * source that does move, so this is where "a run ended" is decided now. It
 * takes *two* snapshots because an ending is a transition and not a state: a
 * finished run stays finished, and a predicate over one snapshot would fire
 * again on every republish — a second toast for a run that ended once.
 *
 * Three things are deliberately not endings:
 *
 * - **A stored run on either side.** Opening a recording swaps the surface to
 *   one that was never running here; coming back from it puts a live run up
 *   that ended, if it ended, while the recording was held. Neither is a run
 *   ending now, and toasting either would tell a reader something happened
 *   because they clicked a list.
 * - **Nothing before.** A fresh tab's first publish has no previous running
 *   snapshot, so it cannot have stopped running.
 * - **A run still streaming.**
 *
 * A *failed* run is an ending, and that is the half the old handler got right
 * for the right reason: a run that failed still spent whatever it spent before
 * it failed, and the *This tab* cell is only honest if it moves either way.
 * What it cannot do is name a number, so it names none.
 *
 * Pure and framework-free, tested away from React for the reason
 * `useSpend.test.ts` gives: this project's runner has no DOM, so a hook's
 * decision is proven as a function and its wiring is proven in the browser.
 */
export function runEnded(before: RunView | null, after: RunView): RunEnded | null {
  if (before === null) return null;
  if (before.source !== 'live' || after.source !== 'live') return null;
  if (!before.running || after.running) return null;
  const usage = after.usage;
  if (usage === null || usage.length === 0) return { totalTokens: null, toast: null };
  const totalTokens = usage.reduce((sum, row) => sum + row.totalTokens, 0);
  return { totalTokens, toast: `Run finished · ${totalTokens.toLocaleString()} tokens` };
}
