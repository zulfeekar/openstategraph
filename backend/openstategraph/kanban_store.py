"""The kanban card store's stage machine — `kanban-patrol/19`.

## The story

You tell your coding agent to attend a card. It writes "I've got this" once.
If it crashes, loses network, or is just forgotten about, nothing ever writes
the *next* sentence — the card would say "In Progress" forever, and nobody
could tell "still working, slowly" from "abandoned three days ago" by reading
the same words.

This module is the one place both halves of that problem are made honest:

- **The claim is atomic.** Two claimants racing for one card is not a
  theoretical case (`kanban-patrol/13` already found a real one) — the write
  is a single conditional `UPDATE ... WHERE stage = ?`, never a
  read-then-check-then-write, because the latter passes every single-caller
  test and loses a card to whichever wrote last, with both callers believing
  they own it.
- **The lease has an implicit heartbeat and never auto-releases.** Every
  stage write refreshes `last_heartbeat_at` — no separate ping tool, which
  would be one more thing an agent's instructions must remember, and
  forgetting it would produce the exact bug this module exists to prevent.
  Past the threshold, `flagged_stale` says so; it never changes the card.
  Same discipline as `async_tasks.py`'s own `TaskStatus.UNKNOWN`: state the
  uncertainty, never guess it closed.

## What this module holds, and what it does not

`team-board-and-gap-reports/02` split the family into three. This module is the
**vocabulary and the rules**: what a card is, which column it is in, the order
the board is worked in, where the board lives, and the registry a store is
opened through. It contains no `sqlite3` and no `db_path`.

- `abc/kanban_store.py` — `IKanbanStore` and `AbstractKanbanStore`, which own
  every refusal and the stage machine itself.
- `kanban_sqlite.py` — `SqliteKanbanStore`, the one member the family has
  today, and the only module in the card path that knows what a file is.

The rules here are deliberately **not** on the interface: `triage`,
`column_for`, `card_row`, `flagged_stale` and `unresolved_blockers` are
functions over cards a store has already handed back, so a second store cannot
disagree with them.

No CLI, no MCP tool, no HTTP route either — those are thin adapters over
`open_kanban_store()`, so the claim/stage logic exists exactly once.
"""

from __future__ import annotations

import dataclasses
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any
from pathlib import Path

if TYPE_CHECKING:  # pragma: no cover - import cycle, types only
    from openstategraph.abc.kanban_store import IKanbanStore

#: `kanban-patrol/19`. Same shape as `run_sinks.RUN_STORE_PATH_ENV` — an
#: absolute override for a deployment whose write location genuinely differs
#: from `state_dir()`'s own default.
KANBAN_STORE_PATH_ENV = "OPENSTATEGRAPH_KANBAN_STORE_PATH"

#: Unsuffixed, deliberately — `kanban-patrol/19`'s locked decision.
#: `checkpoints-{slug}.sqlite` is keyed by *workflow slug*, one file per
#: workflow inside a project. `memory.sqlite`/`runs.sqlite` sit in the same
#: directory unsuffixed, one each, spanning every workflow in the project.
#: The kanban board is explicitly per-project and cross-workflow, so it
#: matches those two, not the per-workflow checkpoint pattern.
KANBAN_STORE_FILE_NAME = "kanban.sqlite"


@dataclass(frozen=True)
class KanbanLocation:
    """Where this project's board is, whether it is there, and what decided —
    `osg-agent-experience/65`.

    Filed because a board was reported *vanished* and nothing had been
    deleted. `list_cards` says it in its own docstring — "no store yet" and
    "store, no rows" mean the same thing to a reader — which is right for a
    library function returning a list and fatal for a door printing a
    sentence. Both facts a reader needs are here, so no door has to stat the
    file itself and no two doors can phrase the answer differently.
    """

    path: Path
    exists: bool
    source: str
    why: str


