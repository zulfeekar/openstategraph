import { useEffect, useRef } from 'react';
import { useWorkbench } from '@app/WorkbenchContext';
import { diskDocumentStatus, forgetDiskDocument, rememberDiskDocument } from '@app/diskAutosave';
import { decideExternalChange, subscribeRevisionSeen } from '@app/externalWorkflowChange';
import { offerRestoredDraftChoice } from '@app/restoredDraftConflict';
import { CURRENT_SLUG_KEY, getKnownDigest, recordKnownVersion } from '@app/workflowFileWatch';
import { subscribeWorkflowSaved } from '@app/workflowSaveBroadcast';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { registerNodeTypesForRawDocument } from '@nodes/workflowScoped';
import { workflowRefreshedFromDisk } from './restoredDraftChoiceCopy';

/**
 * The editor half of *three tabs on one workflow* — `osg-agent-experience/69`.
 *
 * The owner, after `68`: *"a user opens three tabs on the same workflow, how
 * does each get the latest changes?"* Until this hook, none of them did. The
 * file watch noticed within five seconds and said a sentence — *open Manage
 * Workflows and Load it* — which asks a user to perform a reload, the exact
 * gesture `68` is the ticket about.
 *
 * ## Two transports, one decision — and the third one this tab cannot afford
 *
 * `subscribeRevisionSeen` is the mechanism: the five-second `savedAt` poll
 * `useWorkflowFileWatch` already runs receives the file's digest in the row it
 * already reads, so it covers **every** writer — a second tab, the command
 * line, a coding agent, a `git pull` — and costs no connection.
 * `subscribeWorkflowSaved` is a `BroadcastChannel` between tabs of one
 * browser: strictly fewer writers, reached instantly, which is what stops two
 * tabs of one person writing inside each other's blind window.
 *
 * **The backend's own `workflow.changed` stream is deliberately not opened
 * here, and that is a measurement rather than a preference.** It exists, it is
 * correct, and any client with connections to spare should use it — but this
 * editor has none. A browser allows six concurrent HTTP/1.1 connections per
 * origin and each tab already holds two long-lived ones (`/api/events`,
 * `/api/kanban/patrol/events`). Staged on 2026-09-05 against the running
 * editor with a third: two tabs saturated the budget, the last stream sat at
 * `readyState 0` for minutes, and ordinary `fetch` calls stopped completing —
 * so adding it made *two* tabs worse in order to make one tab faster. Two tabs
 * on one workflow is this ticket's own scenario. `osg-agent-experience/71`
 * carries the fix that keeps both: fold the frames onto the `/api/events`
 * connection this tab is already holding.
 *
 * Both live transports end in `decideExternalChange` against the same
 * `getKnownDigest(slug)`, so hearing one save twice is one action and one
 * ignore in either order. There is no sequence number and there must not be:
 * the revision is the digest, and it is the same string the 409 checks
 * (`osg-agent-experience/45`).
 *
 * ## Why a clean tab is not asked, and a dirty one is not refreshed
 *
 * A tab with no unsaved edits has nothing to lose, and a modal over a decision
 * with one sensible answer is how the *real* question gets dismissed unread.
 * A tab with unsaved edits holds the only copy of them, and this editor is not
 * the one who knows whether they or the file should win — which is `68`'s call
 * exactly, so it is `68`'s dialog exactly, with one sentence of the copy
 * differing.
 *
 * ## Nothing is written while the banner stands, and that needs a call
 *
 * On the reload path `ensureDiskBaseline` simply *never records* a baseline,
 * and `writeOpenWorkflowToDisk` reads a missing baseline as *never write this
 * package*. Here the tab has been working normally, so a baseline exists and
 * the next keystroke would autosave straight over the file the user is being
 * asked about. `forgetDiskDocument` before the offer is what makes the
 * subtitle's *"nothing has been written"* true — the same disarm
 * `standDownAfterConflict` and `abandonDeletedWorkflow` already use, not a
 * fourth mechanism.
 */
