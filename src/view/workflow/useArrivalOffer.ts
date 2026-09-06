import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useWorkbench } from '@app/WorkbenchContext';
import { clearDrillStack } from '@app/drillStack';
import { readAddressFromSearch } from '@app/openAddress';
import { readOpenedStamps } from '@app/lastOpened';
import {
  arrivalWasDismissed,
  rememberArrivalDismissed,
  shouldOfferArrival,
} from '@app/arrivalOffer';
import { arrivalChoices, type ArrivalChoice } from '@core/runtime/arrivalChoices';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { loadWorkflowIntoEditor } from './loadWorkflowIntoEditor';

export interface ArrivalOffer {
  /** The project's workflows, most recently opened or edited first. */
  readonly choices: readonly ArrivalChoice[];
  /** Why the list is empty, when the reason is not that the project is. */
  readonly error: string | null;
  /** Whether the dialog is on screen. */
  readonly open: boolean;
  /** Whether a load is in flight — both surfaces disable their rows on it. */
  readonly busy: boolean;
  readonly dismiss: () => void;
  readonly openWorkflow: (slug: string) => Promise<void>;
}

/**
 * What an arrival with no workflow named is offered — `install-experience` 28.
 *
 * ## One fetch, two surfaces
 *
 * The dialog is the offer; the start panel on the blank canvas is where the
 * offer goes once it has been dismissed. They show the same rows in the same
 * order, so they read one list from one request. Two fetches of one endpoint
 * would be two lists that could disagree about what the project holds, on one
 * screen, seconds apart.
 *
 * The fetch happens **whether or not the dialog will open**, and that is
 * deliberate: the start panel needs the rows on every blank canvas, including
 * the one a `?w=` link left behind after its workflow was closed.
 *
 * ## It waits for the session to settle
 *
 * `useWorkflowSession` decides, in one effect and before anything can write,
 * whether this load is a reload restoring its own draft, a deep link, or the
 * one first visit ticket 24 owns. Every one of those is a reason not to offer,
 * and asking before that effect has run would read all three as `false`. So
 * `settled` gates it, and the two hooks agree in advance rather than racing —
 * the same arrangement `resolveOpenRequest` already keeps between the session
 * hook and the deep-link hook.
 *
 * ## Opening is a click, and there is one of them
 *
 * `openWorkflow` is handed to both surfaces rather than each performing its own
 * load. The order of capability registration against import, the frozen slug
 * and the file watch's baseline are knowledge that lives in
 * `loadWorkflowIntoEditor`; a second copy at a second call site is what that
 * module exists to prevent.
 */
export function useArrivalOffer(input: {
  /** Whether the session hook has finished deciding. */
  readonly settled: boolean;
  /** Whether this tab restored its own autosaved document. */
  readonly restoredDraft: boolean;
  /** Whether this load handed over ticket 24's first-run starter. */
  readonly placedStarter: boolean;
  /** Whether a document was already on the canvas when this load settled. */
  readonly canvasHoldsDocument: boolean;
  readonly notify: (message: string) => void;
}): ArrivalOffer {
  const workbench = useWorkbench();
  const client = useMemo(() => new WorkflowFileClient(), []);
  const [choices, setChoices] = useState<readonly ArrivalChoice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // StrictMode mounts effects twice; a second fetch would be harmless and a
  // second `setOpen` after a dismissal would not.
  const asked = useRef(false);

  const { settled, restoredDraft, placedStarter, canvasHoldsDocument, notify } = input;

  useEffect(() => {
    if (!settled || asked.current) return;
    asked.current = true;

    // Decided **before** the fetch, so a slow backend cannot turn a deep link
    // into an arrival: by the time rows arrive the address bar is still the
    // one this load began on, but the reasoning is easier to trust when the
    // question is asked once, at the moment it is actually about.
    const offering = shouldOfferArrival({
      // An address, not a bare slug: `?w=concierge/wf-music` names one mount
      // and is every bit as much a link that must land where it says.
      urlNamedWorkflow: readAddressFromSearch(window.location.search) !== null,
      restoredDraft,
      placedStarter,
      canvasHoldsDocument,
      dismissed: arrivalWasDismissed(),
    });

    void client.list().then((result) => {
      if (result.ok) setChoices(arrivalChoices(result.value, readOpenedStamps()));
      // A backend that cannot answer costs the list and nothing else. It is
      // said rather than shown as an empty project, because "no workflows" and
      // "could not ask" are two very different states, and one appearance for
      // both is how a mounted editor's blank canvas came to be reported as a
      // failed install (`install-experience` 27).
      else setError(`Could not list this project's workflows: ${result.error}`);
      if (offering) setOpen(true);
    });
  }, [settled, restoredDraft, placedStarter, canvasHoldsDocument, client]);

  const dismiss = useCallback(() => {
    // Recorded first: the dialog is gone either way, and a store that refuses
    // the write must not leave the flag disagreeing with the screen.
    rememberArrivalDismissed();
    setOpen(false);
  }, []);

  const openWorkflow = useCallback(
    async (slug: string) => {
      setBusy(true);
      const outcome = await loadWorkflowIntoEditor(slug, client, workbench);
      setBusy(false);
      if (!outcome.ok) {
        notify(`Could not load: ${outcome.error}`);
        return;
      }
      // Opening from here is a navigation of its own, not a return — the same
      // reasoning the Workflows panel's own load records.
      clearDrillStack();
      notify(
        outcome.value.restoredDraft
          ? `Loaded: ${outcome.value.name} — with your unsaved edits from this browser, not the saved file.`
          : `Loaded: ${outcome.value.name}`,
      );
      // The offer has been taken. Dismissing it here rather than only closing
      // it is what stops a reload of this same tab — which now has a workflow
      // open and will not offer anyway — from being the only thing that
      // records the answer.
      dismiss();
    },
    [client, workbench, notify, dismiss],
  );

  return { choices, error, open, busy, dismiss, openWorkflow };
}
