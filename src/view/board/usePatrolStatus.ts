import { useEffect, useRef, useState } from 'react';
import {
  RuntimeClient,
  type PatrolStatus,
  type PatrolStreamEvent,
} from '@core/runtime/RuntimeClient';

/**
 * The live patrol status this app is subscribed to — kanban-patrol/07,
 * widened to a second reader by kanban-patrol/10.
 *
 * The React glue only: refetch on mount (`catalogue_events.py`'s own rule,
 * applied to the sibling stream — the registry is the source of truth, an
 * event is a hint to go and look) and a subscription for the rest, exactly
 * the shape `useWorkflowFileWatch.ts` already established for the catalogue
 * stream. The decision of what to *say* is `patrolStatusLine.ts`, on its
 * own and tested without a component.
 *
 * Mounted once, independent of whether the board is open — a patrol started
 * from one tab and finished while the board was closed is still true, and
 * `07`'s whole point is that the board must not have had to stay open to
 * know it.
 *
 * **It returns the status, not a sentence.** It did return
 * `patrolStatusLine(status)` while the board was the only reader; `10` added
 * the toolbar's job chip, which asks a different question of the same fact
 * (*is something running*, rather than *what happened*). Two callers, two
 * pure decision modules — `patrolStatusLine.ts` and
 * `topbar/patrolJobNotice.ts` — and **one** subscription, because a second
 * `EventSource` for one fact is a second thing that can disagree.
 */
export function usePatrolStatus(onCardsMayHaveChanged: () => void): PatrolStatus | null {
  const clientRef = useRef<RuntimeClient | null>(null);
  if (!clientRef.current) clientRef.current = new RuntimeClient();
  const [status, setStatus] = useState<PatrolStatus | null>(null);

  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;
    let cancelled = false;

    void client.patrolStatus().then((result) => {
      if (!cancelled && result.ok) setStatus(result.value);
    });

    const onEvent = (event: PatrolStreamEvent) => {
      switch (event.kind) {
        case 'started':
          setStatus({
            status: 'running',
            startedAt: '',
            finishedAt: '',
            error: '',
            filed: 0,
            skipped: 0,
            totalFindings: 0,
          });
          break;
        case 'progressed':
          // A card was filed. Not reflected in the status line itself —
          // `07` asks only that the board's data be correct, and the
          // correct answer is the store, refetched here rather than
          // guessed from the event's own fields.
          onCardsMayHaveChanged();
          break;
        case 'finished':
          setStatus({
            status: 'finished',
            startedAt: '',
            finishedAt: '',
            error: '',
            filed: event.filed,
            skipped: event.skipped,
            totalFindings: event.totalFindings,
          });
          onCardsMayHaveChanged();
          break;
        case 'failed':
          setStatus({
            status: 'failed',
            startedAt: '',
            finishedAt: '',
            error: event.reason,
            filed: 0,
            skipped: 0,
            totalFindings: 0,
          });
          break;
      }
    };
    const stop = client.watchPatrolEvents(onEvent);

    return () => {
      cancelled = true;
      stop();
    };
  }, [onCardsMayHaveChanged]);

  return status;
}
