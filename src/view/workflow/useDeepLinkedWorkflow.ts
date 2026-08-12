import { useEffect, useRef } from 'react';
import { useWorkbench } from '@app/WorkbenchContext';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import {
  getOpenSlug,
  readSlugFromSearch,
  resolveOpenRequest,
  setOpenSlug,
} from '@app/openWorkflow';
import { clearDrillStack } from '@app/drillStack';
import { loadWorkflowIntoEditor, type LoadedWorkflow } from './loadWorkflowIntoEditor';

/**
 * What the toast says — and it must say when the canvas is *not* the file.
 *
 * A bare "Opened: X" over this browser's restored draft would tell the user
 * they are looking at the backend's copy when they are looking at their own
 * unsaved edits to it. Ticket 23 was the mirror of that: the edits vanished
 * silently. Neither half is acceptable without a sentence.
 */
function describeOpened(loaded: LoadedWorkflow): string {
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

    const request = resolveOpenRequest({
      urlSlug: readSlugFromSearch(window.location.search),
      openSlug: getOpenSlug(),
    });
    if (request.action === 'restore') {
      // Nothing to fetch — but if this tab has a workflow open and the URL
      // does not say so, put it there. That is what makes "copy the address
      // bar" work after a plain reload, without anyone pressing anything.
      const open = getOpenSlug();
      if (open !== null) setOpenSlug(open);
      return;
    }

    void (async () => {
      const outcome = await loadWorkflowIntoEditor(
        request.slug,
        new WorkflowFileClient(),
        workbench,
      );
      if (!outcome.ok) {
        notifyRef.current(`Could not open "${request.slug}" from the link: ${outcome.error}`);
        return;
      }
      // Arriving by link is a navigation, not a return: there is no parent
      // workflow to offer a way back to.
      clearDrillStack();
      notifyRef.current(describeOpened(outcome.value));
    })();
  }, [workbench]);
}
