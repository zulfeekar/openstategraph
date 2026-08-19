import { useEffect, useRef } from 'react';
import { useWorkbench } from '@app/WorkbenchContext';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { getOpenSlug, setOpenSlug } from '@app/openWorkflow';
import {
  getOpenAddress,
  readAddressFromSearch,
  resolveAddressRequest,
  setOpenAddress,
} from '@app/openAddress';
import { formatMountAddress, isInstance, parseMountAddress } from '@core/model/MountAddress';
import { MountContext } from '@core/model/MountContext';
import { forgetMountHostDocument, rememberMountHostDocument } from '@app/diskAutosave';
import { recordKnownSavedAt } from '@app/workflowFileWatch';
import { clearDrillStack } from '@app/drillStack';
import { hasDraftFor } from '@app/workflowDrafts';
import { refreshWorkflowCapabilities } from '@app/capabilityRefresh';
import {
  loadMountIntoEditor,
  loadWorkflowIntoEditor,
  type LoadedWorkflow,
} from './loadWorkflowIntoEditor';

/**
 * What the toast says — and it must say when the canvas is *not* the file.
 *
 * A bare "Opened: X" over this browser's restored draft would tell the user
 * they are looking at the backend's copy when they are looking at their own
 * unsaved edits to it. Ticket 23 was the mirror of that: the edits vanished
 * silently. Neither half is acceptable without a sentence.
 */
function describeOpened(loaded: LoadedWorkflow): string {
  // A lossy load comes first, ahead of the draft note: it is the one case
  // where what is on screen is *less* than what is on disk, and the user needs
  // to know before they touch anything. Opening `ops-desk` used to drop four
  // of its twelve links and write that back to the file without a word
  // (`every-workflow-green` 22); autosave is now withheld, and this is the
  // sentence that says why.
  if (loaded.incomplete) {
    return (
      `Opened: ${loaded.name} — but not all of the file could be shown ` +
      `(${loaded.incomplete}). It will not be auto-saved, so the file keeps what it has.`
    );
  }
  return loaded.restoredDraft
    ? `Opened: ${loaded.name} — with your unsaved edits from this browser, not the saved file.`
    : `Opened: ${loaded.name}`;
}

/**
 * Open the workflow the URL names, once, at startup (ticket 20).
 *
 * This is what makes `?w=<slug>` a real deep link rather than decoration: a
 * colleague's link, a bookmark, or a reload of a tab that was pointed
 * somewhere all arrive here and get the document off the backend.
 *
 * It deliberately does **not** fire for a reload of a tab that already has
 * that same workflow open — `resolveOpenRequest` decides, and its docstring
 * says why: this tab's autosave holds unsaved edits to that very workflow, and
 * refetching the file over them would discard work on every reload.
 *
 * Failure is a toast, and the URL is left alone. A link to a workflow that is
 * not on *this* backend (a colleague's local machine, a package not pulled
 * yet) is a real thing to be told about, and rewriting the address bar to hide
 * it would make the link un-retryable after the developer fixes the cause.
 */