export function useExternalWorkflowChange(notify: (message: string) => void): void {
  const workbench = useWorkbench();
  // Held in refs and assigned in an effect, not during render. The
  // subscription below must be opened **once** — a stream re-opened on every
  // render is a server-side poll restarted on every render — so the effect
  // cannot depend on either value, and reading them through a ref is how a
  // long-lived subscription sees today's notifier and today's workbench.
  const notifyRef = useRef(notify);
  const workbenchRef = useRef(workbench);
  useEffect(() => {
    notifyRef.current = notify;
    workbenchRef.current = workbench;
  }, [notify, workbench]);

  useEffect(() => {
    const client = new WorkflowFileClient();
    let cancelled = false;

    /** What to do about `slug` now holding `digest`, and then doing it. */
    const react = async (slug: string, digest: string): Promise<void> => {
      const open = sessionStorage.getItem(CURRENT_SLUG_KEY);
      // A frame about a package this tab is not editing. The server already
      // filters its own stream by slug; this covers the `BroadcastChannel`,
      // which is one channel for the whole browser, and the moment between a
      // slug changing and this effect re-running.
      if (open !== slug) return;
      const bench = workbenchRef.current;
      const action = decideExternalChange({
        incomingDigest: digest,
        knownDigest: getKnownDigest(slug),
        status: diskDocumentStatus(slug, bench.model, bench.serializer),
      });
      if (action.kind === 'ignore') return;

      // One fetch, whichever answer follows: *take the file* needs the
      // document and so does a silent refresh, and asking the user first and
      // fetching afterwards would put a network failure in the middle of a
      // dialog they have already answered.
      const disk = await client.load(slug);
      if (cancelled || !disk.ok) return;
      // The open slug is read again: a `load` is a round trip, and a user who
      // opened another workflow while it was in flight must not have this one
      // imported over the top of it.
      if (sessionStorage.getItem(CURRENT_SLUG_KEY) !== slug) return;
      const fileName = (disk.value as { name?: string }).name ?? slug;

      if (action.kind === 'ask') {
        // **Before the offer, not after.** Autosave listens to
        // `controller.onChange` and fires a second later; a baseline left in
        // place would write this tab's draft over the file while the question
        // about that very file is still on screen.
        forgetDiskDocument(slug);
        offerRestoredDraftChoice({
          slug,
          cause: 'changed-elsewhere',
          file: disk.value,
          fileName,
        });
        return;
      }

      // A silent refresh. Node types first, as on every import path in this
      // repository: a workflow-scoped type must exist before `fromJSON` runs,
      // or every node of that type is skipped without a word.
      registerNodeTypesForRawDocument(disk.value, bench.registry, bench.engine.executors);
      bench.controller.document.importJSON(JSON.stringify(disk.value));
      // After the import, so the baseline describes what is now on screen and
      // the `onChange` this import fires finds nothing to write.
      rememberDiskDocument(slug, fileName, disk.value, bench.serializer);
      // And the revision, so the next save quotes what was actually taken
      // rather than the version this tab loaded with — the same pair
      // `ensureDiskBaseline` records for the same reason.
      const row = await client.summary(slug);
      if (cancelled) return;
      recordKnownVersion(slug, row.ok ? row.value : null);
      // Said out loud. Nothing was lost, but the canvas changed with no
      // gesture, and that is the one thing this editor may never do quietly.
      notifyRef.current(workflowRefreshedFromDisk(fileName));
    };

    // The mechanism, and the one that costs no connection: the five-second
    // `savedAt` poll `useWorkflowFileWatch` already runs publishes the digest
    // out of the row it already reads. See the header for what happened when
    // a third `EventSource` was opened here instead.
    const offPoll = subscribeRevisionSeen((slug, digest) => {
      void react(slug, digest);
    });

    // The same-browser half, which needs no slug of its own: one channel for
    // the origin, filtered by `react` against the open slug.
    const offBroadcast = subscribeWorkflowSaved((announcement) => {
      void react(announcement.slug, announcement.digest);
    });

    return () => {
      cancelled = true;
      offPoll();
      offBroadcast();
    };
  }, []);
}
