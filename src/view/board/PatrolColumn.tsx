import { Badge } from '@design/primitives';
import { PatrolCard } from './PatrolCard';
import { cardsInColumn, type BoardCard, type BoardColumn } from './patrolBoardModel';

export interface PatrolColumnProps {
  readonly column: BoardColumn;
  /** Every card on the board. The column selects its own. */
  readonly cards: readonly BoardCard[];
  /** Passed straight through — the column decides nothing about the gesture. */
  readonly onAnswer?: (card: BoardCard, answer: string) => void;
  /** Passed straight through — `kanban-patrol/19`'s explicit Release. */
  readonly onRelease?: (card: BoardCard) => void;
}

/**
 * One column — its heading, its count, and the cards in it.
 * `kanban-patrol/06`.
 *
 * ## Why the whole board's cards come in
 *
 * The column filters rather than being handed a pre-filtered list, so the
 * count in the header and the list under it can never disagree: they are one
 * `cardsInColumn` call, read twice. A caller that filtered and passed both
 * would be free to pass a count from one source and a list from another.
 *
 * `cardsInColumn` is a filter and not a sort, deliberately — cards land one
 * at a time while a patrol runs, and re-ordering under the reader's pointer
 * is the board nobody can click.
 */
export function PatrolColumn({ column, cards, onAnswer, onRelease }: PatrolColumnProps) {
  const inColumn = cardsInColumn(cards, column.id);

  return (
    <section className="patrol-column">
      <header className="patrol-column__head">
        <span className="patrol-column__label">{column.label}</span>
        {/* `numeric`, so it is a count beside the thing it counts and owes no
            explanation — the rule `badgeExplanations.test.ts` enforces. */}
        <Badge tone={column.tone} numeric>
          {inColumn.length}
        </Badge>
      </header>

      <ul className="patrol-column__cards">
        {inColumn.map((card) => (
          <PatrolCard
            key={card.id}
            card={card}
            column={column}
            onAnswer={onAnswer}
            onRelease={onRelease}
          />
        ))}
      </ul>
    </section>
  );
}
