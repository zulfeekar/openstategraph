import { describe, expect, it } from 'vitest';
import { BOARD_COLUMNS } from './patrolBoardModel';
import { CARD_KINDS, columnForCard } from './cardKind';
import {
  ACTION_COPY,
  CARD_ACTIONS,
  actionForCard,
  isAnswerSubmittable,
  offersRelease,
} from './cardAction';

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

describe('Release is an affordance too, and the column decides it as well', () => {
  /**
   * `kanban-patrol/32`. The rule above — *Resolved offers nothing* — was
   * green the whole time a Resolved card drew a **Release** button, because
   * `stale` was rendered outside `actionForCard`'s vocabulary: a second
   * affordance the column never got to decide. Release is the only control
   * on this board that destroys data (it empties all four evidence fields),
   * so it is the last one that may sit outside the rule.
   *
   * The store is the fact and is fixed there — a `finished` card is never
   * flagged. This is the second line, and it is cheap: the board must not
   * offer the button even if a row arrives claiming `stale: true`.
   */
  it('never offers Release on Resolved, even on a row the API called stale', () => {
    const done = EVERY_CARD.filter((c) => columnForCard(c) === 'resolved');
    expect(done.length).toBeGreaterThan(0);
    for (const card of done) {
      expect(offersRelease({ ...card, stale: true }), `${card.kind}/${card.lifecycle}`).toBe(false);
    }
  });

  it('still offers Release on an abandoned claim, which is what it is for', () => {
    const claimed = EVERY_CARD.filter((c) => columnForCard(c) === 'inProgress');
    expect(claimed.length).toBeGreaterThan(0);
    for (const card of claimed) {
      expect(offersRelease({ ...card, stale: true }), `${card.kind}/${card.lifecycle}`).toBe(true);
    }
  });

  it('offers Release on nothing that is not stale', () => {
    for (const card of EVERY_CARD) {
      expect(offersRelease(card), `${card.kind}/${card.lifecycle}`).toBe(false);
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

describe('an answered judgement is a decided one — `kanban-patrol/15`', () => {
  /**
   * The owner's decision of 2026-09-04: Answer records a decision on a Needs
   * You card and returns it to **Detected**, carrying the answer. Never to
   * Resolved — `17`'s evidence gate is still the only road there — and never
   * left in Needs You, which is the column a person reads for outstanding
   * questions.
   */
  const JUDGEMENTS = CARD_KINDS.filter(
    (kind) => columnForCard({ kind, lifecycle: 'open' }) === 'needsYou',
  );

  it('has judgements to talk about at all', () => {
    // A rule about an empty set is a rule that passes for the wrong reason.
    expect(JUDGEMENTS.length).toBeGreaterThan(0);
  });

  it('moves an answered judgement out of Needs You and into Detected', () => {
    for (const kind of JUDGEMENTS) {
      expect(columnForCard({ kind, lifecycle: 'open', answer: 'the cloud one' }), kind).toBe(
        'detected',
      );
    }
  });

  it('offers Attend on it, because the judgement it was waiting on is made', () => {
    for (const kind of JUDGEMENTS) {
      expect(actionForCard({ kind, lifecycle: 'open', answer: 'the cloud one' }), kind).toBe(
        'attend',
      );
    }
  });

  it('never sends an answered judgement to Resolved', () => {
    for (const kind of JUDGEMENTS) {
      expect(columnForCard({ kind, lifecycle: 'open', answer: 'the cloud one' }), kind).not.toBe(
        'resolved',
      );
    }
  });

  it('treats a blank answer as no answer at all', () => {
    // `bool(' ')` is true in every language this feature is written in, and
    // a whitespace decision is exactly as meaningless as an empty one — the
    // store refuses to write it, and this is the second line.
    for (const kind of JUDGEMENTS) {
      expect(columnForCard({ kind, lifecycle: 'open', answer: '   ' }), kind).toBe('needsYou');
    }
  });

  it('leaves a claimed answered judgement where it is — somebody is on it', () => {
    for (const kind of JUDGEMENTS) {
      expect(columnForCard({ kind, lifecycle: 'claimed', answer: 'the cloud one' }), kind).toBe(
        'inProgress',
      );
    }
  });
});

describe('what a person may type into the Answer field', () => {
  /**
   * `kanban-patrol/15`. The store refuses a blank answer and returns a `400`;
   * this is the same rule one layer up, so the button is disabled rather than
   * the person learning it from a failed request. Pure, so it is asserted
   * here rather than through a rendered field.
   */
  it('accepts a real decision', () => {
    expect(isAnswerSubmittable('Use the cloud one.')).toBe(true);
  });

  it('refuses an empty one', () => {
    expect(isAnswerSubmittable('')).toBe(false);
  });

  it('refuses whitespace, which is what an empty one usually looks like', () => {
    expect(isAnswerSubmittable('   \n\t ')).toBe(false);
  });

  it('is the same trim the store applies, so nothing passes here and fails there', () => {
    expect(isAnswerSubmittable('  ok  ')).toBe(true);
  });
});
