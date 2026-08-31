import { FolderOpen, Plus } from 'lucide-react';
import { Badge, Button, Icon } from '@design/primitives';
import type { ArrivalChoice } from '@core/runtime/arrivalChoices';
import { HIDDEN_PACKAGE_MARK, HIDDEN_PACKAGE_NOTE } from '@core/runtime/workflowCatalogue';
import {
  ARRIVAL_DISMISS,
  ARRIVAL_DISMISS_HINT,
  ARRIVAL_EMPTY_HINT,
  ARRIVAL_EMPTY_TITLE,
  ARRIVAL_NEW,
  ARRIVAL_SUBTITLE,
  ARRIVAL_TITLE,
  arrivalRecencyLine,
} from '@view/workflow/arrivalCopy';
import { Dialog } from './Dialog';
import './overlays.css';

interface ArrivalDialogProps {
  readonly choices: readonly ArrivalChoice[];
  /** What went wrong reaching the backend, when something did. */
  readonly error: string | null;
  readonly onOpen: (slug: string) => void;
  readonly onNew: () => void;
  readonly onClose: () => void;
}

/**
 * The project's workflows, offered on arrival — `install-experience` 28.
 *
 * ## It is the credentials dialog's container, not a second one
 *
 * The ticket asked for this by name and it is worth stating why rather than
 * only obeying: `Dialog` already owns Escape, a focus trap that wraps at both
 * ends, a backdrop that closes only on a press *and* release of its own, and a
 * body that scrolls inside a bounded panel. Four decisions with a reason each,
 * and a second copy of them is exactly the duplication this repository keeps
 * paying for. What is left here is a list.
 *
 * ## It opens nothing
 *
 * `install-experience` 23 removed a document that arrived on the canvas
 * because a tab happened to open. An offer is the opposite of an adoption —
 * but only while it stays one, so this component has no effect of any kind and
 * nothing in it can fire on mount. A workflow reaches the canvas because
 * somebody clicked its row.
 *
 * That is also the reason 27 is absorbed here rather than implemented as it
 * was filed. A mounted editor opening its host's workflow outright is right
 * exactly while the host is right; a list with that workflow at the top is
 * right either way, and it is the only one of the two that a reader can
 * disagree with.
 */
export function ArrivalDialog({ choices, error, onOpen, onNew, onClose }: ArrivalDialogProps) {
  // Read once per render rather than ticked: a list of ages that advanced
  // under the cursor while somebody read it would be worse than one that is a
  // few seconds old — the same call `WorkflowManager` makes about its drafts.
  const now = Date.now();

  return (
    <Dialog
      title={ARRIVAL_TITLE}
      subtitle={choices.length === 0 && error === null ? ARRIVAL_EMPTY_HINT : ARRIVAL_SUBTITLE}
      icon={FolderOpen}
      onClose={onClose}
      footer={
        <>
          <span className="arrival__hint">{ARRIVAL_DISMISS_HINT}</span>
          <Button onClick={onClose}>{ARRIVAL_DISMISS}</Button>
          <Button variant="primary" icon={<Icon glyph={Plus} size="sm" />} onClick={onNew}>
            {ARRIVAL_NEW}
          </Button>
        </>
      }
    >
      {/* A backend that cannot answer costs the list and nothing else: the
          canvas behind this is the blank one 23 settled on, and the buttons
          below still work. Said out loud rather than shown as an empty
          project, because "no workflows" and "could not ask" are two very
          different states and one appearance is how 27 was reported. */}
      {error !== null ? <p className="arrival__error">{error}</p> : null}

      {error === null && choices.length === 0 ? (
        <p className="arrival__empty">{ARRIVAL_EMPTY_TITLE}</p>
      ) : null}

      {choices.map((choice) => (
        <button
          key={choice.slug}
          type="button"
          className="arrival__row"
          onClick={() => onOpen(choice.slug)}
        >
          <span className="arrival__name">
            {choice.name}
            {/* The editor's own surface shows a package a customer channel
                does not advertise, and marks it — the decision
                `WorkflowSummary.hidden` records. Filtering it out here would
                make a directory on disk unreachable from the one screen whose
                job is to list what is on disk. The mark and its sentence are
                the shared constants: this is the third surface to print them,
                and a re-wording here would be a third answer to one rule. */}
            {choice.hidden ? (
              <Badge explanation={HIDDEN_PACKAGE_NOTE}>{HIDDEN_PACKAGE_MARK}</Badge>
            ) : null}
          </span>
          <span className="arrival__meta">
            <span className="arrival__where">{choice.location}</span>
            <span className="arrival__when">{arrivalRecencyLine(choice, now)}</span>
          </span>
        </button>
      ))}
    </Dialog>
  );
}
