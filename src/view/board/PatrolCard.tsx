import { Badge, Button, StatusDot, Tooltip } from '@design/primitives';
import { type BoardCard, type BoardColumn } from './patrolBoardModel';
import { PRIORITY_MARKS } from './cardPriority';
import { ACTION_COPY, actionForCard } from './cardAction';
import { instructionForCard } from './cardInstruction';

export interface PatrolCardProps {
  readonly card: BoardCard;
  /**
   * The column this card is sitting in.
   *
   * Passed in rather than looked up from `card.column`: the column owns the
   * dot's tone and the word beside it, and a card that re-derived them would
   * be the second place that mapping lives — which is the one thing
   * `04` settled must not happen.
   */
  readonly column: BoardColumn;
  /**
   * The gesture. What it *means* is the column's — `attend` hands a card to an
   * agent, `answer` asks a person for a judgement — and the caller owns the
   * consequence, because neither can be done from a browser alone.
   */
  readonly onAct?: (card: BoardCard, action: 'attend' | 'answer') => void;
  /**
   * The explicit Release — `kanban-patrol/19`. Distinct from `onAct`: it is
   * not derived from `kind`/`column` the way attend/answer are, it is
   * derived from `card.stale`, and it can fire from any in-progress card
   * regardless of which kind filed it. Optional, same rule as `onAct`: no
   * handler, no button, rather than one that does nothing.
   */
  readonly onRelease?: (card: BoardCard) => void;
}

/**
 * One card on the patrol board — `kanban-patrol/06`.
 *
 * ## Why this is its own component
 *
 * It was inline in `PatrolBoard` and that was the god component forming: the
 * board was rendering the dialog, the tabs, two empty states, the columns
 * *and* the cards, which is six reasons to change in one function. A card is
 * about to grow an action — attending one is its own ticket — and the seam
 * has to exist before that lands, not after.
 *
 * ## It decides no colour
 *
 * Both marks it draws are handed to it. The dot's tone comes from the column;
 * the priority's tone comes from `PRIORITY_MARKS`. Neither is spelled here,
 * which is what keeps the board's palette in one table.
 */
export function PatrolCard({ card, column, onAct, onRelease }: PatrolCardProps) {
  const priority = PRIORITY_MARKS[card.priority];
  // Two of the four columns offer nothing, deliberately — `15`. In Progress
  // offering no action is the board's only defence against two actors working
  // one card.
  const action = actionForCard(card);

  return (
    <li className="patrol-card">
      <span className="patrol-card__title">{card.title}</span>
      <span className="patrol-card__secondary">{card.secondary}</span>

      {/* The two axes the owner asked the board to carry, so it can be
          prioritised and read by discipline rather than only listed.
          Priority is a `Badge`; the area is a plain mono tag, because a
          second badge would put two marks of equal weight on one card and
          neither would read as the urgent one. */}
      <span className="patrol-card__meta">
        {/* The card's own reason wins when the classifier gave one — it's
            specific to this finding; the generic per-level sentence is the
            fallback for a card nobody explained. */}
        <Badge tone={priority.tone} explanation={card.priorityReason ?? priority.explanation}>
          {priority.label}
        </Badge>
        {/* The kind, which is *why* this card is in this column — a reader
            can tell a question from a task without opening it. Rendered as a
            word rather than a second badge, for the same reason the area is:
            three marks of equal weight and none of them reads as primary. */}
        <span className="patrol-card__kind">{card.kind}</span>
        <span className="patrol-card__area">{card.area}</span>
      </span>

      <span className="patrol-card__status">
        <StatusDot tone={column.dot} />
        {column.label}
        <span className="patrol-card__when">
          {card.when}
          {card.filedOn ? ` · ${card.filedOn}` : ''}
        </span>
      </span>

      {/* `kanban-patrol/17`+`21`: evidence nobody can read is a checkbox
          with extra steps. A resolved card renders the proof behind it —
          the test that failed and why — rather than only the fact that it
          reached this column. Only present on a resolved card; the mapping
          (`kanbanCardMapping.ts`) never populates these fields early. */}
      {card.evidenceTestId ? (
        <Tooltip content={card.evidenceRedReason ?? ''} multiline>
          <span className="patrol-card__evidence">
            evidence: <code className="patrol-card__evidence-test">{card.evidenceTestId}</code>
          </span>
        </Tooltip>
      ) : null}

      {/* `kanban-patrol/19`'s explicit Release: "flag, never auto-release" —
          the card says so honestly, and a human reads it and presses the
          button themselves. Only present once the lease has actually gone
          past the hour-long threshold; the system never releases anything
          on its own schedule. */}
      {card.stale ? (
        <span className="patrol-card__stale">
          attended, nothing new in over an hour
          {onRelease ? (
            <Button variant="secondary" size="sm" onClick={() => onRelease(card)}>
              Release
            </Button>
          ) : null}
        </span>
      ) : null}

      {action === 'attend' ? (
        // `kanban-patrol/19`'s redesign, replacing the click-and-notify
        // placeholder `15` first shipped: nothing here can start a coding
        // agent, so instead of pretending to, the card hands over what a
        // person pastes into whichever agent they run. "Copy ID" is for an
        // agent that already has the CLI/MCP door installed and can read
        // this row live; "Copy instruction" needs neither.
        <span className="patrol-card__action">
          <Tooltip content="Self-contained — paste into any coding agent, nothing installed required.">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void navigator.clipboard.writeText(instructionForCard(card))}
            >
              Copy instruction
            </Button>
          </Tooltip>
          <Tooltip content="Just the task id, for an agent that already has the kanban CLI/MCP door.">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void navigator.clipboard.writeText(card.id)}
            >
              Copy ID
            </Button>
          </Tooltip>
        </span>
      ) : action !== null && onAct ? (
        <Tooltip content={ACTION_COPY[action].hint} multiline>
          <Button
            variant="secondary"
            size="sm"
            className="patrol-card__action"
            onClick={() => onAct(card, action)}
          >
            {ACTION_COPY[action].label}
          </Button>
        </Tooltip>
      ) : null}
    </li>
  );
}
