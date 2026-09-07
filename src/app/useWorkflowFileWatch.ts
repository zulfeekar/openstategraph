import { useEffect, useRef } from 'react';
import { invalidateSlug } from '@core/runtime/SlugCache';
import { workflowCatalogue } from '@core/runtime/workflowCatalogue';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { abandonDeletedWorkflow } from './diskAutosave';
import { announceRevisionSeen } from './externalWorkflowChange';
import {
  BLIND_AFTER_FAILED_POLLS,
  CURRENT_SLUG_KEY,
  IN_TOUCH,
  type WatchReach,
  decideWatchStep,
  getKnownSavedAt,
  getWatchReach,
  publishWatchReach,
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
    // Held here rather than in a ref: it belongs to this poll loop and dies
    // with it. The *published* copy is what surfaces read.
    let reach: WatchReach = getWatchReach();

    const poll = async () => {
      const slug = sessionStorage.getItem(CURRENT_SLUG_KEY);
      if (!slug) return;

      // The open slug is asked about by name. Not `list()` — see
      // `decideFileWatchAction` and `WorkflowFileClient.summary` on why a
      // surface listing cannot answer "does my file still exist".
      const outcome = await client.summary(slug);
      if (cancelled) return;

      // **Every outcome is acted on, including the ones that never arrived**
      // (`say-it-on-the-surface/07`). This used to read `if (outcome.ok)` with
      // no `else`, so a poll that could not reach the backend was
      // indistinguishable from one that reached it and found nothing wrong —
      // nine failed polls over forty-five seconds produced nothing at all,
      // while a deletion produced a toast and health produced nothing. Two of
      // the three states were one output, on the surface whose whole job is to
      // say what is true.
      // **Every successful poll says what revision the file holds**
      // (`osg-agent-experience/69`). The row already carries the digest, so
      // this costs nothing and no connection at all. That was the whole
      // mechanism when three long-lived streams meant two editor tabs
      // saturated a browser's six-per-origin HTTP/1.1 budget; since `71` the
      // tab holds one connection and hears `workflow.changed` on it, and this
      // is the floor underneath — five seconds, no socket, true however many
      // tabs are open and whether or not the stream is up.
      //
      // Published unconditionally rather than only on a change, because the
      // consumer deduplicates against the revision *it* holds — which is a
      // different question from "did `savedAt` move", and the only one that
      // decides whether a document should be replaced.
      if (outcome.ok) announceRevisionSeen(slug, outcome.value?.digest);

      const step = decideWatchStep(outcome, getKnownSavedAt(slug), reach);
      reach = step.reach;
      publishWatchReach(reach);
      {
        const action = step.action;
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
            // `deleted-elsewhere`: the user did not ask for this, and their
            // unsaved edits are still on screen — so the browser draft is
            // carried onto the fresh key the release re-keys this tab to,
            // rather than being left under a slug this tab no longer names
            // (`launch-readiness` 153).
            abandonDeletedWorkflow(slug, 'deleted-elsewhere');
            onNotify(
              'This workflow was deleted on disk. Your copy is still open here — ' +
                'Save it to create a new workflow from it.',
            );
            break;
          case 'notify-changed':
            // **Deliberately silent now** (`osg-agent-experience/69`). This
            // used to say *"open Manage Workflows and Load it to see the
            // latest version"*, which asked the user to perform a reload — the
            // exact gesture `68` is the ticket about, and a sentence that told
            // somebody with unsaved edits to go and lose them.
            //
            // The revision published above reaches `useExternalWorkflowChange`,
            // which does the thing the sentence was asking for: a tab with no
            // unsaved edits takes the new version and says so, and a tab with
            // unsaved edits is asked which one to keep. Saying both would be
            // two notices for one event, and the older one names a door that
            // is now the wrong answer.
            //
            // The verdict itself is kept rather than removed: it is what
            // re-baselines `knownSavedAt`, and a future surface that wants to
            // show "changed at 10:42" has something to read.
            if (outcome.ok && outcome.value?.savedAt) {
              recordKnownSavedAt(slug, outcome.value.savedAt);
            }
            break;
          case 'notify-blind':
            // Named as a **wait**, never as work — `launch-readiness/141`'s
            // discipline, for the same reason: claiming to know what is
            // happening when you do not is the defect one layer down. This
            // says what stopped being knowable and what is unaffected. It
            // does not say the backend is down, because the only thing
            // observed is that this call did not answer.
            onNotify(
              `Cannot reach the backend — nothing has answered for ${BLIND_AFTER_FAILED_POLLS} checks in a row, ` +
                'so this editor can no longer tell you whether this workflow is still on disk. ' +
                'Your canvas is unaffected.',
            );
            break;
          case 'notify-back-in-touch':
            // Said because the alternative is a stale alarm nobody clears.
            onNotify('Back in touch with the backend — this workflow is being watched again.');
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
      // Nothing is polling any more, so nothing can claim to be blind: a
      // marker outliving the watch that raised it is the stale alarm this
      // ticket is about, with the arrow reversed.
      publishWatchReach(IN_TOUCH);
    };
  }, [onNotify]);
}
