import { Badge } from '@design/primitives';
import type { PatrolStatus } from '@core/runtime/RuntimeClient';
import { patrolJobNotice } from './patrolJobNotice';

/**
 * The named background job the user can see is running — `kanban-patrol/10`.
 *
 * Beside `RuntimeHealthDot` and `EditorFreshnessChip` in the brand group,
 * matching the precedent rather than inventing next to it: all three render
 * **nothing** when there is nothing to say.
 *
 * **It subscribes to nothing.** The status arrives as a prop from `AppShell`,
 * which already mounts `usePatrolStatus` unconditionally for the board — so
 * the board and this chip are one SSE connection reporting one fact, not two
 * streams that can disagree about whether a patrol is running.
 *
 * What each status renders, and why `failed` clears it too, is
 * `patrolJobNotice.ts` — decided and tested without a component, the split this
 * folder already draws for `staleEditorNotice` and `runIntent`.
 */
export function PatrolJobChip({ status }: { status: PatrolStatus | null }) {
  const notice = patrolJobNotice(status);
  if (notice === null) return null;
  return (
    <Badge tone="accent" explanation={notice.hint}>
      {notice.label}
    </Badge>
  );
}
