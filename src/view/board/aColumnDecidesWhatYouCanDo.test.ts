import { describe, expect, it } from 'vitest';
import { BOARD_COLUMNS } from './patrolBoardModel';
import { CARD_KINDS, columnForCard } from './cardKind';
import { ACTION_COPY, CARD_ACTIONS, actionForCard } from './cardAction';

/**
 * `kanban-patrol/15`. The four columns are not four states of one interaction
 * — they are four different affordances, and two of them are deliberately
 * none.
 *
 * | Column | Affordance | Why |
 * | --- | --- | --- |
 * | Detected | **Attend** | the patrol is confident; it needs doing |
 * | Needs You | **Answer** | the patrol stopped on a judgement |
 * | In Progress | *none* | somebody is on it |
 * | Resolved | *none* | closed, with its evidence |
 *
 * **In Progress having no action is the load-bearing one.** It is the board's
 * only defence against two actors working one card, and it is why `16`'s
 * claim has to be atomic rather than advisory.
 */

/** Every card shape the board can hold, so a rule is asserted over all of them. */
const EVERY_CARD = CARD_KINDS.flatMap((kind) =>
  (['open', 'claimed', 'resolved'] as const).map((lifecycle) => ({ kind, lifecycle })),
);

describe('what a card lets you do depends on the column it is in', () => {
  it('offers exactly one action per column, or none, and never invents a third', () => {
    for (const card of EVERY_CARD) {
      const action = actionForCard(card);
      if (action !== null) {
        expect(CARD_ACTIONS, `${card.kind}/${card.lifecycle}`).toContain(action);
      }
    }
  });

  it('offers Attend on Detected and nothing else there', () => {
    for (const card of EVERY_CARD.filter((c) => columnForCard(c) === 'detected')) {
      expect(actionForCard(card), `${card.kind}/${card.lifecycle}`).toBe('attend');
    }
  });

  it('offers Answer on Needs You, because the question is the card', () => {
    for (const card of EVERY_CARD.filter((c) => columnForCard(c) === 'needsYou')) {
      expect(actionForCard(card), `${card.kind}/${card.lifecycle}`).toBe('answer');
    }
  });

  it('offers nothing at all on In Progress — a second actor is how work gets done twice', () => {
    const claimed = EVERY_CARD.filter((c) => columnForCard(c) === 'inProgress');
    expect(claimed.length).toBeGreaterThan(0);
    for (const card of claimed) {
      expect(actionForCard(card), `${card.kind}/${card.lifecycle}`).toBeNull();
    }
  });

  it('offers nothing on Resolved — it is closed, and reopening is not this control', () => {
    const done = EVERY_CARD.filter((c) => columnForCard(c) === 'resolved');
    expect(done.length).toBeGreaterThan(0);
    for (const card of done) {
      expect(actionForCard(card)).toBeNull();
    }
  });

  it('never offers an agent-takeable action on a judgement', () => {
    // The structural half of `18`'s rule, one layer up: `attend` is the
    // gesture that hands work to an agent, so it must be unreachable on any
    // card whose kind is a judgement, in every lifecycle.
    for (const card of EVERY_CARD) {
      if (columnForCard(card) === 'needsYou') {
        expect(actionForCard(card)).not.toBe('attend');
      }
    }
  });

  it('decides an action for every column the board draws', () => {
    // A fifth column added to `BOARD_COLUMNS` without a decision here would
    // render cards with a silently absent affordance. This fails instead.
    const decided = new Set(EVERY_CARD.map((card) => columnForCard(card)));
    for (const column of BOARD_COLUMNS) {
      expect(decided, `${column.id} has cards that can reach it`).toContain(column.id);
    }
  });
});

describe('an action names itself the same way everywhere', () => {
  it('carries a label and a hint for each action, from one place', () => {
    // Two spellings of one verb agree the day they are written and drift on
    // the first reword — the rule `Badge`'s explanation already follows.
    for (const action of CARD_ACTIONS) {
      expect(ACTION_COPY[action].label.length).toBeGreaterThan(0);
      expect(ACTION_COPY[action].hint.length).toBeGreaterThan(0);
    }
  });
});
