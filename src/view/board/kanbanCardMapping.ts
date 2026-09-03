import { relativeTime } from '@core/runtime/pastRunView';
import type { CardKind, CardLifecycle } from './cardKind';
import type { BoardArea, BoardPriority } from './cardPriority';
import type { BoardCard } from './patrolBoardModel';

/**
 * `GET /api/kanban/cards`'s row shape — `kanban-patrol/19` — kept as its own
 * type so a schema change on the wire shows up here as a type error rather
 * than a silent `any` threaded through the board.
 */
export interface KanbanCardResponse {
  readonly task_id: string;
  readonly board: string;
  readonly kind: string;
  readonly category: string;
  readonly title: string;
  readonly stage: string;
  readonly actor: string | null;
  readonly priority: string;
  readonly area: string;
  readonly priority_reason: string;
  readonly filed_at: string;
  readonly evidence_test_id: string;
  readonly evidence_red_reason: string;
  readonly evidence_green: boolean;
  readonly evidence_commit: string;
  //: `kanban-patrol/19`'s explicit Release — whether this card's claim has
  //: gone past the hour-long lease with no heartbeat. Absent-vs-`false`
  //: does not apply here — every row carries this field always, unlike
  //: `priority_reason`'s "empty when the classifier gave none".
  readonly stale: boolean;
}

/**
 * Stage collapses onto lifecycle. `finished` maps to `'resolved'` —
 * `kanban-patrol/17`+`21`'s evidence gate is what makes this trustworthy:
 * the backend now refuses a `finished` transition unless a test id, a red
 * reason and a recorded green already sit on the row, so a card that
 * reaches `finished` carries real proof, not an actor's unverified word.
 * Before this gate existed, `finished` collapsed onto `'claimed'` instead —
 * the only honest reading of a claim with nothing behind it.
 */
function lifecycleForStage(stage: string): CardLifecycle {
  if (stage === 'unattended') return 'open';
  if (stage === 'finished') return 'resolved';
  return 'claimed';
}

/**
 * The one seam translating a sqlite row into what the board draws —
 * `kanban-patrol/19`. Kept separate from `patrolBoardModel` because the two
 * shapes were designed against different constraints (what a row can
 * honestly hold, versus what a card needs to show) and a mapping that lived
 * inside either would read as that file's own concern instead of the seam
 * between two independently-owned shapes.
 */
export function mapKanbanCardToBoardCard(row: KanbanCardResponse, now: number): BoardCard {
  const lifecycle = lifecycleForStage(row.stage);
  return {
    id: row.task_id,
    title: row.title,
    secondary: `${row.board} · ${row.category}`,
    kind: row.kind as CardKind,
    lifecycle,
    when: relativeTime(row.filed_at, now),
    // `toLocaleDateString()` — the same call `WorkflowManager.tsx` already
    // uses for a saved-date column, not a second date convention invented
    // here.
    filedOn: new Date(row.filed_at).toLocaleDateString(),
    priority: row.priority as BoardPriority,
    area: row.area as BoardArea,
    // `undefined`, never `''` — a `Tooltip` given an empty string still
    // renders (a blank hover target), so "no reason" has to mean "the prop
    // is absent", the same absent-vs-empty rule this whole feature already
    // applies to `sessionId`/`seconds` upstream.
    priorityReason: row.priority_reason || undefined,
    // Only when resolved — a card mid-flight (`red`/`green`) already has
    // `evidence_test_id` on the row, but showing it before the gate has
    // actually accepted `finished` would be the same premature claim this
    // whole feature exists to refuse.
    evidenceTestId: lifecycle === 'resolved' ? row.evidence_test_id || undefined : undefined,
    evidenceRedReason: lifecycle === 'resolved' ? row.evidence_red_reason || undefined : undefined,
    // Present-and-true only, same absent-not-false rule `priorityReason`
    // follows above — `kanban-patrol/19`: a card that is not stale renders
    // no label and no Release button, rather than a prop that is `false`
    // on every unclaimed and every fresh card alike.
    stale: row.stale ? true : undefined,
  };
}
