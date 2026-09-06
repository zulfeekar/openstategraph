import { describe, expect, it } from 'vitest';
import { mapKanbanCardToBoardCard, type KanbanCardResponse } from './kanbanCardMapping';

/**
 * `kanban-patrol/19`. The API's row shape and the board's `BoardCard` shape
 * were designed separately — one by what a sqlite row can honestly hold, one
 * by what a card needs to show — and this is the one seam that translates
 * between them, so no other file re-derives the mapping and drifts.
 */

function row(overrides: Partial<KanbanCardResponse> = {}): KanbanCardResponse {
  return {
    task_id: 'proj-a:thread-1',
    board: 'workflows',
    kind: 'bug',
    category: 'bug',
    title: 'A tool call with no timeout',
    stage: 'unattended',
    actor: null,
    priority: 'high',
    area: 'backend',
    filed_at: new Date(Date.now() - 2 * 60_000).toISOString(),
    priority_reason: '',
    evidence_test_id: '',
    evidence_red_reason: '',
    evidence_green: false,
    evidence_commit: '',
    answer: '',
    answered_by: '',
    answered_at: '',
    story: '',
    done_when: '',
    blocked_by: [],
    agent_model: '',
    agent_effort: '',
    finished_reason: '',
    count: 1,
    stale: false,
    ...overrides,
  };
}

describe('the id, title, kind, priority and area pass straight through', () => {
  it('carries the fields that need no translation', () => {
    const card = mapKanbanCardToBoardCard(row(), Date.now());

    expect(card.id).toBe('proj-a:thread-1');
    expect(card.title).toBe('A tool call with no timeout');
    expect(card.kind).toBe('bug');
    expect(card.priority).toBe('high');
    expect(card.area).toBe('backend');
  });
});

describe('stage collapses onto lifecycle', () => {
  it('unattended is open', () => {
    expect(mapKanbanCardToBoardCard(row({ stage: 'unattended' }), Date.now()).lifecycle).toBe(
      'open',
    );
  });

  it.each(['attended', 'red', 'green'])('stage %s is claimed', (stage) => {
    expect(mapKanbanCardToBoardCard(row({ stage }), Date.now()).lifecycle).toBe('claimed');
  });

  it('finished is resolved — kanban-patrol/17+21: the backend refuses this transition without a recorded test id, red reason and green', () => {
    expect(
      mapKanbanCardToBoardCard(
        row({
          stage: 'finished',
          evidence_test_id: 'tests/test_x.py::test_y',
          evidence_red_reason: 'AssertionError: no timeout set',
          evidence_green: true,
        }),
        Date.now(),
      ).lifecycle,
    ).toBe('resolved');
  });
});

describe('a resolved card carries its evidence; nothing else does', () => {
  it('passes the test id and red reason through when the card is resolved', () => {
    const card = mapKanbanCardToBoardCard(
      row({
        stage: 'finished',
        evidence_test_id: 'tests/test_x.py::test_y',
        evidence_red_reason: 'AssertionError: no timeout set',
        evidence_green: true,
      }),
      Date.now(),
    );

    expect(card.evidenceTestId).toBe('tests/test_x.py::test_y');
    expect(card.evidenceRedReason).toBe('AssertionError: no timeout set');
  });

  it('omits the evidence fields (undefined, not empty strings) on a card that is not resolved yet, even if the row already has evidence written', () => {
    const card = mapKanbanCardToBoardCard(
      row({
        stage: 'red',
        evidence_test_id: 'tests/test_x.py::test_y',
        evidence_red_reason: 'AssertionError: no timeout set',
      }),
      Date.now(),
    );

    expect(card.evidenceTestId).toBeUndefined();
    expect(card.evidenceRedReason).toBeUndefined();
  });

  it('omits the evidence fields on an unattended card with nothing recorded', () => {
    const card = mapKanbanCardToBoardCard(row({ stage: 'unattended' }), Date.now());

    expect(card.evidenceTestId).toBeUndefined();
    expect(card.evidenceRedReason).toBeUndefined();
  });
});

describe('priority carries its own per-card reason, never a generic one', () => {
  it("passes the classifier's reason through unchanged", () => {
    const card = mapKanbanCardToBoardCard(
      row({ priority_reason: 'Asked the same question 4 times in one thread.' }),
      Date.now(),
    );

    expect(card.priorityReason).toBe('Asked the same question 4 times in one thread.');
  });

  it('an empty reason maps to undefined, never an empty string a Tooltip would render blank', () => {
    const card = mapKanbanCardToBoardCard(row({ priority_reason: '' }), Date.now());

    expect(card.priorityReason).toBeUndefined();
  });
});