def kanban_store_location(workflows_root_dir: Path | str | None = None) -> KanbanLocation:
    """Where the kanban store lives, and whether it is there yet.

    The environment variable wins outright; otherwise
    `state_dir()/kanban.sqlite`, whose own three-branch chain is reported
    rather than re-implemented (`state_dir.resolve_state_dir`). Asking never
    creates anything — `state_dir`'s rule, which is what lets this be pointed
    at a read-only mount without writing to it first.
    """
    configured = os.environ.get(KANBAN_STORE_PATH_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        return KanbanLocation(
            path,
            path.is_file(),
            "environment",
            f"{KANBAN_STORE_PATH_ENV} is set in this environment",
        )

    from openstategraph.state_dir import resolve_state_dir

    choice = resolve_state_dir(workflows_root_dir)
    path = choice.path / KANBAN_STORE_FILE_NAME
    return KanbanLocation(path, path.is_file(), choice.source, choice.why)


def kanban_store_path(workflows_root_dir: Path | str | None = None) -> Path:
    """Where the kanban store lives. Defined as `kanban_store_location().path`
    so the address and the report of it cannot drift."""
    return kanban_store_location(workflows_root_dir).path


class Stage(str, Enum):
    UNATTENDED = "unattended"
    ATTENDED = "attended"
    RED = "red"
    GREEN = "green"
    FINISHED = "finished"


#: Stage only ever advances. `kanban-patrol/19`: a card reporting `green`
#: without ever having reported `red` is a claim this module refuses to
#: record, not a fact it trusts.
_ORDER = {stage: index for index, stage in enumerate(Stage)}


class StageOrderError(ValueError):
    """Raised for a transition this module refuses to record — backward, or
    skipping a stage. The caller's mistake, never silently accepted."""


class MissingEvidenceError(ValueError):
    """`kanban-patrol/17`+`21`. Raised for a red/green/finished transition
    that lacks the evidence this gate requires — a different refusal from
    `StageOrderError`: not the wrong stage to move from, but the right stage
    with nothing to point the proof at. Names exactly what is missing so the
    caller (human or agent) can fix it, never a generic failure.

    `kanban-patrol/15` reuses it for `answer_card`'s own blanks — an answer
    with nothing in it is the same defect the evidence gate already refuses,
    a write that records a field and says nothing, and a second exception
    class for one more spelling of "you gave me nothing" would be a second
    thing a caller has to catch to get the same handling."""


@dataclass(frozen=True)
class SetStageResult:
    ok: bool
    #: Populated only when `ok` is False — who already holds the card, and
    #: when. Never a silent overwrite; the loser is told, not guessed at.
    reason: str = ""


@dataclass(frozen=True)
class Card:
    task_id: str
    board: str
    kind: str
    category: str
    title: str
    stage: Stage
    actor: str | None
    last_heartbeat_at: str | None
    #: Patrol-minted, human-revised — `kanban-patrol/02`'s one deliberate
    #: exception to "the patrol's fields don't change on re-patrol": priority
    #: is the one axis a human is trusted to overwrite the patrol's guess on.
    priority: str
    area: str
    #: The plain-English *why*, written at classification time —
    #: kanban-patrol/25. Distinct from `cardPriority.ts`'s generic per-level
    #: sentence, which reads the same for every card at that level regardless
    #: of what actually happened. Empty when the classifier gave none.
    priority_reason: str
    #: A real timestamp, never a worded guess — the board computes its own
    #: relative phrase from this rather than being handed a stale one.
    filed_at: str
    #: `kanban-patrol/17`+`21`. The evidence gate's own fields — recorded at
    #: the actual red/green transitions, never re-typed at the end. Empty
    #: string / False when no evidence has been recorded yet.
    evidence_test_id: str
    evidence_red_reason: str
    evidence_green: bool
    evidence_commit: str
    #: `kanban-patrol/15`'s Answer — the decision a person typed onto a Needs
    #: You card, written once, with who typed it and when. Empty string when
    #: nobody has answered yet, never `None`: the same "one spelling of
    #: nothing" rule the four evidence fields above already follow.
    answer: str
    answered_by: str
    answered_at: str
    #: The brief an *idea* card carries — `osg-agent-experience/25`. A patrol
    #: card justifies itself with the run it was minted from; a card filed out
    #: of a conversation has no thread to point at, so the plain-English want
    #: and the check that settles it are written on the card at filing time or
    #: they are lost with the chat log. Empty on every patrol card, never
    #: `None`: the same one-spelling-of-nothing rule the evidence and answer
    #: fields above already keep.
    story: str = ""
    done_when: str = ""
    #: The other cards this one waits on, as ids. A tuple rather than the JSON
    #: text the column actually holds — the encoding is this module's business
    #: and nothing above it should have to know it, which is the same reason
    #: `evidence_green` is a `bool` here and an `INTEGER` there.
    blocked_by: tuple[str, ...] = ()
    #: What to give the subagent that takes this card. Advisory, and empty
    #: whenever nobody had an opinion — never a default model name invented
    #: here, which would read on the board as a decision somebody made.
    agent_model: str = ""
    agent_effort: str = ""
    #: `osg-agent-experience/85`. What the closing checks said, written at the
    #: `finished` transition and nowhere else. Last in the field order because
    #: it carries a default and the four evidence fields above it do not — not
    #: because it is a lesser piece of evidence: it is the one an agent's own
    #: gate produces, and until this field existed `set_stage` accepted it and
    #: dropped it. Empty string, never `None`, the same one-spelling-of-nothing
    #: rule every field above keeps.
    finished_reason: str = ""


#: `kanban-patrol/19`'s explicit Release lease, in seconds — one hour. Owned
#: here, beside `flagged_stale`, because the HTTP route and the MCP door both
#: ask this module the same question and a threshold spelled at each door is a
#: threshold that can differ between them.
STALE_THRESHOLD_SECONDS = 3600

#: The board's four columns, in board order — the ids
#: `src/view/board/patrolBoardModel.ts` declares. `test_kanban_store.py` pins
#: this tuple against that file: two spellings of one vocabulary in two
#: languages is exactly the drift that would surface as a filter reporting
#: "no such column" for a column a user is looking straight at.
BOARD_COLUMNS: tuple[str, ...] = ("detected", "needsYou", "inProgress", "resolved")

#: `src/view/board/cardPriority.ts`'s two unions, same pin.
BOARD_AREAS: tuple[str, ...] = ("ui", "ux", "frontend", "backend", "test", "docs")
BOARD_PRIORITIES: tuple[str, ...] = ("high", "med", "low")

#: The kinds that end in a judgement only a person may make —
#: `cardKind.ts`'s own `HUMAN_DECISION`, and the whole of what puts a card in
#: Needs You rather than Detected.
_HUMAN_DECISION_KINDS = frozenset({"prototype", "grilling", "decision"})


def column_for(card: Card) -> str:
    """Which of `BOARD_COLUMNS` this card is in.

    **Derived, never stored** — `kanban-patrol/18`'s rule, kept: a stored
    column could disagree with the kind, and the disagreement would put a
    judgement in the column an agent pulls work from.

    Lifecycle outranks kind, and that ordering is the design. A claimed
    `decision` leaves Needs You, because somebody is already answering it and
    leaving it there would invite a second person to answer it too. Only an
    unattended card is placed by its kind.

    This is the same function as `cardKind.ts`'s `columnForCard`, in the
    language the MCP door speaks. The board keeps its own because it maps a
    row it already has in the browser; nothing crosses the wire twice.
    """
    if card.stage is Stage.FINISHED:
        return "resolved"
    if card.stage is not Stage.UNATTENDED:
        return "inProgress"
    if card.kind not in _HUMAN_DECISION_KINDS:
        return "detected"
    # `kanban-patrol/15`, 2026-09-04: an **answered** judgement is a decided
    # one, so it leaves Needs You the same way a claimed one does. Needs You
    # is the column a person reads for outstanding questions; a card whose
    # question has been answered sitting in it is a claim that the question
    # is still open. It goes to Detected rather than to Resolved because a
    # decision is not evidence that anything was built — `17`'s gate is still
    # the only road there — and an agent can now attend it with the judgement
    # already made.
    return "detected" if card.answer.strip() else "needsYou"


def card_row(card: Card, *, stale: bool) -> dict[str, Any]:
    """One card as the flat row every read door publishes.

    One function rather than one per door: `GET /api/kanban/cards` builds its
    `KanbanCardResponse` from this, and the MCP `kanban_list_cards` /
    `kanban_show_card` answer with it directly (plus the derived `column`).
    Before it existed the route listed sixteen fields and the MCP door listed
    eight of them, so an agent and the board were reading two different cards
    with nothing to say which fields the smaller one had dropped.
    """
    return {
        "task_id": card.task_id,
        "board": card.board,
        "kind": card.kind,
        "category": card.category,
        "title": card.title,
        "stage": card.stage.value,
        "actor": card.actor,
        "priority": card.priority,
        "area": card.area,
        "priority_reason": card.priority_reason,
        "filed_at": card.filed_at,
        "evidence_test_id": card.evidence_test_id,
        "evidence_red_reason": card.evidence_red_reason,
        "evidence_green": card.evidence_green,
        "evidence_commit": card.evidence_commit,
        # `kanban-patrol/15`. Published on every row rather than only on an
        # answered one, for the reason this function exists at all: two doors
        # publishing different field sets is how a board and an agent come to
        # read different cards.
        "answer": card.answer,
        "answered_by": card.answered_by,
        "answered_at": card.answered_at,
        # `osg-agent-experience/25`. On every row, not only an idea card's,
        # for the reason this function exists: two doors publishing different
        # field sets is how a board and an agent come to read different cards.
        "story": card.story,
        "done_when": card.done_when,
        "blocked_by": list(card.blocked_by),
        "agent_model": card.agent_model,
        "agent_effort": card.agent_effort,
        # `osg-agent-experience/85`. On every row rather than only a finished
        # one, for the reason this function exists at all: two doors publishing
        # different field sets is how a board and an agent come to read
        # different cards.
        "finished_reason": card.finished_reason,
        "stale": stale,
    }


def now_iso() -> str:
    """One spelling of *now* for every card write — a heartbeat, a filing and
    an answer are stamped by the same clock, in the same format, whatever store
    they land in."""
    return datetime.now(timezone.utc).isoformat()


#: `osg-agent-experience/25`. Every idea card's id starts here, so a reader of
#: a board — or of a `--session-id` on a run — can tell a card somebody wanted
#: from a card the patrol found without opening either.
IDEA_PREFIX = "idea-"

#: The kinds an idea card may be filed as. Narrower than `cardKind.ts`'s six on
#: purpose: `research`, `prototype` and `decision` end in something this door
#: cannot state a done-when for, and a done-when is what `file_idea_card`
#: refuses a card without. A card that ends in a judgement is a `grilling`.
IDEA_KINDS: frozenset[str] = frozenset({"task", "bug", "grilling"})

_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")


def idea_task_id(project_id: str, title: str) -> str:
    """`<project_id>:idea-<slug>` — the id an idea card is filed under.

    Derived from the title rather than minted from a counter, so the same idea
    described twice is the same card and an agent can name one in
    `blocked_by` before it has filed it.

    A title with no word characters is **refused**, never slugged to nothing:
    `proj-a:idea-` is an id that two different titles would both mint, which
    is exactly the collision deriving the id from the title is meant to make
    impossible.
    """
    slug = _SLUG_SEPARATORS.sub("-", title.strip().lower()).strip("-")
    if not slug:
        raise ValueError(
            f"cannot file a card from title {title!r}: a title needs at least "
            "one letter or digit to make an id from"
        )
    return f"{project_id}:{IDEA_PREFIX}{slug}"


def resolve_blocked_by(
    project_id: str, blocked_by: Sequence[str], known_ids: frozenset[str]
) -> tuple[str, ...]:
    """The ids a `blocked_by` actually names — `osg-agent-experience/30`.

    A card id is `<project_id>:<name>`, and until this function existed the
    field took whatever string it was handed. The bare slug — the readable
    half of an id the CLI had just printed, and the obvious guess — was
    accepted and produced a blocker no card would ever carry: the blocked card
    stayed blocked after every real card on the board had finished, and the
    blocker lost the `unblocks N` credit that lifts it to the top.

    `CLAUDE.md`'s own rule, both halves. **Tolerant in reading**: a bare name
    is resolved against the board, as itself first (a patrol card's id is
    `<project>:<thread_id>` with no `idea-` in it) and then as an idea slug.
    **Strict in trusting**: a name that resolves to nothing is still
    normalised to the id that card *will* be given, never left as the half-id
    that can never match.

    Two shapes are refused outright, because no working of this board can ever
    clear them: a blank entry, and an id belonging to another project.

    An id this board does not carry *yet* is **not** refused. Filing a card
    that blocks on one not yet filed is a real ordering, and a board that
    cannot be filed into is worse than one that explains itself — so it is
    reported instead, by `unresolved_blockers` at both doors and by `triage`'s
    `why_here` on the board.
    """
    resolved: list[str] = []
    for raw in blocked_by:
        name = str(raw).strip()
        if not name:
            raise ValueError(
                "a blocked-by entry is blank — name the card it waits on, or "
                "pass no blocked-by at all"
            )
        if ":" in name:
            owner = name.split(":", 1)[0]
            if owner != project_id:
                raise ValueError(
                    f"blocked-by {name!r} names project {owner!r}; this board "
                    f"is project {project_id!r}, and a card in another project "
                    "is one this board can never see finish"
                )
            candidate = name
        else:
            qualified = f"{project_id}:{name}"
            as_idea = f"{project_id}:{IDEA_PREFIX}{name}"
            if qualified in known_ids:
                candidate = qualified
            elif as_idea in known_ids:
                candidate = as_idea
            elif name.startswith(IDEA_PREFIX):
                candidate = qualified
            else:
                candidate = as_idea
        if candidate not in resolved:
            resolved.append(candidate)
    return tuple(resolved)


_STAGE_SEQUENCE = list(Stage)


def required_previous_stage(stage: Stage) -> Stage:
    """The one stage a transition *to* `stage` must come from. Stage only
    ever advances one step at a time — this is the entire ordering rule,
    expressed once so every caller checks the same thing."""
    return _STAGE_SEQUENCE[_ORDER[stage] - 1]


@dataclass(frozen=True)
class TriageRow:
    """One card, ranked — `osg-agent-experience/25`. `rank` is 1-indexed
    position in the argued order `triage` returns; `why_here` is the one
    sentence naming which rule of that order put the card there, so a reader
    never has to reconstruct the order from the raw fields to trust it."""

    card: Card
    rank: int
    why_here: str


def triage(cards: Sequence[Card]) -> tuple[TriageRow, ...]:
    """The owner's pick-up-next order (decision 10), computed fresh from
    whatever cards are handed in — pure, no store, nothing to persist or
    drift (least-confident-decision 2 in `03-program-design.md`).

    A `finished` card is excluded outright: it is not work to pick up. Its
    presence in some other card's `blocked_by` is also spent — a card that
    was waiting only on work that has since finished is unblocked, the same
    way `column_for` already treats a decided judgement as no longer
    outstanding.

    The order, in one pass:
    1. **Unblocked cards that block others**, most dependents first — the
       card whose done-when unlocks the most other work is worth doing
       before a card nothing is waiting on, regardless of either one's
       priority. **Dependents are counted to the end of the chain**
       (`osg-agent-experience/66`): A <- B <- C ranked A first and said
       `unblocks 1 card`, when nothing else on that board could start until A
       landed. Both the order and the sentence use the transitive count, and
       the sentence names the direct one too whenever they differ.
    2. **Unblocked cards that block nothing**, by priority (high, med, low).
    3. **Blocked cards, last**, in the *same* sub-order as 1+2 combined —
       dependents first, priority second — so a blocked card that itself
       unblocks a chain still sorts ahead of a blocked card nobody is
       waiting on, even though neither can be picked up yet.

    `why_here` names exactly one of those three rules: "unblocks N cards"
    (or "unblocks N cards directly, M in all" when the chain runs deeper than
    one hop), "<priority> priority, nothing waits on it", or "blocked by
    <ids>" — and the third distinguishes a blocker that is a card on this
    board from one no card carries (`osg-agent-experience/30`), because only
    the first of those two clears by working the board.
    """
    live = [card for card in cards if card.stage is not Stage.FINISHED]
    finished_ids = {card.task_id for card in cards if card.stage is Stage.FINISHED}
    known_ids = {card.task_id for card in cards}

    def outstanding_blockers(card: Card) -> tuple[str, ...]:
        return tuple(b for b in card.blocked_by if b not in finished_ids)

    dependents: dict[str, list[str]] = {card.task_id: [] for card in live}
    for card in live:
        for blocker in outstanding_blockers(card):
            if blocker in dependents:
                dependents[blocker].append(card.task_id)

    def all_dependents(task_id: str) -> set[str]:
        """Every live card that cannot start until this one lands, at any
        depth — `osg-agent-experience/66`.

        A chain A <- B <- C ranked A first and printed `unblocks 1 card`. The
        order was right and the only evidence offered for it understated the
        case by two thirds, which is a reader's cue to take the `high`
        priority card nothing waits on instead.

        The walk is breadth-first with a `seen` set, and the set is a cycle
        guard rather than an optimisation: `blocked_by` is free text resolved
        against the board, nothing on the write path refuses A <- B <- A, and
        a walk that trusts the graph is acyclic hangs the door. The origin is
        excluded at the end because reachability from a card inside a cycle
        includes the card, and "unblocks itself" is not a fact about a board.
        """
        seen: set[str] = {task_id}
        frontier = list(dependents.get(task_id, ()))
        while frontier:
            nxt = frontier.pop()
            if nxt in seen:
                continue
            seen.add(nxt)
            frontier.extend(dependents.get(nxt, ()))
        return seen - {task_id}

    reachable = {card.task_id: all_dependents(card.task_id) for card in live}

    def priority_rank(card: Card) -> int:
        try:
            return BOARD_PRIORITIES.index(card.priority)
        except ValueError:
            return len(BOARD_PRIORITIES)

    def sort_key(card: Card) -> tuple[int, int, str]:
        # Most dependents first (negated for ascending sort), then priority,
        # then title for a stable, readable tie-break. Transitive, and the
        # same number `why_here` prints: an order computed from one count and
        # justified by another is worse than either alone
        # (`osg-agent-experience/66`).
        return (-len(reachable[card.task_id]), priority_rank(card), card.title)

    unblocked = [c for c in live if not outstanding_blockers(c)]
    blocked = [c for c in live if outstanding_blockers(c)]
    ordered = sorted(unblocked, key=sort_key) + sorted(blocked, key=sort_key)

    rows = []
    for rank, card in enumerate(ordered, start=1):
        blockers = outstanding_blockers(card)
        n_dependents = len(dependents[card.task_id])
        n_reachable = len(reachable[card.task_id])
        if blockers:
            # `osg-agent-experience/30`: "blocked by X" read the same whether
            # X is a card somebody will finish or an id nothing carries, and
            # only one of those two clears by working the board.
            carried = tuple(b for b in blockers if b in known_ids)
            phantom = tuple(b for b in blockers if b not in known_ids)
            phrase = f"an id no card carries: {', '.join(phantom)}"
            if carried and phantom:
                why_here = f"blocked by {', '.join(carried)}, and by {phrase}"
            elif phantom:
                why_here = f"blocked by {phrase}"
            else:
                why_here = f"blocked by {', '.join(carried)}"
        elif n_reachable:
            # One number when the two agree — a clause that always says the
            # same thing is a clause a reader stops reading — and both when
            # they do not, because "unblocks 4 cards" for a card one thing
            # waits on directly is its own kind of misreport.
            plural = "card" if n_dependents == 1 else "cards"
            why_here = f"unblocks {n_dependents} {plural}"
            if n_reachable != n_dependents:
                why_here = f"unblocks {n_dependents} {plural} directly, {n_reachable} in all"
        else:
            why_here = f"{card.priority} priority, nothing waits on it"
        rows.append(TriageRow(card=card, rank=rank, why_here=why_here))
    return tuple(rows)


@dataclass(frozen=True)
class CardEvidence:
    """The five fields a stage write carries, as one value.

    `team-board-and-gap-reports/02`: `AbstractKanbanStore` decides what the
    evidence *becomes* and a store writes it, so the two need one thing to pass
    between them. A record rather than five parameters because they are read
    and written together at every stage and a sixth would otherwise mean five
    signatures changing in four places — which is exactly how
    `osg-agent-experience/85`'s `finished_reason` would have been forgotten
    somewhere.
    """

    test_id: str = ""
    red_reason: str = ""
    green: bool = False
    commit: str = ""
    finished_reason: str = ""

    def replace(self, **changes: object) -> "CardEvidence":
        return dataclasses.replace(self, **changes)  # type: ignore[arg-type]


def unresolved_blockers(store: "IKanbanStore", card: Card) -> tuple[str, ...]:
    """The ids on `card.blocked_by` that no card on the store carries —
    `osg-agent-experience/30`'s "reported at filing time, naming it".

    Read-only, and a **rule** rather than a store method
    (`team-board-and-gap-reports/02`): it is a set difference over cards the
    store has already handed back, so the CLI and the MCP tool cannot report
    different things and a second store cannot answer it its own way. An empty
    board leaves every blocker on the card unresolved, which is the honest
    answer for a project whose board has never been filed into.
    """
    if not card.blocked_by:
        return ()
    known = {existing.task_id for existing in store.list_cards()}
    return tuple(blocker for blocker in card.blocked_by if blocker not in known)


def flagged_stale(store: "IKanbanStore", *, threshold_seconds: int) -> list[str]:
    """Cards whose last heartbeat is older than the threshold. Read-only —
    flags, never releases. `kanban-patrol/19`: a human presses Release
    themselves; this must never change a row, only report on it.

    Two stages are excluded, and for the same reason at both ends of the
    lifecycle: staleness is about an abandoned *claim*.

    - An `unattended` card has no claim to abandon.
    - A `finished` card's claim was not abandoned, it was *discharged*
      (`kanban-patrol/32`). Nobody writes to a resolved card again, which is
      what resolved means, so its heartbeat is older than any threshold within
      the hour — and flagging it offered `release_card`, the one control that
      empties every evidence field, on the one column that is read-only.

    A **rule**, not a store method (`team-board-and-gap-reports/02`): the API
    row's `stale`, the CLI's `kanban release` and the MCP `kanban_release_card`
    all read it, and a threshold or an exclusion spelled at one door is one the
    other two do not have. An empty board is an empty answer, never a crash.
    """
    now = datetime.now(timezone.utc)
    stale: list[str] = []
    for card in store.list_cards():
        if card.stage in (Stage.UNATTENDED, Stage.FINISHED):
            continue
        if not card.last_heartbeat_at:
            continue
        age = (now - datetime.fromisoformat(card.last_heartbeat_at)).total_seconds()
        if age > threshold_seconds:
            stale.append(card.task_id)
    return stale


#: `team-board-and-gap-reports/02`, and the owner's round-2 decision: a
#: **separate** variable for the team board. The checkpointer's
#: `OPENSTATEGRAPH_POSTGRES_URL` is never reused for cards — one URL doing two
#: jobs is one mistake away from a project's checkpoints and its board being
#: the same database by accident.
KANBAN_URL_ENV = "OPENSTATEGRAPH_KANBAN_URL"


class KanbanStoreRegistry:
    """Which implementation opens which kind of address.

    `CLAUDE.md`'s registry behaviour, the same shape as
    `search_backends.SearchBackendRegistry`: a duplicate scheme raises (two
    claims on one name is ambiguity, not precedence), `upsert` is how a caller
    says it meant to replace one, `list()` enumerates, and a fresh instance is
    always constructible so a test's registrations never leak into another
    test's.

    The openers live in their own modules and are imported here, never defined
    here — `test_a_dispatch_table_does_not_hold_its_targets.py` stays at zero,
    which is `CLAUDE.md`'s **O** as a test: extend by registering, never by
    editing the engine.
    """

    def __init__(self) -> None:
        self._openers: dict[str, Callable[[str], "IKanbanStore"]] = {}

    def register(self, scheme: str, opener: Callable[[str], "IKanbanStore"]) -> None:
        if scheme in self._openers:
            raise ValueError(
                f'A kanban store is already registered for "{scheme}". Two claims '
                "on one scheme is ambiguity, not precedence — use upsert() if you "
                "meant to replace it."
            )
        self._openers[scheme] = opener

    def upsert(self, scheme: str, opener: Callable[[str], "IKanbanStore"]) -> None:
        self._openers[scheme] = opener

    def get(self, scheme: str) -> "Callable[[str], IKanbanStore] | None":
        return self._openers.get(scheme)

    def list(self) -> tuple[str, ...]:
        return tuple(self._openers)


def default_kanban_store_registry() -> KanbanStoreRegistry:
    """SQLite today; `team-board-and-gap-reports/03` registers Postgres beside
    it and edits nothing else. A fresh registry per call — no module-level
    singleton, so a test that mutates one instance cannot affect another."""
    from openstategraph.kanban_sqlite import open_sqlite_kanban_store

    registry = KanbanStoreRegistry()
    registry.register("sqlite", open_sqlite_kanban_store)
    return registry


def open_kanban_store(
    workflows_root_dir: Path | str | None = None,
    *,
    registry: KanbanStoreRegistry | None = None,
) -> "IKanbanStore":
    """This project's board — the one door every consumer opens.

    `OPENSTATEGRAPH_KANBAN_URL` decides which implementation, by the scheme it
    names; unset means this laptop's own `kanban.sqlite`, whose address
    `kanban_store_location` resolves and reports. A scheme nothing is
    registered for is refused **by name**, naming the variable that set it and
    what is registered — a board silently falling back to a local file when the
    shared one was asked for is the failure nobody would notice until two
    people disagreed about what the board said.

    Asking never creates anything: a store is opened lazily and a read of a
    board that has never been filed into is an empty board, not a new one.
    """
    registry = default_kanban_store_registry() if registry is None else registry
    url = os.environ.get(KANBAN_URL_ENV, "").strip()
    if not url:
        return registry_opener(registry, "sqlite")(
            f"sqlite:///{kanban_store_path(workflows_root_dir)}"
        )
    scheme = url.split("://", 1)[0].strip().lower()
    return registry_opener(registry, scheme, url_env=True)(url)


def registry_opener(
    registry: KanbanStoreRegistry, scheme: str, *, url_env: bool = False
) -> "Callable[[str], IKanbanStore]":
    """The refusal, worded once so both branches of `open_kanban_store` say the
    same thing about a scheme nothing claims."""
    opener = registry.get(scheme)
    if opener is not None:
        return opener
    known = ", ".join(registry.list()) or "none"
    source = f"{KANBAN_URL_ENV} names" if url_env else "this build asked for"
    raise ValueError(
        f"{source} a {scheme!r} kanban store, and nothing is registered for that "
        f"scheme (registered: {known}). A board that quietly fell back to a local "
        "file would be two people disagreeing about what the board says."
    )
