import { describe, expect, it } from 'vitest';
import { BOARD_COLUMNS } from './patrolBoardModel';
import { CARD_KINDS, columnForCard } from './cardKind';
import {
  CARD_STAGES,
  IN_PROGRESS_STAGE_COPY,
  statusTextForCard,
  type CardStage,
} from './cardStage';
import { mapKanbanCardToBoardCard, type KanbanCardResponse } from './kanbanCardMapping';

/**
 * `kanban-patrol/19`'s last unbuilt clause: *"the stage text table above on an
 * In Progress card"*. Every claimed card said **In Progress** — the column's
 * own label — so a card taken thirty seconds ago and a card whose test is
 * already passing read the same, and the stage the store had been recording
 * all along reached no reader.
 *
 * | stage | card text |
 * | --- | --- |
 * | `attended` | Queued |
 * | `red` | In progress — test written |
 * | `green` | In progress — test passing |
 * | `finished` | Awaiting review |
 */

const label = (id: string) => BOARD_COLUMNS.find((column) => column.id === id)!.label;

describe('an In Progress card says which stage it is at', () => {
  it('shows the stage sentence, never the column label, for every claimed stage', () => {
    for (const stage of CARD_STAGES.filter((s) => s !== 'unattended')) {
      const card = { kind: 'bug', lifecycle: 'claimed', stage } as const;
      expect(columnForCard(card)).toBe('inProgress');
      const text = statusTextForCard(card, label('inProgress'));
      expect(text, stage).toBe(IN_PROGRESS_STAGE_COPY[stage as Exclude<CardStage, 'unattended'>]);
      expect(text, stage).not.toBe('In Progress');
    }
  });

  it('says the exact four sentences the ticket settled', () => {
    expect(IN_PROGRESS_STAGE_COPY).toEqual({
      attended: 'Queued',
      red: 'In progress — test written',
      green: 'In progress — test passing',
      finished: 'Awaiting review',
    });
  });

  it('leaves Detected and Needs You reading their column, whatever stage says', () => {
    // The stage table is In Progress's alone. An open card's stage is
    // `unattended` by definition, and a row that somehow carries another one
    // must not relabel a column it is not in.
    for (const kind of CARD_KINDS) {
      for (const stage of CARD_STAGES) {
        const card = { kind, lifecycle: 'open', stage } as const;
        const column = columnForCard(card);
        expect(statusTextForCard(card, label(column)), `${kind}/${stage}`).toBe(label(column));
      }
    }
  });

  it('leaves a Resolved card reading Resolved — evidence closed it, not a claim', () => {
    for (const stage of CARD_STAGES) {
      const card = { kind: 'bug', lifecycle: 'resolved', stage } as const;
      expect(statusTextForCard(card, label('resolved')), stage).toBe('Resolved');
    }
  });

  it('falls back to the column label when the row carries no stage at all', () => {
    // A fixture card, or a row from an API that predates the field. A missing
    // stage is a missing sentence, never a blank status line.
    expect(statusTextForCard({ kind: 'bug', lifecycle: 'claimed' }, 'In Progress')).toBe(
      'In Progress',
    );
  });

  it('carries the stage off the wire onto the card, which is where it was dropped', () => {
    const row: KanbanCardResponse = {
      task_id: 'p:t',
      board: 'patrol',
      kind: 'bug',
      category: 'answer',
      title: 'A tool call with no timeout',
      stage: 'red',
      actor: 'agent',
      priority: 'high',
      area: 'backend',
      priority_reason: '',
      filed_at: new Date().toISOString(),
      evidence_test_id: '',
      evidence_red_reason: '',
      evidence_green: false,
      evidence_commit: '',
      answer: '',
      answered_by: '',
      answered_at: '',
      stale: false,
    };
    const card = mapKanbanCardToBoardCard(row, Date.now());
    expect(card.stage).toBe('red');
    expect(statusTextForCard(card, label('inProgress'))).toBe('In progress — test written');
  });
});
