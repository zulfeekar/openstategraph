import type { BoardColumnId } from './patrolBoardModel';

/**
 * What kind of ticket a card is — `kanban-patrol/18`.
 *
 * ## The vocabulary is not invented here
 *
 * These are the ticket types every map under `.scratch/` already uses. Reusing
 * them rather than minting a parallel set is the point: a card the patrol
 * files and a ticket a person files are the same kind of object, so a reader
 * who knows one knows the other, and a card can graduate into a real ticket
 * without translation.
 *
 * ## The split that matters, and it is the board's own columns
 *
 * A ticket type says what the ticket **ends in**, and that answers directly
 * whether an agent may take it:
 *
 * - `research` ends in a fact, `task` in a change, `bug` in a fix whose
 *   decision is already made. An agent can go and do all three.
 * - `grilling` ends in a judgement, `decision` in a choice that is the owner's,
 *   `prototype` in a human reacting to something concrete. None is an agent's
 *   to settle.
 *
 * That is exactly Needs You versus Detected. So the column is **derived** from
 * the kind and never stored beside it — a stored column could disagree with
 * the kind, and the disagreement would put a judgement in the column an agent
 * pulls work from.
 */

export type CardKind = 'research' | 'task' | 'bug' | 'prototype' | 'grilling' | 'decision';

/**
 * Every kind, as data.
 *
 * Exported and iterated by the tests rather than restated there: a seventh
 * kind added here is automatically held to the partition property instead of
 * quietly going unasserted, which is how a "does every X do Y" test comes to
 * guard nothing.
 */
export const CARD_KINDS: readonly CardKind[] = [
  'research',
  'task',
  'bug',
  'prototype',
  'grilling',
  'decision',
];

/**
 * The kinds a person must settle.
 *
 * A `Set` rather than a predicate with a `switch`, so adding a kind is a data
 * edit in one place and the compiler still checks the members.
 */
const HUMAN_DECISION: ReadonlySet<CardKind> = new Set<CardKind>([
  'prototype',
  'grilling',
  'decision',
]);

/**
 * Does this kind end in a judgement only a person may make?
 *
 * The one question the board, the MCP claim and the patrol all ask, so it is
 * asked in one place. `16`'s `claim_card` refuses when this is true: an agent
 * may not claim a judgement, and that refusal is structural rather than a
 * convention an agent is trusted to observe.
 */
export function isHumanDecision(kind: CardKind): boolean {
  return HUMAN_DECISION.has(kind);
}

/**
 * Which column a card of this kind opens in.
 *
 * Only ever `detected` or `needsYou`. The other two columns are **reached**
 * and never filed into: `inProgress` means an actor claimed it, `resolved`
 * carries evidence that a test went red and then green (`17`). A patrol that
 * could open a card directly into either would be closing work nobody did.
 */
export function columnForKind(kind: CardKind): BoardColumnId {
  return isHumanDecision(kind) ? 'needsYou' : 'detected';
}

/* ------------------------------------------------------------------ *
 * Lifecycle — where a card has moved to since it opened
 * ------------------------------------------------------------------ */

/**
 * What has happened to a card since the patrol filed it.
 *
 * Separate from `kind` because they answer different questions and change at
 * different times. **Kind is fixed at filing and never moves** — a judgement
 * does not become a task because somebody worked on it. **Lifecycle is the
 * only thing an actor changes**, and it is the whole of what claiming and
 * resolving do.
 *
 * Collapsing the two into one `column` field was the first shape tried and it
 * is wrong in both directions: a patrol could file straight into `resolved`,
 * and a claim would have to overwrite the kind to move the card.
 */
export type CardLifecycle = 'open' | 'claimed' | 'resolved';

/**
 * The column a card is actually in — `18`.
 *
 * Lifecycle outranks kind, and that ordering is the design:
 *
 * - `resolved` → **Resolved**, whatever kind it was. `17` gates entry on
 *   evidence, so reaching this state is already the hard part.
 * - `claimed` → **In Progress**, whatever kind it was. This is why a claimed
 *   `grilling` leaves Needs You: somebody is answering it, and leaving it in
 *   Needs You would invite a second person to answer it too.
 * - `open` → wherever its **kind** opens it — **unless** the judgement has
 *   been answered (`kanban-patrol/15`, decided 2026-09-04), in which case it
 *   goes to Detected. Needs You is the column a person reads for outstanding
 *   questions; a card whose question has been settled sitting in it is a
 *   claim that the question is still open. It goes to Detected and not to
 *   Resolved because a decision is not evidence that anything was built —
 *   `17`'s gate is still the only road there — and an agent can now attend it
 *   with the judgement already made.
 *
 * One function, so no surface can compute a different answer. The board reads
 * it, and `16`'s MCP tools read it, and neither may re-derive it locally.
 */
export function columnForCard(card: {
  readonly kind: CardKind;
  readonly lifecycle: CardLifecycle;
  /**
   * The decision recorded on this card, if one has been. Absent on every
   * card that has none — and read for its *trimmed* content, never its mere
   * presence, so a row that arrives carrying an empty or whitespace answer
   * still reads as unanswered. `kanban_store.answer_card` refuses to write
   * one; this is the second line.
   */
  readonly answer?: string;
}): BoardColumnId {
  if (card.lifecycle === 'resolved') return 'resolved';
  if (card.lifecycle === 'claimed') return 'inProgress';
  if (card.answer?.trim()) return 'detected';
  return columnForKind(card.kind);
}
