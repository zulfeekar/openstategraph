import { useState } from 'react';
import { PlugZap, Radar } from 'lucide-react';
import { Button, Icon, PanelEmpty, Tabs } from '@design/primitives';
import { Dialog } from '@view/overlays/Dialog';
import { PatrolColumn } from './PatrolColumn';
import { BOARD_TABS, boardTabState, type BoardTabId } from './boardTabs';
import { BOARD_COLUMNS, type BoardCard } from './patrolBoardModel';
import {
  BOARD_EMPTY_BODY,
  BOARD_EMPTY_TITLE,
  BOARD_PATROL_ACTION,
  BOARD_SUBTITLE,
  BOARD_TITLE,
} from './boardCopy';
import { PATROL_BOARD_FIXTURE } from './patrolBoardFixture';
import './PatrolBoard.css';

export interface PatrolBoardProps {
  /**
   * The cards to draw. Defaults to the fixture, because the real schema is
   * `kanban-patrol/02` and this ticket does not wait on it.
   */
  readonly cards?: readonly BoardCard[];
  /**
   * Start a patrol. A callback the caller owns: running one for real is
   * `kanban-patrol/07`, and a view that faked it would be worse than a view
   * that cannot.
   */
  readonly onPatrol: () => void;
  readonly onClose: () => void;
  /**
   * A card's gesture. Optional, because a board with no handler is still a
   * legible board — the controls simply do not render, which is honest rather
   * than a button that does nothing.
   */
  readonly onAct?: (card: BoardCard, action: 'attend' | 'answer') => void;
  /**
   * `kanban-patrol/19`'s explicit Release. Same optional-handler rule as
   * `onAct`: a board with no handler simply renders no Release button.
   */
  readonly onRelease?: (card: BoardCard) => void;
  /**
   * Re-read the store. Deliberately **not** live yet — `19` rides `07`'s SSE
   * fan-out for a push, which does not exist; this is the honest interim,
   * a caller re-fetching on request rather than the board silently going
   * stale between opens. Optional, same rule as `onAct`: no handler, no
   * button, rather than one that does nothing.
   */
  readonly onRefresh?: () => void;
  /**
   * The one honest sentence about the patrol's live state — kanban-patrol
   * /07. `null` (the default) means idle or not yet known, and renders
   * nothing: `patrolStatusLine.ts` decides the words, this only shows
   * whatever it decided. A minimal line rather than a progress bar, per
   * `07`'s own instruction — this ticket's bar is "correct and honest", not
   * "polished".
   */
  readonly statusLine?: string | null;
}

/**
 * The patrol board — `kanban-patrol/06`.
 *
 * ## What this component is, after the split
 *
 * The **shell**: which tab is showing, and which of the three things goes in
 * the body — an unavailable notice, the blank-board offer, or the columns. It
 * draws no column and no card. Both of those are components beside it, because
 * this function was doing six jobs and a card is about to grow an action.
 *
 * ## It is the shared `Dialog`, one size larger
 *
 * Not a modal of its own. `Dialog` owns Escape, a focus trap that wraps at
 * both ends, and a backdrop that closes only on a press *and* release of its
 * own — three decisions with a reason each, which a one-off large panel would
 * have to re-earn. What this ticket added there is a `size` prop and a rule in
 * `overlays.css`; the modals that were here first pass no size and did not
 * move, which `aDialogSizeIsOptInOnly.test.ts` fails on.
 */
export function PatrolBoard({
  cards = PATROL_BOARD_FIXTURE,
  onPatrol,
  onClose,
  onAct,
  onRelease,
  onRefresh,
  statusLine = null,
}: PatrolBoardProps) {
  const [tab, setTab] = useState<BoardTabId>('workflows');
  const state = boardTabState(tab);

  const patrolButton = (
    <Button variant="primary" icon={<Icon glyph={Radar} size="sm" />} onClick={onPatrol}>
      {BOARD_PATROL_ACTION}
    </Button>
  );
  const footer = onRefresh ? (
    <>
      <Button variant="secondary" onClick={onRefresh}>
        Refresh
      </Button>
      {patrolButton}
    </>
  ) : (
    patrolButton
  );

  return (
    <Dialog
      title={BOARD_TITLE}
      subtitle={BOARD_SUBTITLE}
      icon={Radar}
      size="large"
      onClose={onClose}
      footer={footer}
    >
      <Tabs tabs={BOARD_TABS} active={tab} onChange={setTab} />

      {statusLine ? <p className="patrol-board__status">{statusLine}</p> : null}

      {state.kind === 'unavailable' ? (
        <PanelEmpty glyph={PlugZap} title={state.title} body={state.body} />
      ) : cards.length === 0 ? (
        /* The blank board says what blank means and offers the one action
           that changes it — `.canvas-empty`'s bargain, one surface along.
           Instead of the columns rather than above them: four headers
           reading `0` over the sentence "no patrol has run" is the same
           contradiction the unbuilt tabs avoid. */
        <div className="patrol-board__empty">
          <PanelEmpty glyph={Radar} title={BOARD_EMPTY_TITLE} body={BOARD_EMPTY_BODY} />
          {patrolButton}
        </div>
      ) : (
        <div className="patrol-board">
          {BOARD_COLUMNS.map((column) => (
            <PatrolColumn
              key={column.id}
              column={column}
              cards={cards}
              onAct={onAct}
              onRelease={onRelease}
            />
          ))}
        </div>
      )}
    </Dialog>
  );
}
