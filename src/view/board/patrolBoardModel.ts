import type { ComponentProps } from 'react';
import type { Badge, StatusTone } from '@design/primitives';
// Runtime import in one direction only: `cardKind` imports nothing from here
// but a type, which is erased — so there is no cycle at runtime.
import { columnForCard, type CardKind, type CardLifecycle } from './cardKind';
import type { CardStage } from './cardStage';
import type { BoardArea, BoardPriority } from './cardPriority';

/**
 * The board's shape — `kanban-patrol/06`.
 *
 * Framework-free on purpose, so the two decisions that are actually decisions
 * can be executed by a test rather than read back out of JSX: **which colour a
 * column is**, and **what order cards come out in**.
 */

/* ------------------------------------------------------------------ *
 * The columns
 * ------------------------------------------------------------------ */

export type BoardColumnId = 'detected' | 'needsYou' | 'inProgress' | 'resolved';

/**
 * `Badge`'s tone union, taken from `Badge` rather than restated.
 *
 * The point of `04`'s mapping is that the board spends tones that already
 * exist. A hand-copied union would keep agreeing with the primitive right up
 * until somebody adds a fifth tone or renames one, and then it would be a
 * second definition of the design system's palette living in a feature.
 */
type BadgeTone = NonNullable<ComponentProps<typeof Badge>['tone']>;

export interface BoardColumn {
  readonly id: BoardColumnId;
  /** Settled by the owner in `04`. Not this ticket's to rename. */
  readonly label: string;
  /** The column header's badge. */
  readonly tone: BadgeTone;
  /** The dot inside every card in the column. */
  readonly dot: StatusTone;
}

/**
 * Four columns, four tones, one table — `04`, decided by the owner.
 *
 * | Column | Badge | Dot |
 * | --- | --- | --- |
 * | Detected | `neutral` | the patrol found it; nobody has looked |
 * | Needs You | `danger` | a person must decide before anything proceeds |
 * | In Progress | `accent` | somebody, or a coding agent, is on it |
 * | Resolved | `success` | done |
 *
 * **Both names sit in one row because that is the rule.** `04`: *"the mapping
 * lives in one place both the header and the card read, so a column cannot be
 * `danger` in one and `accent` in the other."* The header and the dot answer
 * to different vocabularies — `Badge` has four tones, `StatusDot` has seven —
 * and the failure the rule is about is the two being chosen in two files, not
 * the two existing.
 *
 * **Why the dot is `StatusDot` and not a span this feature paints.** It is
 * `04`'s own argument one layer down: a board that coloured its own dots would
 * be a fifth opinion about what red means, and the first place a new token
 * gets minted is a feature stylesheet that needed *nearly* an existing colour.
 * The pairing is by hue, not by wording — `paused` reads better than `error`
 * for "waiting for a person", and it is amber where the column's badge is red,
 * which is exactly the disagreement the rule forbids.
 */
export const BOARD_COLUMNS: readonly BoardColumn[] = [
  { id: 'detected', label: 'Detected', tone: 'neutral', dot: 'idle' },
  { id: 'needsYou', label: 'Needs You', tone: 'danger', dot: 'error' },
  { id: 'inProgress', label: 'In Progress', tone: 'accent', dot: 'running' },
  { id: 'resolved', label: 'Resolved', tone: 'success', dot: 'success' },
];

/* ------------------------------------------------------------------ *
 * The card
 * ------------------------------------------------------------------ */

/**
 * What a card shows, and **nothing more**.
 *
 * The real schema is `kanban-patrol/02`, which is still open and owns every
 * question this deliberately does not answer — what a finding is, how it is
 * identified across patrols, which of the three boards it belongs to. This is
 * the shell's fixture shape: the four things the reference structure puts on a
 * card, so the layout can be drawn and reviewed without waiting on a field
 * list it does not depend on.
 *
 * `when` is **already worded** rather than a timestamp, for the reason
 * `StartPanel` and `ArrivalDialog` both give: a column of ages that advanced
 * under the cursor while somebody read it would be worse than one that is a
 * few seconds old. Whoever owns `02` may replace it with an instant and a
 * formatter; nothing here depends on which.
 */
