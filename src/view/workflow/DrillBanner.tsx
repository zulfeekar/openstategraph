import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Share2 } from 'lucide-react';
import { Icon } from '@design/primitives';
import { useModelEvents, useWorkbench } from '@app/WorkbenchContext';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { getOpenAddress, subscribeOpenAddress } from '@app/openAddress';
import {
  formatMountAddress,
  isInstance,
  parentAddress,
  type MountAddress,
} from '@core/model/MountAddress';
import { loadMountIntoEditor, loadWorkflowIntoEditor } from './loadWorkflowIntoEditor';
import './DrillBanner.css';

/**
 * Where am I, and how do I get back?
 *
 * Drilling into a mount replaces the canvas wholesale. Without this strip the
 * user is simply somewhere else: a different graph, no statement of *which*
 * mount it is, and no route home but guessing the parent's name in the
 * Workflows panel.
 *
 * Deliberately a slim strip and not a modal, a dialog or a toast:
 *  - a toast evaporates, and the question "where am I" outlives three seconds;
 *  - a modal would block editing, which is the thing the user came here to do;
 *  - a strip is always visible while it is true, and gone the instant it is not.
 *
 * ## The trail is derived, not remembered — ticket 42
 *
 * It used to read a `drillStack` of `{slug, name}` frames, which deduped by
 * slug: a chain passing through two mounts of one package collapsed into a
 * single frame, and Back offered the wrong destination. The address already
 * holds the whole chain (`concierge/wf-music/wf-inner`), so the way back is
 * simply its prefix — a fact rather than a record, and one that cannot fall
 * out of step with the canvas.
 *
 * ## And it no longer says "shared definition"
 *
 * That label was true when drilling in loaded the *package*. Under an instance
 * address it would be exactly backwards: what is on screen is this mount's own
 * document, and an edit here is this mount's own. Saying "shared" would send
 * someone to the Workflows panel to make a change they could have made here,
 * or worse, stop them making one at all.
 */
export function DrillBanner() {
  const workbench = useWorkbench();
  // The current document's name changes under us on every load — the import
  // fires `workflow:reset`, the Inspector's Name field fires `workflow:name`.
  useModelEvents(['workflow:name', 'workflow:reset']);
  const [address, setAddress] = useState<MountAddress | null>(() => getOpenAddress());
  const [busy, setBusy] = useState(false);

  useEffect(() => subscribeOpenAddress(() => setAddress(getOpenAddress())), []);

  const back = useCallback(async () => {
    const here = getOpenAddress();
    const up = here ? parentAddress(here) : null;
    if (!up) return;
    setBusy(true);
    const client = new WorkflowFileClient();
    // Going back is a *pop*, and the destination is a prefix of where we are,
    // so it needs no provenance and cannot name a document that was never
    // passed through.
    await (isInstance(up)
      ? loadMountIntoEditor(up, client, workbench)
      : loadWorkflowIntoEditor(up.root, client, workbench));
    setBusy(false);
  }, [workbench]);

  if (!address || !isInstance(address)) return null;

  const up = parentAddress(address);
  const mountId = address.mountPath[address.mountPath.length - 1] ?? '';

  return (
    <div className="drill-banner" role="status">
      <Icon glyph={Share2} size="xs" />
      <span className="drill-banner__where">
        Editing <strong>{workbench.model.name}</strong>
      </span>
      <span
        className="drill-banner__shared"
        title={
          `This is the ${mountId} mount — its own overrides, not the shared package. ` +
          `Field values can differ here; the workflow's shape cannot.`
        }
      >
        {mountId}
      </span>
      {up ? (
        <button
          type="button"
          className="drill-banner__back"
          disabled={busy}
          title={`Return to ${formatMountAddress(up)}`}
          onClick={() => void back()}
        >
          <Icon glyph={ArrowLeft} size="xs" />
          Back to {isInstance(up) ? (up.mountPath[up.mountPath.length - 1] ?? up.root) : up.root}
        </button>
      ) : null}
    </div>
  );
}