export function useDeepLinkedWorkflow(notify: (message: string) => void): void {
  const workbench = useWorkbench();
  // StrictMode mounts effects twice; fetching twice would be visible and would
  // race two imports into one canvas.
  const done = useRef(false);
  const notifyRef = useRef(notify);
  useEffect(() => {
    notifyRef.current = notify;
  }, [notify]);

  useEffect(() => {
    if (done.current) return;
    done.current = true;

    // Addresses, not slugs (ticket 42): `concierge/wf-music` and
    // `concierge/wf-other` are both `chinook-assistant`, so comparing slugs
    // would call a link to the second a reload of the first and leave the
    // wrong instance's overrides on screen.
    const openAddress = getOpenAddress() ?? parseMountAddress(getOpenSlug() ?? '');
    const request = resolveAddressRequest({
      urlAddress: readAddressFromSearch(window.location.search),
      openAddress,
      // Ticket 49. Declining to refetch is only defensible while this browser
      // actually holds unsaved edits to refetch *over*; with none, the restore
      // branch below leaves the blank default document on screen for a slug the
      // backend can serve in full. That is the blocker, and it is the state of
      // every tab immediately after its first Save.
      hasDraft: hasDraftFor(openAddress === null ? null : formatMountAddress(openAddress)),
    });
    if (request.action === 'restore') {
      // **Nothing to fetch is about the *document*, not the capabilities**
      // (`every-workflow-green` 07). Capabilities were fetched inside
      // `loadWorkflowIntoEditor`, the function this branch skips, so the two
      // were welded together by accident: every warm reload ran on whatever
      // picture the last cold load left behind — a tool added to `tools/`
      // invisible, a `pip install` invisible, and the capability warnings
      // stale, which is the channel built so a half-authored tool is never
      // silent.
      //
      // The two have different staleness rules and that is the whole fix. A
      // document must not be refetched over this tab's unsaved edits; a
      // capability picture has no local edits to protect. So the guard above
      // is untouched and this refreshes beside it.
      //
      // `refreshWorkflowCapabilities` rather than a fetch written here: it
      // already unregisters what disappeared and keeps the Refresh baseline
      // honest, and a private copy would drift from it.
      void refreshWorkflowCapabilities(
        getOpenSlug(),
        workbench.registry,
        workbench.engine.executors,
      );

      // Nothing to fetch — but if this tab has something open and the URL
      // does not say so, put it there. That is what makes "copy the address
      // bar" work after a plain reload, without anyone pressing anything.
      const openAddress = getOpenAddress();
      if (openAddress !== null) {
        setOpenAddress(openAddress, getOpenSlug() ?? openAddress.root);
        // A restored instance is still an instance. The scope is normally
        // entered by `loadMountIntoEditor`, and this branch deliberately does
        // not load — so without this line a reload of an instance address came
        // back with the mount's document on screen and the gate *off*, and a
        // delete went through. Found in the browser; no unit test could have
        // seen it, because the gap is between two code paths rather than
        // inside either.
        if (isInstance(openAddress)) {
          const mountId = openAddress.mountPath[openAddress.mountPath.length - 1] ?? '';
          // The root package is fetched even on a restore, because it is what
          // an edit here is written to. Without it the instance would be
          // editable with nowhere to put the result.
          const client = new WorkflowFileClient();
          void Promise.all([
            client.load(openAddress.root),
            client.loadMount(openAddress, { inherited: true }),
          ]).then(async ([root, inheritedDoc]) => {
            workbench.controller.document.enterInstance(
              mountId,
              root.ok
                ? new MountContext(
                    openAddress,
                    root.value as Record<string, unknown>,
                    inheritedDoc.ok
                      ? (inheritedDoc.value.document as Record<string, unknown>)
                      : undefined,
                  )
                : undefined,
            );
            // The same two baselines `loadMountIntoEditor` records, because a
            // reload lands in exactly the state that path produces. Without
            // the first, autosave has no proof this page opened the host and
            // refuses every write — so an override made after a reload would
            // be badged and dropped all over again (ticket 44). Without the
            // second, the compare-and-set that stops a whole-document write
            // reverting somebody else's parent edit disables itself.
            if (!root.ok) {
              forgetMountHostDocument(openAddress.root);
              return;
            }
            rememberMountHostDocument(openAddress.root, root.value);
            const row = await client.summary(openAddress.root);
            recordKnownSavedAt(
              openAddress.root,
              row.ok ? (row.value?.savedAt ?? undefined) : undefined,
            );
          });
        }
        return;
      }
      const open = getOpenSlug();
      if (open !== null) setOpenSlug(open);
      return;
    }

    const asked = formatMountAddress(request.address);
    void (async () => {
      const client = new WorkflowFileClient();
      const outcome = isInstance(request.address)
        ? await loadMountIntoEditor(request.address, client, workbench)
        : await loadWorkflowIntoEditor(request.address.root, client, workbench);
      if (!outcome.ok) {
        notifyRef.current(`Could not open "${asked}" from the link: ${outcome.error}`);
        return;
      }
      // Arriving by link is a navigation, not a return: there is no parent
      // workflow to offer a way back to.
      clearDrillStack();
      notifyRef.current(describeOpened(outcome.value));
    })();
  }, [workbench]);
}
