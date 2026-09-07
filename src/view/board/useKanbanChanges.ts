import { useEffect, useRef } from 'react';
import { RuntimeClient } from '@core/runtime/RuntimeClient';

/**
 * The board's live card feed — `osg-agent-experience/36`.
 *
 * The defect the owner hit: a coding agent attends a card, reports red, then
 * green, then finished, and an open board shows yesterday until somebody
 * presses Refresh. Those writes come from other processes straight into
 * `kanban.sqlite`, so the server learns of them by watching the file, and this
 * is the connection that asks it to.
 *
 * **Subscribed only while `open`**, which is the whole point and not a
 * nicety: the backend polls the store only while at least one client holds
 * this stream, so a subscription that outlived the board would make the
 * server poll for the life of the tab. `usePatrolStatus` is deliberately the
 * opposite — mounted unconditionally, because a patrol that finished while
 * the board was closed is still true — and that difference is exactly why
 * these are two streams.
 *
 * **The frame is a hint, never a card.** Every change refetches through the
 * caller's own loader, so the store stays the one spelling of a row.
 */
export function useKanbanChanges(open: boolean, onCardsMayHaveChanged: () => void): void {
  const clientRef = useRef<RuntimeClient | null>(null);
  if (!clientRef.current) clientRef.current = new RuntimeClient();

  useEffect(() => {
    const client = clientRef.current;
    if (!open || !client) return;
    const stop = client.watchKanbanEvents(() => onCardsMayHaveChanged());
    return () => stop();
  }, [open, onCardsMayHaveChanged]);
}
