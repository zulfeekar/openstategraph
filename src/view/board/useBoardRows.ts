import { useCallback, useEffect, useState } from 'react';
import { RuntimeClient } from '@core/runtime/RuntimeClient';
import type { BoardCard } from './patrolBoardModel';
import type { BoardConfig, BoardTabId } from './boardTabs';
import { mapKanbanCardToBoardCard } from './kanbanCardMapping';
import { useKanbanChanges } from './useKanbanChanges';
import { useBoardConfig } from './useBoardConfig';

/** Everything the board dialog needs to draw rows, and nothing else. */
export interface BoardRows {
  /**
   * `null` until the first read returns, so the board can tell *hasn't asked
   * yet* from *asked, found nothing* — the three-state honesty
   * `kanban-patrol/19` already applies to a card's own absent fields.
   */
  readonly cards: readonly BoardCard[] | null;
  /** What the environment says the tabs have behind them; `null` unanswered. */
  readonly config: BoardConfig | null;
  /** Re-read the current board — the manual Refresh, and every live hint. */
  readonly refresh: () => void;
  /** Show a different board's rows. Called when the view switches tab. */
  readonly showBoard: (board: BoardTabId) => void;
}

/**
 * The board's data feed — extracted from `AppShell` by
 * `team-board-and-gap-reports/04`.
 *
 * It came out because the shell crossed the module ceiling and the census
 * asked the question it exists to ask: *is this one more line of the shell's
 * one job, or a second reason to change?* It is a second reason. Which rows
 * the board is showing, when they are re-read and which board they are of
 * moves for board reasons; the shell moves for shell reasons; and the four
 * pieces below were already only ever read together.
 *
 * ## What it does, in the order it does it
 *
 * - **Reads on open**, never before: `patrolBoardOpen` gates every effect
 *   here, so a tab that never opens the board makes no request and holds no
 *   subscription. That is `kanban_events.py`'s cost rule at the other end of
 *   the wire.
 * - **Live from there on** (`osg-agent-experience/36`). An agent attending a
 *   card is another process writing the store, so the rows go stale the
 *   moment the board opens; `useKanbanChanges` subscribes for exactly as long
 *   as the board is on screen and refetches through this same loader. The
 *   frame is a hint — one spelling of a card, and it is the store's.
 * - **One board at a time** (`team-board-and-gap-reports/04`). The owner's
 *   decision is one table with a `board` column, so switching tab is a
 *   refetch with a different discriminator: no second client, no second
 *   stream, no second cache to disagree with the first. The old rows are
 *   dropped on the switch rather than shown for a beat, because rows of the
 *   board you just left are a claim about a store nobody read.
 *
 * A hook rather than a component, because `AppShell` owns the dialog and
 * `PatrolBoard` must contain no `fetch(` — the layering rule
 * `aTabThatIsNotBuiltSaysSo.test.ts` asserts.
 */
export function useBoardRows(open: boolean): BoardRows {
  const [cards, setCards] = useState<readonly BoardCard[] | null>(null);
  const [board, setBoard] = useState<BoardTabId>('workflows');
  const config = useBoardConfig(open);

  const refresh = useCallback(() => {
    const client = new RuntimeClient();
    void client.kanbanCards(board).then((result) => {
      if (!result.ok) return; // stays whatever it last was — an unreachable
      // backend is not evidence the board is empty.
      setCards(result.value.map((row) => mapKanbanCardToBoardCard(row, Date.now())));
    });
  }, [board]);

  useEffect(() => {
    if (open) refresh();
  }, [open, refresh]);
  useKanbanChanges(open, refresh);

  const showBoard = useCallback((next: BoardTabId) => {
    setCards(null);
    setBoard(next);
  }, []);

  return { cards, config, refresh, showBoard };
}
