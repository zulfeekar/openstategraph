import { useState } from 'react';
import { Badge, Button, StatusDot, TextArea, Tooltip } from '@design/primitives';
import { type BoardCard, type BoardColumn } from './patrolBoardModel';
import { PRIORITY_MARKS } from './cardPriority';
import { ACTION_COPY, actionForCard, isAnswerSubmittable, offersRelease } from './cardAction';
import { instructionForCard } from './cardInstruction';
import { statusTextForCard } from './cardStage';

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
   * The decision a person typed — `kanban-patrol/15`, decided 2026-09-04.
   *
   * Replaces the `onAct` that used to carry both gestures. `attend` stopped
   * needing a handler when `19` made it two clipboard buttons, and `answer`
   * stopped fitting one when it grew a text field: a callback taking a verb
   * and no payload cannot carry an answer. Optional, same rule as
   * `onRelease`: no handler, no field, rather than one that does nothing.
   */
  readonly onAnswer?: (card: BoardCard, answer: string) => void;
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
export function PatrolCard({ card, column, onAnswer, onRelease }: PatrolCardProps) {
  const priority = PRIORITY_MARKS[card.priority];
  // Two of the four columns offer nothing, deliberately — `15`. In Progress
  // offering no action is the board's only defence against two actors working
  // one card.
  const action = actionForCard(card);
  // Local to the card, deliberately: a half-typed decision is not board
  // state, nobody else needs to see it, and lifting it would make the board
  // re-render on every keystroke in one card's field.
  const [answering, setAnswering] = useState(false);
  const [draft, setDraft] = useState('');

  return (
    <li className="patrol-card">
      <span className="patrol-card__title">{card.title}</span>
      <span className="patrol-card__secondary">{card.secondary}</span>

      {/* `osg-agent-experience/25`. The brief an idea card carries, directly
          under the title, because it *is* the card — a title alone is what
          this feature exists to stop a filed idea decaying into. Guarded, not
          merely mapped: a patrol card has no story and must draw nothing at
          all here, not an empty element under every title on the board. */}
      {card.story ? <span className="patrol-card__story">{card.story}</span> : null}
      {card.doneWhen ? (
        <span className="patrol-card__done-when">
          Done when: <span className="patrol-card__done-when-text">{card.doneWhen}</span>
        </span>
      ) : null}
      {/* Model and effort on one line, together — neither reads as a whole
          answer on its own, and two lines would give an advisory hint the
          same weight as the brief above it. */}
      {card.agentModel ? (
        <span className="patrol-card__agent">
          suggested: {card.agentModel}
          {card.agentEffort ? ` · ${card.agentEffort} effort` : ''}
        </span>
      ) : null}

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
        {/* `kanban-patrol/19`: the column's label is the right word in three
            columns and the wrong one in In Progress, where every claimed card
            read the same sentence whatever the actor had actually reported.
            The stage table is owned in `cardStage.ts`; nothing here spells a
            status word, exactly as nothing here spells a tone. */}
        {statusTextForCard(card, column.label)}
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

      {/* `osg-agent-experience/85`: what the closing checks said, on the card
          rather than in the shell that ran them. The line above names the test
          that proves the work; this one carries the verdict of the gate run at
          the end, which until this ticket `set_stage` accepted and dropped. */}
      {card.finishedReason ? (
        <span className="patrol-card__evidence">finished: {card.finishedReason}</span>
      ) : null}

      {/* `team-board-and-gap-reports/17`: how many installs have hit this
          gap. The keyless door counts repeats onto one card, and until this
          line the board drew a card that said a gap exists with no way to
          tell one report from forty. Only ever present above one — the
          mapping drops it at one, because a number true of every card on the
          board makes the counted one harder to spot. Same caption tone as the
          evidence lines above it; nothing new is minted. */}
      {card.count ? <span className="patrol-card__count">reported {card.count} times</span> : null}

      {/* `kanban-patrol/19`'s explicit Release: "flag, never auto-release" —
          the card says so honestly, and a human reads it and presses the
          button themselves. Only present once the lease has actually gone
          past the hour-long threshold; the system never releases anything
          on its own schedule. Routed through `offersRelease` rather than
          read from `card.stale` — `kanban-patrol/32`: the column decides
          this affordance too, so Resolved cannot draw the one control that
          empties a card's evidence. */}
      {offersRelease(card) ? (
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
      ) : action === 'answer' && onAnswer ? (
        /* `kanban-patrol/15`, decided 2026-09-04: Answer opens a small text
           field rather than firing a gesture. The card is in Needs You
           because a question was asked, so the control has to be able to
           carry the answer — a button that only says "answered" would record
           a decision nobody can read.

           Submitting sends the card back to **Detected** carrying the
           decision (the store does that, from the answer alone), so an agent
           attends it next with the judgement already made. */
        <span className="patrol-card__action">
          {answering ? (
            <>
              {/* The design system's own control, not a bare `<textarea>`:
                  the board paints no field of its own, for the same reason
                  `04` says it paints no dot of its own. */}
              <TextArea
                className="patrol-card__answer"
                value={draft}
                autoFocus
                minRows={2}
                aria-label={`Your decision on "${card.title}"`}
                placeholder="Your decision, in your own words"
                onChange={(event) => setDraft(event.target.value)}
              />
              <Button
                variant="primary"
                size="sm"
                /* The same trim the store applies — `isAnswerSubmittable` —
                   so a blank decision is refused here rather than by a 400
                   the person has to read to find out. */
                disabled={!isAnswerSubmittable(draft)}
                onClick={() => {
                  onAnswer(card, draft.trim());
                  setAnswering(false);
                  setDraft('');
                }}
              >
                Record decision
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setAnswering(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <Tooltip content={ACTION_COPY[action].hint} multiline>
              <Button variant="secondary" size="sm" onClick={() => setAnswering(true)}>
                {ACTION_COPY[action].label}
              </Button>
            </Tooltip>
          )}
        </span>
      ) : null}
    </li>
  );
}
