import { useEffect, useRef } from 'react';
import { WorkflowFileClient, type WorkflowSummary } from '@core/runtime/WorkflowFileClient';

/**
 * The slug of whichever saved workflow this tab currently has open —
 * `sessionStorage`, not the model, so a rename changes the display name
 * only, never the directory (ticket 14's identity decision).
 */
export const CURRENT_SLUG_KEY = 'dyflow-current-workflow-slug';

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
 * reports for `slug` and what this tab last knew, what should happen.
 * Pulled out of the hook below so it is testable without a timer, a
 * network stub, or React — the same reasoning `ExecutionEngine`'s
 * `rejectBeforeStart` split applies to its own side effect.
 */
export function decideFileWatchAction(
  entries: readonly WorkflowSummary[],
  slug: string,
  known: string | undefined,
): FileWatchAction {
  const entry = entries.find((wf) => wf.slug === slug);
  if (!entry) return { kind: 'notify-deleted' };
  if (known === undefined) return { kind: 'baseline', savedAt: entry.savedAt };
  if (entry.savedAt !== known) return { kind: 'notify-changed' };
  return { kind: 'none' };
}

const POLL_INTERVAL_MS = 5000;

/**
 * Ticket 16's other half. `WorkflowManager` already writes files; nothing
 * noticed when a file changed *underneath* an open editor — another tab
 * saving the same slug, a teammate's pull, a hand-edit. Polls the backend's
 * workflow list for the currently open slug and compares its `savedAt`
 * against the value this tab itself last recorded (`recordKnownSavedAt`,
 * called by `WorkflowManager` after every successful save or load) — so
 * this tab's own writes never self-trigger the notice, only a change this
 * tab did not make.
 *
 * Deliberately notify-only, never auto-reload or merge — the ticket's own
 * open questions, resolved here as: silently discarding unsaved local edits
 * to pull in an external change is a worse failure than asking the user to
 * reload by hand via the existing "Manage Workflows" panel. Mounted once,
 * independent of whether that panel happens to be open, since an external
 * change can land at any time.
 */
export function useWorkflowFileWatch(onNotify: (message: string) => void): void {
  const clientRef = useRef<WorkflowFileClient | null>(null);
  if (!clientRef.current) clientRef.current = new WorkflowFileClient();

  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;
    let cancelled = false;

    const poll = async () => {
      const slug = sessionStorage.getItem(CURRENT_SLUG_KEY);
      if (!slug) return;

      const outcome = await client.list();
      if (cancelled || !outcome.ok) return;

      const action = decideFileWatchAction(outcome.value, slug, knownSavedAt.get(slug));
      switch (action.kind) {
        case 'baseline':
          knownSavedAt.set(slug, action.savedAt);
          break;
        case 'notify-deleted':
          onNotify('This workflow was deleted on disk — your open copy is no longer backed by a saved file.');
          break;
        case 'notify-changed':
          onNotify('This workflow changed on disk — open Manage Workflows and Load it to see the latest version.');
          break;
        case 'none':
          break;
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
