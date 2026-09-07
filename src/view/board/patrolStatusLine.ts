import type { PatrolStatus } from '@core/runtime/RuntimeClient';

/**
 * The one honest sentence the board shows about the patrol — kanban-patrol/07.
 *
 * `07` asks for *something honest*, not a progress bar: "even a minimal text
 * line ... is enough for this ticket". This function is that line, pure and
 * on its own so it is testable without a component, a stream, or a clock —
 * the same split `workflowFileWatch.ts` already draws between a decision and
 * the effects that feed it.
 *
 * `null` is itself an answer: "idle" (nothing has run since this app opened,
 * or this app has not yet asked) prints nothing, because a board that always
 * shows a patrol line would make silence itself a claim ("nothing is
 * happening") the moment nobody has looked. `07` and `catalogue_events.py`'s
 * own SSE stream agree on this: an event, or its absence, is a hint — the
 * job registry is the source of truth, and idle is not news.
 */
export function patrolStatusLine(status: PatrolStatus | null): string | null {
  if (!status) return null;
  switch (status.status) {
    case 'running':
      return 'Patrol running…';
    case 'failed':
      // `07`'s own words: "a patrol that dies silently is worse than one
      // that never started" — the reason is shown, not softened.
      return `Patrol failed: ${status.error || 'unknown reason'}`;
    case 'finished':
      return status.filed > 0
        ? `Patrol finished — filed ${status.filed} new card(s).`
        : 'Patrol finished — nothing new to file.';
    case 'idle':
      return null;
  }
}
