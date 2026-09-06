import { relativeTime } from '@core/runtime/pastRunView';
import type { CardKind, CardLifecycle } from './cardKind';
import type { CardStage } from './cardStage';
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
  //: `kanban-patrol/15`'s Answer — the decision, who made it, and when.
  //: Empty strings on every unanswered row, which is why the mapping below
  //: turns them into absent props rather than passing them through.
  readonly answer: string;
  readonly answered_by: string;
  readonly answered_at: string;
  //: `osg-agent-experience/25`. The brief an idea card carries; empty strings
  //: and an empty list on every patrol card, which is why the mapping below
  //: turns them into absent props rather than passing them through.
  readonly story: string;
  readonly done_when: string;
  readonly blocked_by: readonly string[];
  readonly agent_model: string;
  readonly agent_effort: string;
  //: `osg-agent-experience/85` — what the closing checks said, recorded at the
  //: `finished` transition. Empty on every card that has not reached it, and on
  //: a finished one whose actor passed no reason.
  readonly finished_reason: string;
  //: `team-board-and-gap-reports/17` — how many times this exact finding has
  //: been reported from this install. `1` on every card no door has counted
  //: on, never `0` or absent; turning a number true of every row into a
  //: label is the board's decision, and `kanbanCardMapping` makes it.
  readonly count: number;
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
    // Carried through rather than collapsed away — `kanban-patrol/19`. The
    // lifecycle above answers *which column*; the stage answers *how far*,
    // and until this line existed the second question had no answer past
    // this seam even though the row had always carried it.
    stage: row.stage as CardStage,
    // `kanban-patrol/15`. Absent, never `''` — the same rule `priorityReason`
    // follows above, and here it is load-bearing twice over: `columnForCard`
    // and `instructionForCard` both read this to decide whether a decision
    // exists at all.
    answer: row.answer || undefined,
    answeredBy: row.answered_by || undefined,
    // `osg-agent-experience/25`, and the same absent-not-empty rule as every
    // line above it. Load-bearing rather than tidy: the card guards on these
    // props, so `''` would draw an empty story element under the title of all
    // seven patrol cards.
    story: row.story || undefined,
    doneWhen: row.done_when || undefined,
    blockedBy: row.blocked_by?.length ? row.blocked_by : undefined,
    agentModel: row.agent_model || undefined,
    agentEffort: row.agent_effort || undefined,
    // `osg-agent-experience/85`. Absent, never `''`, the same rule every line
    // above follows — and load-bearing here too: the card guards on this prop,
    // so an empty string would draw a blank "finished:" line under every card
    // that never carried a gate.
    finishedReason: row.finished_reason || undefined,
    // `team-board-and-gap-reports/17`. The keyless door files one card per
    // finding per install and counts the repeats onto it; until this line
    // existed that number stopped at the database and the board drew a card
    // that could not tell one report from forty.
    //
    // Absent at one, the same absent-not-default rule every line above
    // follows — and here the default is a *number*, not an empty string, so
    // it is worth saying why it is not drawn: every card exists because
    // something was reported once, so "1" is true of every row on the board
    // and distinguishes none of them. A label true of everything makes the
    // counted card harder to find, not easier.
    count: (row.count ?? 1) > 1 ? row.count : undefined,
  };
}