export interface BoardCard {
  readonly id: string;
  readonly title: string;
  /** The second line — where the finding was seen. */
  readonly secondary: string;
  /**
   * What kind of ticket this is — and therefore which column it opens in.
   *
   * The column is **not** stored beside it (`18`). A stored column could
   * disagree with the kind, and the disagreement would be silent and would put
   * a judgement in the column an agent pulls work from.
   */
  readonly kind: CardKind;
  /**
   * Where the card has moved to since it was filed.
   *
   * The only field an actor changes. Kind is fixed at filing; lifecycle is
   * what claiming and resolving do, and `columnForCard` combines the two.
   */
  readonly lifecycle: CardLifecycle;
  /** A relative time, as a phrase. */
  readonly when: string;
  /**
   * The absolute date it was filed, month/day/year — alongside `when`, never
   * instead of it. A relative phrase answers "how long ago"; a calendar date
   * answers "which day", and a reader scanning a board of several days'
   * findings needs both. Optional: existing fixtures and tests that predate
   * this field are still valid cards, same rule every other new field on
   * this interface follows.
   */
  readonly filedOn?: string;
  /** How urgent, on the owner's three-level axis. */
  readonly priority: BoardPriority;
  /**
   * The plain-English *why*, written at classification time — distinct from
   * `PRIORITY_MARKS`' generic per-level sentence, which reads the same for
   * every card at that level regardless of what actually happened. Absent
   * when the classifier gave none, never an empty string.
   */
  readonly priorityReason?: string;
  /** Which discipline picks it up. */
  readonly area: BoardArea;
  /**
   * `kanban-patrol/17`+`21`'s evidence gate. Present only when `lifecycle`
   * is `'resolved'` — the backend refuses the `finished` transition without
   * both fields already recorded, so a resolved card always has them and an
   * unresolved one never does. Absent, never an empty string, same rule as
   * `priorityReason`/`filedOn`: "no evidence" has to mean "the prop is
   * absent", not a blank line rendered on every unclaimed card.
   */
  readonly evidenceTestId?: string;
  /** The reason the test failed, recorded at the `red` transition. */
  readonly evidenceRedReason?: string;
  /**
   * `kanban-patrol/19`'s explicit Release. Present and `true` only when the
   * card's claim has gone past the hour-long lease with no heartbeat —
   * absent, never `false`, same rule as `priorityReason`/`filedOn`: "not
   * stale" has to mean "the prop is absent", not a flag rendered false on
   * every other card.
   */
  readonly stale?: boolean;
  /**
   * How far the actor holding this card has got — `kanban-patrol/19`'s stage
   * table. Read by `statusTextForCard`, which is the only thing that turns it
   * into words; the card renders no stage of its own.
   *
   * Optional for the same reason `filedOn` is: a fixture card that never went
   * near the store is still a card, and a missing stage falls back to the
   * column's label rather than to a blank status line.
   */
  readonly stage?: CardStage;
  /**
   * The decision a person recorded on this card — `kanban-patrol/15`, decided
   * 2026-09-04. Present only once somebody has answered; absent, never an
   * empty string, the same rule `priorityReason`/`filedOn`/`stale` follow.
   *
   * It is what moves an answered judgement out of Needs You (`columnForCard`
   * reads it) and what `instructionForCard` puts at the top of the text an
   * agent is handed, so the judgement is settled before the work is read.
   */
  readonly answer?: string;
  /** Who decided. An unattributed decision is a rumour. */
  readonly answeredBy?: string;
  /**
   * The brief a card filed from a conversation carries —
   * `osg-agent-experience/25`.
   *
   * A patrol card justifies itself with the run thread behind it, which a
   * reader can go and open. A card filed out of a conversation cannot: the
   * chat is gone. So the want (`story`) and the check that settles it
   * (`doneWhen`) are written on the card at filing time, and the store
   * refuses a card without them.
   *
   * Absent, never an empty string — the same rule `priorityReason` and
   * `stale` follow, and load-bearing here for the same reason: the card
   * guards on the prop, so `''` would draw an empty line under every patrol
   * card's title.
   */
  readonly story?: string;
  readonly doneWhen?: string;
  /** The other cards this one waits on, as ids. Absent when it waits on none. */
  readonly blockedBy?: readonly string[];
  /**
   * What to give a subagent that takes this card. **Advisory**, and absent
   * whenever nobody had an opinion — never a default model name, which would
   * read on the board as a decision somebody made.
   */
  readonly agentModel?: string;
  readonly agentEffort?: string;
  /**
   * What the closing checks said when this card reached `finished` —
   * `osg-agent-experience/85`. Distinct from `evidenceRedReason`, which is why
   * the test failed at `red`: this is the verdict of the gate run at the end,
   * and until the store kept it the only place it could live was a file beside
   * the workflow. Absent on every card that never carried one.
   */
  readonly finishedReason?: string;
}

/**
 * A column's cards, in the order they arrived.
 *
 * `filter` and not a sort, and that is the entire function. Cards land one at
 * a time while a patrol runs, and the obvious *newest first* would re-order
 * the list under the reader's pointer on every arrival — a board nobody can
 * click, which is `06`'s own phrase for it. Append-only means whatever was
 * under the cursor is still under the cursor.
 */
export function cardsInColumn(
  cards: readonly BoardCard[],
  column: BoardColumnId,
): readonly BoardCard[] {
  // Derived, never read off the card — `18`. `columnForCard` is the one
  // place the mapping lives, so no surface can put a card somewhere its kind
  // and lifecycle do not.
  return cards.filter((card) => columnForCard(card) === column);
}
