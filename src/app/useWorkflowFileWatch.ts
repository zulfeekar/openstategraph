import { useEffect, useRef } from 'react';
import { invalidateSlug } from '@core/runtime/SlugCache';
import { workflowCatalogue } from '@core/runtime/workflowCatalogue';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { abandonDeletedWorkflow } from './diskAutosave';
import {
  CURRENT_SLUG_KEY,
  decideFileWatchAction,
  getKnownSavedAt,
  recordKnownSavedAt,
} from './workflowFileWatch';

/**
 * The effects half of the file watch — timers, network, and what a verdict
 * *means*.
 *
 * Split from `workflowFileWatch.ts` when the deleted verdict acquired a
 * consequence (launch-readiness 147). That module owns the open-slug key and
 * the `savedAt` this tab knows, and `diskAutosave` reads both; a hook living
 * beside them could not call `abandonDeletedWorkflow` without an import cycle.
 * The division is the one that module's own tests already describe: the pure
 * decision there, the machinery here.
 */
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
        const action = decideFileWatchAction(outcome.value, getKnownSavedAt(slug));
        switch (action.kind) {
          case 'baseline':
            recordKnownSavedAt(slug, action.savedAt);
            break;
          case 'notify-deleted':
            // **Told and disarmed, not merely told** (launch-readiness 147).
            // Until this call the notice was the only effect: the baseline
            // stayed, so one keystroke re-created the package through
            // `PUT` — holding `workflow.json` and `AGENTS.md`, with the
            // `tools/`, `functions/` and `tests/` that made it work gone for
            // good. `abandonDeletedWorkflow` stops the writer and releases the
            // slug, which is also what makes the sentence below true.
            //
            // It clears the open slug, so this is the last poll for it and the
            // notice is raised once rather than every five seconds.
            abandonDeletedWorkflow(slug);
            onNotify(
              'This workflow was deleted on disk. Your copy is still open here — ' +
                'Save it to create a new workflow from it.',
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
