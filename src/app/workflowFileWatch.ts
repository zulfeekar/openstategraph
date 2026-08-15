import { useEffect, useRef } from 'react';
import { invalidateSlug } from '@core/runtime/SlugCache';
import { workflowCatalogue } from '@core/runtime/workflowCatalogue';
import { WorkflowFileClient, type WorkflowSummary } from '@core/runtime/WorkflowFileClient';

/**
 * The slug of whichever saved workflow this tab currently has open —
 * `sessionStorage`, not the model, so a rename changes the display name
 * only, never the directory (ticket 14's identity decision).
 */
export const CURRENT_SLUG_KEY = 'openstategraph-current-workflow-slug';

/**
 * The `savedAt` this tab itself last wrote or read for a slug — a plain
 * module-level map, not persisted, because a full page reload re-restores
 * everything through `useWorkflowSession` and the watch below re-baselines
 * on its first poll with no false positive either way.
 */
const knownSavedAt = new Map<string, string>();

export function recordKnownSavedAt(slug: string, savedAt: string | undefined): void {
  if (savedAt) knownSavedAt.set(slug, savedAt);
}

export function forgetKnownSavedAt(slug: string): void {
  knownSavedAt.delete(slug);
}

/** Exposed for tests — the hook itself reads the map directly. */
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
 * Pulled out of the hook below so it is testable without a timer, a
 * network stub, or React — the same reasoning `ExecutionEngine`'s
 * `rejectBeforeStart` split applies to its own side effect.
 *
 * **`entry` is the answer to an existence question, not a visibility one**
 * (ticket 21). It used to be `entries.find(...)` over
 * `GET /api/workflows?surface=editor`, which is a *surface*: it omits hidden
 * packages by design, so drilling into `concierge` or `workflow-architect`
 * made this function announce a deletion over a file the backend was happily
 * serving 200. It now takes what `WorkflowFileClient.summary(slug)` returned,
 * where `null` means a 404 and nothing else does — so a genuinely deleted
 * workflow still warns, and only that.
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

const POLL_INTERVAL_MS = 5000;

/**
 * Ticket 16's other half: `WorkflowManager` already writes
 * files; nothing noticed when a file changed *underneath* an open editor —
 * another tab saving the same slug, a teammate's pull, a hand-edit. Compares
 * the backend's `savedAt` **for this tab's own slug** against the value this
 * tab itself last recorded (`recordKnownSavedAt`, called by `WorkflowManager` after every
 * successful save or load) — so this tab's own writes never self-trigger
 * the notice, only a change this tab did not make. Deliberately
 * notify-only, never auto-reload or merge — silently discarding unsaved
 * local edits to pull in an external change is a worse failure than asking
 * the user to reload by hand via the existing "Manage Workflows" panel.
 *
 * This watches the **document** only. A workflow's discovered `tools/`
 * capabilities are deliberately *not* polled here — see
 * `capabilityRefresh.ts` for why they are refreshed on load and on the
 * palette's explicit Refresh instead of on a timer.
 *
 * Mounted once, independent of whether "Manage Workflows" happens to be
 * open, since a change can land at any time.
 */
export function useWorkflowFileWatch(onNotify: (message: string) => void): void {
  const clientRef = useRef<WorkflowFileClient | null>(null);
  if (!clientRef.current) clientRef.current = new WorkflowFileClient();

  // The mount slug picker's source (ticket 05). Started here because this
  // hook is already mounted once for the life of the editor and already holds
  // a client — a second subscription to `/api/events` would be a second thing
  // to reconnect and a second place to get the base URL wrong.
  //
  // The same event retires what the card bodies cached about that slug — its
  // document, its compiled peek, its schema. They are per-slug caches with no
  // clock of their own (`SlugCache`), and this is the one place the editor
  // learns that a package moved, which is the same reason the catalogue sync
  // lives here.
  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;
    return workflowCatalogue.syncFrom(client, (change) => invalidateSlug(change.slug));
  }, []);

  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;
    let cancelled = false;

    const poll = async () => {
      const slug = sessionStorage.getItem(CURRENT_SLUG_KEY);
      if (!slug) return;

      // The open slug is asked about by name. Not `list()` — see
      // `decideFileWatchAction` and `WorkflowFileClient.summary` on why a
      // surface listing cannot answer "does my file still exist".
      const outcome = await client.summary(slug);
      if (!cancelled && outcome.ok) {
        const action = decideFileWatchAction(outcome.value, knownSavedAt.get(slug));
        switch (action.kind) {
          case 'baseline':
            knownSavedAt.set(slug, action.savedAt);
            break;
          case 'notify-deleted':
            onNotify(
              'This workflow was deleted on disk — your open copy is no longer backed by a saved file.',
            );
            break;
          case 'notify-changed':
            onNotify(
              'This workflow changed on disk — open Manage Workflows and Load it to see the latest version.',
            );
            break;
          case 'none':
            break;
        }
      }
    };

    const timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    void poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [onNotify]);
}
