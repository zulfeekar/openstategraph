import { FolderOpen, Plus } from 'lucide-react';
import { Button, Icon } from '@design/primitives';
import type { ArrivalChoice } from '@core/runtime/arrivalChoices';
import {
  ARRIVAL_NEW,
  START_PANEL_NO_RECENT,
  START_PANEL_OPEN,
  START_PANEL_RECENT,
  START_PANEL_START,
  arrivalRecencyLine,
} from '@view/workflow/arrivalCopy';
import './StartPanel.css';

export interface StartPanelProps {
  readonly choices: readonly ArrivalChoice[];
  readonly busy: boolean;
  readonly onOpen: (slug: string) => void;
  readonly onNew: () => void;
  readonly onBrowse: () => void;
}

/**
 * The blank canvas, made useful instead of merely safe —
 * `install-experience` 28.
 *
 * `23` decided that arriving with no workflow named shows nothing, and it was
 * right about the *document*: adopting somebody else's draft was the defect.
 * It was never an argument for a bare grid. This is the state 23 protects,
 * carrying the two things every editor a developer already uses puts on it —
 * **Start**, and **Recent** with where each one lives.
 *
 * It sits **beside** the empty-canvas guidance rather than replacing it, and
 * the two answer different questions on purpose: `emptyStateCopy` says how to
 * *draw* a flow from parts, and this says how to *open* one that exists. A
 * project holding nothing therefore still reads as a lesson rather than as an
 * error.
 *
 * Every action is handed in. The rows are the same `ArrivalChoice` list the
 * arrival dialog offers, from the same fetch, opened through the same call —
 * see `useArrivalOffer`, which owns all three.
 */
export function StartPanel({ choices, busy, onOpen, onNew, onBrowse }: StartPanelProps) {
  // Read once per render rather than ticked: a column of ages that advanced
  // under the cursor while somebody read it would be worse than one that is a
  // few seconds old.
  const now = Date.now();

  return (
    <div className="start-panel">
      <section className="start-panel__section">
        <h2 className="start-panel__heading">{START_PANEL_START}</h2>
        <div className="start-panel__actions">
          <Button icon={<Icon glyph={Plus} size="sm" />} onClick={onNew} disabled={busy}>
            {ARRIVAL_NEW}
          </Button>
          <Button icon={<Icon glyph={FolderOpen} size="sm" />} onClick={onBrowse} disabled={busy}>
            {START_PANEL_OPEN}
          </Button>
        </div>
      </section>

      <section className="start-panel__section">
        <h2 className="start-panel__heading">{START_PANEL_RECENT}</h2>
        {choices.length === 0 ? (
          <p className="start-panel__none">{START_PANEL_NO_RECENT}</p>
        ) : (
          <ul className="start-panel__list">
            {choices.map((choice) => (
              <li key={choice.slug}>
                <button
                  type="button"
                  className="start-panel__row"
                  disabled={busy}
                  onClick={() => onOpen(choice.slug)}
                >
                  <span className="start-panel__name">{choice.name}</span>
                  <span className="start-panel__when">{arrivalRecencyLine(choice, now)}</span>
                  {/* Where it lives, under the name and across both columns:
                      the directory is the answer to "which one is this?" when
                      two packages carry the same display name, and it is what
                      a reader needs to find the files outside this editor. */}
                  <span className="start-panel__where">{choice.location}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
