import { columnForCard, type CardKind, type CardLifecycle } from './cardKind';

/**
 * What an In Progress card actually says — `kanban-patrol/19`.
 *
 * ## Why the column's own label is the wrong word here
 *
 * Every claimed card sat under one sentence: *In Progress*. A card an agent
 * had only just taken and a card whose test is already green read identically,
 * so the column answered "somebody has this" and nothing answered the question
 * a reader is actually asking — *how far has it got?* The stage is already on
 * the row (`kanban_store.Stage`, the only field an actor moves), and it was
 * being dropped on the way to the card.
 *
 * ## Why the copy is a table and not four ternaries at the card
 *
 * Same rule `ACTION_COPY` follows: a label spelled at its render site is a
 * label with no owner, and the second spelling arrives the first time somebody
 * rewords one of them. One table, keyed by the stage the store already writes.
 *
 * The wording is GitHub's own convention, settled in `19` rather than chosen
 * here — "Queued", "In progress — …", "Awaiting review".
 */

export type CardStage = 'unattended' | 'attended' | 'red' | 'green' | 'finished';

/**
 * Every stage, as data, so a test iterates rather than restates — the same
 * reason `CARD_KINDS` and `CARD_ACTIONS` are exported.
 *
 * In the store's own advancing order (`kanban_store._STAGE_SEQUENCE`), which
 * is the order a reader watches a card move through.
 */
export const CARD_STAGES: readonly CardStage[] = [
  'unattended',
  'attended',
  'red',
  'green',
  'finished',
];

/**
 * The sentence each claimed stage shows, from `19`'s own table.
 *
 * `unattended` is absent because it is not a claimed stage: an unattended
 * card is in Detected, where the column's label is the honest answer and a
 * stage sentence would be describing a claim nobody has made.
 *
 * `finished` **is** here even though a finished card normally maps to
 * Resolved: `finished` is a claim and `17`'s evidence gate is what carries a
 * card into Resolved, so a finished card that has not cleared the gate is
 * still In Progress and says the truthful thing — it is waiting on a reader,
 * not on work.
 */
export const IN_PROGRESS_STAGE_COPY: Readonly<Record<Exclude<CardStage, 'unattended'>, string>> = {
  attended: 'Queued',
  red: 'In progress — test written',
  green: 'In progress — test passing',
  finished: 'Awaiting review',
};

/** The card facts this decision needs, and no more. */
interface StagedCard {
  readonly kind: CardKind;
  readonly lifecycle: CardLifecycle;
  /**
   * The stage the store recorded. Optional because a fixture card and every
   * card that predates this field are still cards — a missing stage falls
   * back to the column's own label rather than rendering a blank status line.
   */
  readonly stage?: CardStage;
}

/**
 * The words beside a card's dot.
 *
 * Routed through `columnForCard` rather than through the passed-in column, for
 * the reason `actionForCard` gives: one function decides where a card is, and
 * a second surface re-deriving it is a second opinion. The label is passed in
 * because the column owns it (`BOARD_COLUMNS`) and this file must not own a
 * second spelling of "Detected".
 */
export function statusTextForCard(card: StagedCard, columnLabel: string): string {
  if (columnForCard(card) !== 'inProgress') return columnLabel;
  const stage = card.stage;
  if (stage === undefined || stage === 'unattended') return columnLabel;
  // Indexed rather than switched, so an unknown stage from an older or newer
  // API is the column's label — never `undefined` rendered as nothing.
  return IN_PROGRESS_STAGE_COPY[stage] ?? columnLabel;
}
