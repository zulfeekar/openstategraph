import { type Result } from '@core/kernel/Result';
import { type WorkflowSummary } from '@core/runtime/WorkflowFileClient';

/**
 * What one poll of the open workflow's file means — the decision and the two
 * pieces of state it is made from, with no timer, no network and no React.
 *
 * The machinery that acts on it is `useWorkflowFileWatch.ts`. They were one
 * module until launch-readiness 147 gave the deleted verdict a consequence:
 * acting on it means disarming disk autosave, and `diskAutosave` reads the
 * open-slug key and the `savedAt` map below, so the hook had to move rather
 * than close a cycle.
 */

/**
 * The slug of whichever saved workflow this tab currently has open —
 * `sessionStorage`, not the model, so a rename changes the display name
 * only, never the directory (ticket 14's identity decision).
 */
export const CURRENT_SLUG_KEY = 'openstategraph-current-workflow-slug';

/**
 * The `savedAt` this tab itself last wrote or read for a slug — a plain
 * module-level map, not persisted, because a full page reload re-restores
 * everything through `useWorkflowSession` and the watch re-baselines on its
 * first poll with no false positive either way.
 */
const knownSavedAt = new Map<string, string>();

export function recordKnownSavedAt(slug: string, savedAt: string | undefined): void {
  if (savedAt) knownSavedAt.set(slug, savedAt);
}

export function forgetKnownSavedAt(slug: string): void {
  knownSavedAt.delete(slug);
}

/** What this tab believes the file's `savedAt` is — read by the hook and by tests. */
export function getKnownSavedAt(slug: string): string | undefined {
  return knownSavedAt.get(slug);
}

/**
 * The **version** of a package this tab is editing — `osg-agent-experience/45`.
 *
 * Beside `knownSavedAt` and deliberately not merged into it, because the two
 * are read by different questions. `savedAt` answers *did the file move*, and
 * the watch's own poll is allowed to adopt a new value: noticing a change is
 * its entire job. This answers *which bytes is this tab's document derived
 * from*, and a poll must **never** adopt it — if it did, an agent's write
 * would become this tab's base within seconds and the very next autosave
 * would quote the agent's version back at the backend and overwrite it. The
 * guard would then be at its quietest exactly when it was needed.
 *
 * So this map is written by three events and no others: a load, a save that
 * landed (which answers with the file's new digest), and a refused save
 * (which answers with the digest the file actually has, so *keep mine* is a
 * save the user can make rather than a switch they have to find).
 */
const knownDigest = new Map<string, string>();

/**
 * Adopt the version a *row the backend just handed us* describes.
 *
 * Takes the row rather than two strings so the one moment a client learns
 * both facts about a file writes both of them. Four call sites recorded
 * `savedAt` and would each have had to remember the digest separately, which
 * is the same knowledge in four places — and the one that forgot would
 * silently be the one that saves unguarded.
 *
 * A `null` row (a 404, or a summary call that did not answer) records
 * **nothing**: "I cannot tell you" is not a version, and writing an empty
 * digest would make the next save claim to be editing a file that never
 * existed.
 */
export function recordKnownVersion(
  slug: string,
  row: Pick<WorkflowSummary, 'savedAt' | 'digest'> | null | undefined,
): void {
  recordKnownSavedAt(slug, row?.savedAt);
  if (row?.digest) knownDigest.set(slug, row.digest);
}

/** Adopt a digest handed back by a save — the one this tab just caused. */
export function recordKnownDigest(slug: string, digest: string | undefined): void {
  if (digest) knownDigest.set(slug, digest);
}

/** What this tab believes it is editing, or `undefined` when it has no idea. */
export function getKnownDigest(slug: string): string | undefined {
  return knownDigest.get(slug);
}

/** Drop a slug's version — for tests, and for a package that was deleted. */
export function forgetKnownDigest(slug: string): void {
  knownDigest.delete(slug);
}

export type FileWatchAction =
  | { readonly kind: 'none' }
  | { readonly kind: 'baseline'; readonly savedAt: string }
  | { readonly kind: 'notify-deleted' }
  | { readonly kind: 'notify-changed' }
  | { readonly kind: 'notify-blind' }
  | { readonly kind: 'notify-back-in-touch' };

/**
 * The pure decision behind one poll: given what the backend currently
 * reports for the open slug and what this tab last knew, what should happen.
 * Kept apart from the hook so it is testable without a timer, a
 * network stub, or React — the same reasoning `ExecutionEngine`'s
 * `rejectBeforeStart` split applies to its own side effect.
 *
 * **`entry` is the answer to an existence question, not a visibility one**
 * (ticket 21). It used to be `entries.find(...)` over
 * `GET /api/workflows?surface=editor`, which is a *surface* — and a surface
 * omits things that exist, so drilling into `concierge` or
 * `workflow-architect` made this function announce a deletion over a file the
 * backend was happily serving 200. It now takes what
 * `WorkflowFileClient.summary(slug)` returned, where `null` means a 404 and
 * nothing else does — so a genuinely deleted workflow still warns, and only
 * that.
 *
 * (Until 2026-08-16 the sentence above gave the reason as "it omits hidden
 * packages by design". That was true when ticket 21 was written and is not
 * true now: launch-readiness ticket 04 made `surface=editor` return hidden
 * packages carrying the flag, and only `surface=chat` omits them. The seam is
 * unchanged and still load-bearing — that listing still drops *unreadable*
 * packages, and absence from a surface is still not absence from disk — but
 * the example had outlived the behaviour it cited.)
 */