describe('the absolute date, alongside the relative phrase', () => {
  it("renders month, day and year — WorkflowManager.tsx's own convention, toLocaleDateString", () => {
    const card = mapKanbanCardToBoardCard(
      row({ filed_at: '2026-09-01T16:00:00Z' }),
      Date.parse('2026-09-01T16:02:00Z'),
    );

    expect(card.filedOn).toBe(new Date('2026-09-01T16:00:00Z').toLocaleDateString());
  });
});

describe('secondary reuses the shared relative-time formatter, never a second one', () => {
  it('renders a real elapsed phrase from filed_at, not a fabricated one', () => {
    const card = mapKanbanCardToBoardCard(row(), Date.now());

    expect(card.when).toBe('2 min ago');
  });

  it('names the category in the second line — the one thing the row has that a fixture guessed at', () => {
    const card = mapKanbanCardToBoardCard(row({ category: 'scalability' }), Date.now());

    expect(card.secondary).toContain('scalability');
  });
});

describe('stale passes through present-and-true only — kanban-patrol/19', () => {
  it('a stale row maps to stale: true', () => {
    const card = mapKanbanCardToBoardCard(row({ stale: true }), Date.now());

    expect(card.stale).toBe(true);
  });

  it('a not-stale row maps to stale: undefined, never false', () => {
    const card = mapKanbanCardToBoardCard(row({ stale: false }), Date.now());

    expect(card.stale).toBeUndefined();
  });
});

describe('the decision — `kanban-patrol/15` — crosses the seam or is absent', () => {
  it('carries an answer and who made it', () => {
    const card = mapKanbanCardToBoardCard(
      row({ kind: 'decision', answer: 'Use the cloud one.', answered_by: 'zulfeekar' }),
      Date.now(),
    );

    expect(card.answer).toBe('Use the cloud one.');
    expect(card.answeredBy).toBe('zulfeekar');
  });

  it('leaves both props absent — not empty — on an unanswered card', () => {
    // `columnForCard` and `instructionForCard` both ask "is there a decision"
    // by reading this, so "no answer" has to be the prop being absent, the
    // same rule `priorityReason` follows one field up.
    const card = mapKanbanCardToBoardCard(row({ kind: 'decision' }), Date.now());

    expect(card.answer).toBeUndefined();
    expect(card.answeredBy).toBeUndefined();
  });
});

/**
 * `osg-agent-experience/25`. The brief an idea card carries. Absent, never
 * empty — the same rule `priorityReason` follows above, and load-bearing for
 * the same reason: a card renders these only when they are actually there,
 * and `''` would draw an empty line under every patrol card on the board.
 */
describe('an idea card brings its brief across', () => {
  it('carries the story, the done-when and the model and effort', () => {
    const card = mapKanbanCardToBoardCard(
      row({
        story: 'A weekly planner wants a first agenda without typing one.',
        done_when: 'A run answers with five numbered items.',
        agent_model: 'opus',
        agent_effort: 'high',
      }),
      Date.now(),
    );

    expect(card.story).toBe('A weekly planner wants a first agenda without typing one.');
    expect(card.doneWhen).toBe('A run answers with five numbered items.');
    expect(card.agentModel).toBe('opus');
    expect(card.agentEffort).toBe('high');
  });

  it('carries the ids this card waits on', () => {
    expect(
      mapKanbanCardToBoardCard(row({ blocked_by: ['proj-a:idea-other'] }), Date.now()).blockedBy,
    ).toEqual(['proj-a:idea-other']);
  });

  it('leaves every one of them absent on a patrol row, never an empty string', () => {
    const card = mapKanbanCardToBoardCard(row(), Date.now());

    expect(card.story).toBeUndefined();
    expect(card.doneWhen).toBeUndefined();
    expect(card.agentModel).toBeUndefined();
    expect(card.agentEffort).toBeUndefined();
    expect(card.blockedBy).toBeUndefined();
  });
});

describe('the closing gate reaches the card body — osg-agent-experience/85', () => {
  it('carries what the finished transition recorded', () => {
    const card = mapKanbanCardToBoardCard(
      row({ stage: 'finished', finished_reason: 'validate: no findings; one exit' }),
      Date.now(),
    );

    expect(card.finishedReason).toBe('validate: no findings; one exit');
  });

  it('is absent, never an empty string, on a card that never carried one', () => {
    // The same absent-not-empty rule every other optional prop here follows:
    // `PatrolCard` guards on this, so `''` would draw a blank "finished:" line
    // under every card on the board.
    expect(mapKanbanCardToBoardCard(row(), Date.now()).finishedReason).toBeUndefined();
  });
});
