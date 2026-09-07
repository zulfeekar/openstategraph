import type { ComponentProps } from 'react';
import type { Badge } from '@design/primitives';

/**
 * The two axes a card carries beside its kind — `kanban-patrol/06`.
 *
 * ## Its own module because it is its own axis
 *
 * Priority answers *how urgent*; the column answers *what it needs next*.
 * They move independently — a card is re-prioritised without changing column
 * far more often than the reverse — and a urgency scale that gained a fourth
 * level should not be an edit to the file that owns the board's structure.
 */

type BadgeTone = NonNullable<ComponentProps<typeof Badge>['tone']>;

export type BoardPriority = 'high' | 'med' | 'low';

/** The discipline a card belongs to, so a board can be read by who picks it up. */
export type BoardArea = 'ui' | 'ux' | 'frontend' | 'backend' | 'test' | 'docs';

export interface PriorityMark {
  readonly label: string;
  readonly tone: BadgeTone;
  /**
   * What the word means, carried here rather than written at the call site.
   *
   * `Badge`'s own rule: an explanation *"comes from wherever the claim itself
   * is owned — never re-worded at the call site"*, and a word on a badge must
   * carry one at all unless it is a count. `Med` is the case that proves the
   * rule useful: it is the same colour as `Low`, so without a sentence the
   * only thing separating them is a three-letter abbreviation.
   */
  readonly explanation: string;
}

/**
 * How a priority is drawn, and why only one of the three is coloured.
 *
 * `Badge` has four tones and this board has already spent all four on its
 * columns. Priority is a **second** axis on the same card, so it cannot have
 * four more colours without either minting a token — refused — or re-using a
 * column's colour to mean something else, which is worse: a red dot and a red
 * badge on one card that mean two unrelated things is how a reader stops
 * trusting either.
 *
 * So exactly one level is coloured. `high` is `danger`, because the only
 * question a colour needs to answer at a glance is *which of these is
 * urgent*; `med` and `low` are `neutral` and are told apart by their **word**.
 * That is deliberately not colour-alone — which is the accessible answer as
 * well as the token-free one, and it survives `14` (the `accent` tone renders
 * flat off-canvas, so a scheme that leaned on it would have shipped a level
 * nobody could see).
 */
export const PRIORITY_MARKS: Readonly<Record<BoardPriority, PriorityMark>> = {
  high: {
    label: 'High',
    tone: 'danger',
    explanation:
      'High priority — this is either wrong in a way a user cannot see, or it blocks ' +
      'something else on the board. Take it before anything below it.',
  },
  med: {
    label: 'Med',
    tone: 'neutral',
    explanation:
      'Medium priority — worth doing, and nothing is waiting on it. The default for a ' +
      'finding that is real but not urgent.',
  },
  low: {
    label: 'Low',
    tone: 'neutral',
    explanation:
      'Low priority — an improvement rather than a defect. Safe to leave until the ' +
      'board is otherwise clear.',
  },
};
