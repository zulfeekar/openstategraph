import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Share2 } from 'lucide-react';
import { Icon } from '@design/primitives';
import { useModelEvents, useWorkbench } from '@app/WorkbenchContext';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { peekDrillFrame, popDrillFrame, subscribeDrillStack, type DrillFrame } from '@app/drillStack';
import { loadWorkflowIntoEditor } from './loadWorkflowIntoEditor';
import './DrillBanner.css';

/**
 * Where am I, and how do I get back?
 *
 * Drilling into a mount replaces the canvas wholesale. Without this strip the
 * user is simply somewhere else: a different graph, no statement that it is
 * the *shared* definition rather than this mount's private copy, and no route
 * home but guessing the parent's name in the Workflows panel.
 *
 * Deliberately a slim strip and not a modal, a dialog or a toast:
 *  - a toast evaporates, and the question "where am I" outlives three seconds;
 *  - a modal would block editing, which is the thing the user came here to do;
 *  - a strip is always visible while it is true, and gone the instant it is not.
 *
 * It renders only when the drill stack is non-empty, so the ordinary case —
 * a workflow opened from the Workflows panel — pays nothing and sees nothing.
 */
export function DrillBanner() {
  const workbench = useWorkbench();
  // The current document's name changes under us on every load — the import
  // fires `workflow:reset`, the Inspector's Name field fires `workflow:name`.
  useModelEvents(['workflow:name', 'workflow:reset']);
  const [parent, setParent] = useState<DrillFrame | undefined>(() => peekDrillFrame());
  const [busy, setBusy] = useState(false);

  useEffect(() => subscribeDrillStack(() => setParent(peekDrillFrame())), []);

  const back = useCallback(async () => {
    const frame = peekDrillFrame();
    if (!frame) return;
    setBusy(true);
    // No provenance: going back is a *pop*, not another drill-in. The frame
    // comes off only once the load succeeded, so a failed return leaves the
    // banner — and the way out — intact.
    const outcome = await loadWorkflowIntoEditor(frame.slug, new WorkflowFileClient(), workbench);
    setBusy(false);
    if (outcome.ok) popDrillFrame();
  }, [workbench]);

  if (!parent) return null;

  return (
    <div className="drill-banner" role="status">
      <Icon glyph={Share2} size="xs" />
      <span className="drill-banner__where">
        Editing <strong>{workbench.model.name}</strong>
      </span>
      <span className="drill-banner__shared" title="Every mount of this package uses this definition — an edit here changes all of them.">
        shared definition
      </span>
      <button
        type="button"
        className="drill-banner__back"
        disabled={busy}
        title={`Return to ${parent.name}`}
        onClick={() => void back()}
      >
        <Icon glyph={ArrowLeft} size="xs" />
        Back to {parent.name}
      </button>
    </div>
  );
}
