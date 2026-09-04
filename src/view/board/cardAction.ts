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
  /**
   * The decision recorded on this card — `kanban-patrol/15`. Passed straight
   * through to `columnForCard`, which is what makes an answered judgement
   * offer **Attend** rather than a second Answer: the column decides the
   * affordance, and this changes the column.
   */
  readonly answer?: string;
  /**
   * Whether the API flagged this card's claim as abandoned. Optional
   * because it is absent on every card that is not — the same
   * absent-not-false rule the mapping applies on the wire.
   */
  readonly stale?: boolean;
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
/**
 * May this text be recorded as a decision? — `kanban-patrol/15`.
 *
 * `kanban_store.answer_card` refuses a blank or whitespace answer and the
 * route turns that into a `400`. This is the same rule one layer up, so the
 * Answer field's button is disabled rather than a person learning it from a
 * failed request — and it is the *same* trim, so nothing passes here and
 * fails there.
 *
 * A function rather than a check inside the card, for this file's own stated
 * reason: it is a rule, and a rule inside a component is a rule only a
 * rendered test can reach.
 */
export function isAnswerSubmittable(text: string): boolean {
  return text.trim().length > 0;
}

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

/**
 * Whether this card offers **Release** — `kanban-patrol/32`.
 *
 * Release is not one of `CardAction`'s two, because it is not derived from
 * the kind and it is not an action on the work: it is the human half of
 * "flag, never auto-release", and it can fire from any claimed card. But it
 * *is* an affordance, and until this function existed it was the one
 * affordance the column never got to decide — `PatrolCard` rendered it
 * straight from `card.stale`, so the rule that Resolved offers nothing was
 * green while a Resolved card drew the only control on this board that
 * destroys data (Release empties all four evidence fields).
 *
 * The store is the fact and is fixed there — a `finished` card is never
 * flagged, so this never fires on a row from a current backend. This is the
 * second line: a stale-looking row from an older API, a cached response, or
 * a future stage that collapses onto `resolved` still gets no button.
 */
export function offersRelease(card: ActionableCard): boolean {
  return card.stale === true && columnForCard(card) !== 'resolved';
}
