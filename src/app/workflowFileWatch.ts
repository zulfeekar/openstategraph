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

export type FileWatchAction =
  | { readonly kind: 'none' }
  | { readonly kind: 'baseline'; readonly savedAt: string }
  | { readonly kind: 'notify-deleted' }
  | { readonly kind: 'notify-changed' };

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
