import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { mapKanbanCardToBoardCard, type KanbanCardResponse } from './kanbanCardMapping';

/**
 * `team-board-and-gap-reports/17`. The keyless door files one card per
 * finding per install and counts the repeats onto it — `0003`'s `on conflict
 * ... do update set count = card.count + 1`, and the routine's own outcome
 * word for the second one is `counted`. Until this ticket that number reached
 * the database and stopped there: the board drew a card that said a gap had
 * been reported, with no way to tell one report from forty.
 *
 * ## The absent half is the asserted half
 *
 * A count of one is not a fact about a card — every card exists because
 * something was reported once, which is why the column defaults to `1` and
 * not `0`. Drawing "×1" on every row would be a number that is true, adds
 * nothing, and makes the counted card harder to spot rather than easier. So
 * the mapping follows the same absent-not-default rule every field beside it
 * follows (`priorityReason`, `stale`, `finishedReason`): present when it says
 * something, absent when it does not.
 *
 * ## Why the card half reads the source
 *
 * `anIdeaCardCarriesItsBrief.test.ts`'s reason, unchanged: whether the number
 * is drawn *conditionally* is the load-bearing half, and a card rendering
 * `{card.count}` unguarded would satisfy a "the number appears" mount while
 * printing a bare `1` on all seven patrol cards.
 */

const REPO = new URL('../../../', import.meta.url);
const read = (path: string) => readFileSync(fileURLToPath(new URL(path, REPO)), 'utf8');

const card = read('src/view/board/PatrolCard.tsx');
const styles = read('src/view/board/PatrolBoard.css');

function row(overrides: Partial<KanbanCardResponse> = {}): KanbanCardResponse {
  return {
    task_id: 'gap-reports:0123456789ab-abcdef012345',
    board: 'osgEngineering',
    kind: 'task',
    category: 'gap',
    title: 'No backend implementation for tool.acme-ping',
    stage: 'unattended',
    actor: null,
    priority: 'med',
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

describe('the count crosses the seam', () => {
  it('carries how many installs hit this gap', () => {
    expect(mapKanbanCardToBoardCard(row({ count: 12 }), Date.now()).count).toBe(12);
  });

  it('leaves a card reported once with no count at all', () => {
    expect(mapKanbanCardToBoardCard(row({ count: 1 }), Date.now()).count).toBeUndefined();
  });

  it('survives a row from a store that has never been counted on', () => {
    // A board answered by an older backend, or a card filed by any other
    // route: the field is absent rather than a number, and a card is not a
    // place to invent one.
    const older = row();
    delete (older as { count?: number }).count;
    expect(mapKanbanCardToBoardCard(older, Date.now()).count).toBeUndefined();
  });
});

describe('the card draws it', () => {
  it('renders the count', () => {
    expect(card).toMatch(/\{card\.count\}/);
  });

  it('draws it only when the card has one', () => {
    expect(card, 'the count is rendered unconditionally').toMatch(/card\.count\s*\?/);
  });

  it('names the element it draws it into, so the stylesheet can find it', () => {
    expect(card).toContain('patrol-card__count');
    expect(styles).toContain('.patrol-card__count');
  });

  it('paints it in tokens, minting no colour of its own', () => {
    const rule = /\.patrol-card__count\s*\{([^}]*)\}/.exec(styles)?.[1] ?? '';
    expect(rule).not.toBe('');
    expect(rule).not.toMatch(/#[0-9a-f]{3}/i);
    expect(rule).toMatch(/var\(--/);
  });
});