export function decideFileWatchAction(
  entry: WorkflowSummary | null,
  known: string | undefined,
): FileWatchAction {
  if (!entry) return { kind: 'notify-deleted' };
  // A package caught mid-write, or otherwise unreadable, reports an empty
  // `savedAt`. That is "I cannot tell you when", which is neither a deletion
  // nor a change — wait for the next poll rather than raise an alarm about a
  // file that is being saved right now.
  if (!entry.savedAt) return { kind: 'none' };
  if (known === undefined) return { kind: 'baseline', savedAt: entry.savedAt };
  if (entry.savedAt !== known) return { kind: 'notify-changed' };
  return { kind: 'none' };
}

/* -------------------------------------------------------------------------
 * Whether the watch can see at all — `say-it-on-the-surface/07`
 * ---------------------------------------------------------------------- */

/**
 * How far the watch is from the backend right now.
 *
 * `decideFileWatchAction` above answers *what the file says*. This answers the
 * question underneath it — *did anything answer* — and it exists because the
 * hook used to act only `if (outcome.ok)` with no `else`, so a poll that could
 * not reach the backend was indistinguishable from one that reached it and
 * found nothing wrong. **A watch that goes quiet when it cannot see is a watch
 * that reports "fine" when it means "blind."**
 *
 * Staged live on 2026-08-28 by shimming `fetch` to reject the summary call:
 * nine consecutive failed polls over ~45 s, zero DOM mutations, no toast, Save
 * and Publish both live and Save's tooltip still promising to overwrite a
 * folder nothing had been able to see.
 */
export interface WatchReach {
  /** Failed polls since the last one that answered. Reset by any success. */
  readonly consecutiveFailures: number;
  /** Whether the failures have gone on long enough to be worth saying. */
  readonly blind: boolean;
}

/** The starting reach: silence before the first poll is not an outage. */
export const IN_TOUCH: WatchReach = { consecutiveFailures: 0, blind: false };

/**
 * Consecutive failed polls before the watch says it cannot see.
 *
 * **Argued, not picked.** Polls are five seconds apart, so three consecutive
 * failures is a continuous window of at least ten seconds across three
 * independent attempts, and at least fifteen since the last answer.
 *
 * - **Why not one.** A single dropped request is not an outage, and this
 *   repository's own development loop manufactures them: editing anything
 *   under `backend/` or `workflows/` reloads uvicorn, which is a one-to-two
 *   second gap that lands inside a single poll. A banner on every reload is
 *   the panel that cries wolf, which this project has now hit four times, and
 *   the cost of that is a reader who ignores the true one.
 * - **Why not more.** The audit staged nine failures over forty-five seconds
 *   and saw nothing at all. Three names a genuine outage within fifteen
 *   seconds rather than never, which is the same order as the five seconds
 *   the deleted verdict already takes.
 * - **Why consecutive rather than a rate.** One successful poll resets the
 *   count, so a flapping link that lands even one answer in three never
 *   accumulates — and it should not, because a watch that answered ten
 *   seconds ago is not blind.
 *
 * The threshold can afford to wait for evidence because blindness is a
 * *knowledge* defect and no longer a destructive one: `launch-readiness/147`
 * disarmed the writer and made every editor save `must_exist`, so a save into
 * a package that vanished during the blind window fails with a 404 rather than
 * resurrecting it hollow.
 */
export const BLIND_AFTER_FAILED_POLLS = 3;

/**
 * One whole poll: what it did to the reach, and the single thing to say.
 *
 * Pure, so the sequence a live outage produces can be *run* — nine failures,
 * a flapping link, a deletion that lands while the watch is blind — none of
 * which a timer-and-network hook can be asked about. A suite that only
 * exercises successful polls stays green against exactly the defect this
 * function exists for.
 *
 * On a success that ends a blind spell the underlying verdict wins whenever
 * there is one: `notify-deleted` carries a consequence (147 disarms the
 * writer on it) and already implies contact was restored, while the marker
 * clears from `reach` either way. "Back in touch" is said only when there is
 * nothing more informative to say.
 */
export function decideWatchStep(
  outcome: Result<WorkflowSummary | null, string>,
  known: string | undefined,
  reach: WatchReach,
): { readonly reach: WatchReach; readonly action: FileWatchAction } {
  if (!outcome.ok) {
    const consecutiveFailures = reach.consecutiveFailures + 1;
    const blind = reach.blind || consecutiveFailures >= BLIND_AFTER_FAILED_POLLS;
    return {
      reach: { consecutiveFailures, blind },
      action: blind && !reach.blind ? { kind: 'notify-blind' } : { kind: 'none' },
    };
  }
  const action = decideFileWatchAction(outcome.value, known);
  if (reach.blind && action.kind === 'none') {
    return { reach: IN_TOUCH, action: { kind: 'notify-back-in-touch' } };
  }
  return { reach: IN_TOUCH, action };
}

/**
 * The reach, published where a *persistent* surface can read it.
 *
 * A toast is not enough on its own and the ticket says why: it fades after
 * five seconds, and what survives the fade was identical in all three states.
 * Same shape as `subscribeOpenSlug` — the toolbar's Save subscribes and
 * re-derives, rather than a parent remembering to bump a nonce.
 */
let reach: WatchReach = IN_TOUCH;
const reachListeners = new Set<() => void>();

export function getWatchReach(): WatchReach {
  return reach;
}

export function publishWatchReach(next: WatchReach): void {
  if (next.consecutiveFailures === reach.consecutiveFailures && next.blind === reach.blind) return;
  reach = next;
  for (const listener of reachListeners) listener();
}

export function subscribeWatchReach(listener: () => void): () => void {
  reachListeners.add(listener);
  return () => {
    reachListeners.delete(listener);
  };
}
