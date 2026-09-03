import { columnForCard, type CardKind, type CardLifecycle } from './cardKind';

/**
 * What a card lets you do — `kanban-patrol/15`.
 *
 * ## The four columns are four different affordances, and two are none
 *
 * | Column | Action | Why |
 * | --- | --- | --- |
 * | Detected | `attend` | the patrol is confident; it needs doing, not deciding |
 * | Needs You | `answer` | the patrol stopped on a judgement only a person may make |
 * | In Progress | *none* | somebody is on it |
 * | Resolved | *none* | closed, and carrying its evidence |
 *
 * **In Progress having no action is a decision, not an omission.** It is the
 * board's only defence against two actors working one card, and it is why the
 * claim in `16` has to be atomic rather than advisory.
 *
 * ## Why this is a module and not a ternary in the card
 *
 * The board is not the only caller. `16`'s MCP tools have to answer the same
 * question — *may this actor take this card* — and an agent that computed it
 * from its own copy of the rule would be a second opinion that agrees until
 * somebody edits one of them. One function, both callers.
 */

export type CardAction = 'attend' | 'answer';

/** Every action, as data, so a test can iterate rather than restate. */
export const CARD_ACTIONS: readonly CardAction[] = ['attend', 'answer'];

/** The card facts this decision needs, and no more. */
interface ActionableCard {
  readonly kind: CardKind;
  readonly lifecycle: CardLifecycle;
}

/**
 * The one action a card offers, or `null` for the two columns that offer none.
 *
 * Derived from the column rather than from the kind, deliberately: a claimed
 * judgement is *In Progress*, and it must lose its Answer control when it gets
 * there or two people answer one question. Routing through `columnForCard`
 * means that follows automatically instead of being a second rule to maintain.
 */
export function actionForCard(card: ActionableCard): CardAction | null {
  switch (columnForCard(card)) {
    case 'detected':
      return 'attend';
    case 'needsYou':
      return 'answer';
    case 'inProgress':
    case 'resolved':
      return null;
  }
}

/**
 * How each action is worded, in one place.
 *
 * Two spellings of one verb agree on the day they are written and drift on the
 * first reword — the rule `Badge`'s `explanation` already follows, and the
 * reason the hint is owned here rather than at the button.
 */
export const ACTION_COPY: Readonly<Record<CardAction, { label: string; hint: string }>> = {
  attend: {
    label: 'Attend',
    hint:
      'Hand this to an agent. It moves to In Progress and becomes claimable over MCP — ' +
      'this does not start anything by itself, because a browser cannot.',
  },
  answer: {
    label: 'Answer',
    hint:
      'This one is yours. The patrol stopped on a judgement it should not make, so it is ' +
      'waiting on a decision rather than on work.',
  },
};
