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

## What this module deliberately does not do

No CLI, no MCP tool, no HTTP route — those are thin adapters over `set_stage`
and `read_card`, built separately, so the claim/stage logic exists exactly
once.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from collections.abc import Sequence
from typing import Any
from pathlib import Path

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


def kanban_store_path(workflows_root_dir: Path | str | None = None) -> Path:
    """Where the kanban store lives. The environment variable wins outright;
    otherwise `state_dir()/kanban.sqlite` — asking never creates anything,
    `state_dir`'s own rule, which is what lets this be pointed at a
    read-only mount without writing to it first."""
    configured = os.environ.get(KANBAN_STORE_PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    from openstategraph.state_dir import state_dir

    return state_dir(workflows_root_dir) / KANBAN_STORE_FILE_NAME


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
        "stale": stale,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


#: Every column this schema declares, past `CREATE TABLE`'s own reach once a
#: store already exists — kanban-patrol/26. One source for both: the
#: `CREATE TABLE` above (a fresh store) and the repair loop below (an old
#: one), so a column added to one is never forgotten in the other.
_COLUMN_DEFS: dict[str, str] = {
    "stage": "TEXT NOT NULL DEFAULT 'unattended'",
    "actor": "TEXT",
    "last_heartbeat_at": "TEXT",
    "priority": "TEXT NOT NULL DEFAULT 'med'",
    "area": "TEXT NOT NULL DEFAULT 'backend'",
    "priority_reason": "TEXT NOT NULL DEFAULT ''",
    "filed_at": "TEXT NOT NULL DEFAULT ''",
    "evidence_test_id": "TEXT NOT NULL DEFAULT ''",
    "evidence_red_reason": "TEXT NOT NULL DEFAULT ''",
    "evidence_green": "INTEGER NOT NULL DEFAULT 0",
    "evidence_commit": "TEXT NOT NULL DEFAULT ''",
    "answer": "TEXT NOT NULL DEFAULT ''",
    "answered_by": "TEXT NOT NULL DEFAULT ''",
    "answered_at": "TEXT NOT NULL DEFAULT ''",
    # `osg-agent-experience/25`. Declared only here, not also in the
    # `CREATE TABLE` below: the repair loop runs on a freshly created store
    # too, so one declaration covers both cases and the older columns'
    # duplication is history rather than a pattern to extend.
    "story": "TEXT NOT NULL DEFAULT ''",
    "done_when": "TEXT NOT NULL DEFAULT ''",
    "blocked_by": "TEXT NOT NULL DEFAULT ''",
    "agent_model": "TEXT NOT NULL DEFAULT ''",
    "agent_effort": "TEXT NOT NULL DEFAULT ''",
}


def ensure_schema(db_path: Path) -> None:
    """Build the store if it does not exist; repair it, column by column, if
    it does — kanban-patrol/26.

    The story this closes: the old version only knew "build one if there's
    none," so a store made before a column existed was left exactly as it
    was, and the next read of that column crashed. This asks each declared
    column for itself and adds whatever is missing — per-column, additive
    only, deliberately not a versioned migration list: every change this
    schema has needed so far has been "add a column," never a rename, and
    the fuller machinery would solve a problem that has not happened yet.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                task_id TEXT PRIMARY KEY,
                board TEXT NOT NULL,
                kind TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'unattended',
                actor TEXT,
                last_heartbeat_at TEXT,
                priority TEXT NOT NULL DEFAULT 'med',
                area TEXT NOT NULL DEFAULT 'backend',
                priority_reason TEXT NOT NULL DEFAULT '',
                filed_at TEXT NOT NULL,
                evidence_test_id TEXT NOT NULL DEFAULT '',
                evidence_red_reason TEXT NOT NULL DEFAULT '',
                evidence_green INTEGER NOT NULL DEFAULT 0,
                evidence_commit TEXT NOT NULL DEFAULT '',
                answer TEXT NOT NULL DEFAULT '',
                answered_by TEXT NOT NULL DEFAULT '',
                answered_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        existing = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
        for column, definition in _COLUMN_DEFS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE cards ADD COLUMN {column} {definition}")
        conn.commit()
    finally:
        conn.close()


def file_card(
    db_path: Path,
    *,
    task_id: str,
    board: str,
    kind: str,
    category: str,
    title: str,
    priority: str = "med",
    area: str = "backend",
    priority_reason: str = "",
) -> None:
    """The patrol's write. `kanban-patrol/02`: once a card leaves
    `unattended`, a re-patrol must never touch it again — enforced by the
    caller, not here; this is the initial file only, `INSERT OR IGNORE` so a
    second patrol filing the same `task_id` is a no-op rather than an error.

    `priority`/`area` default rather than require an argument at every call
    site that does not yet have an opinion — `test_kanban_store.py`'s own
    body of tests predates this field and files cards through it constantly;
    a real patrol (`07`/`08`) is expected to always pass both explicitly.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO cards
                (task_id, board, kind, category, title, stage, priority, area,
                 priority_reason, filed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id, board, kind, category, title, Stage.UNATTENDED.value,
                priority, area, priority_reason, _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


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


def _decode_blocked_by(raw: str | None) -> tuple[str, ...]:
    """The JSON list the column holds, as ids. Tolerant in reading and strict
    in trusting, `CLAUDE.md`'s own rule: a blank column, a store written before
    the column existed and a value that is not a JSON list all mean "no
    blockers" rather than a crash on a read of somebody else's board."""
    if not raw:
        return ()
    try:
        loaded = json.loads(raw)
    except ValueError:
        return ()
    if not isinstance(loaded, list):
        return ()
    return tuple(str(item) for item in loaded if str(item).strip())


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


def file_idea_card(
    db_path: Path,
    *,
    project_id: str,
    kind: str,
    title: str,
    story: str,
    done_when: str,
    priority: str,
    priority_reason: str,
    area: str = "backend",
    actor: str = "",
    blocked_by: Sequence[str] = (),
    agent_model: str = "",
    agent_effort: str = "",
) -> str:
    """File a card out of a conversation — `osg-agent-experience/25`. Returns
    its `task_id`.

    **Not `file_card` with more arguments.** That one writes what a patrol
    found, and its whole justification is the run thread behind it, which any
    later reader can go and look at. This one writes what somebody *said they
    wanted*, and the chat log it came from is not a thing the next reader can
    open. So the brief is required here and defaulted there: an empty `story`
    is precisely the shape the lost conversation would take on the card.

    **And it refuses a duplicate rather than ignoring it.** `file_card` uses
    `INSERT OR IGNORE`, which is right for a patrol re-run — the same finding
    seen again is the same card. Here a collision means two different ideas
    were given one title, and silently keeping the first would lose the
    second with nothing said. The caller renames.

    `actor` is who filed it, and it goes in the same column a claimant's name
    goes in — the card is still `unattended`, so the first `attend` overwrites
    it with whoever takes the work, which is the honest reading of that column
    either way: the person this card is currently with. Over MCP the string
    arriving here is the server's own finding rather than the model's claim
    (`kanban-patrol/29`); over the CLI it is the shell's, `20`'s stated floor.
    """
    if kind not in IDEA_KINDS:
        raise ValueError(
            f"kind {kind!r} is not one this door files — use one of "
            f"{', '.join(sorted(IDEA_KINDS))}"
        )
    if priority not in BOARD_PRIORITIES:
        raise ValueError(
            f"priority {priority!r} is not one of {', '.join(BOARD_PRIORITIES)}"
        )
    if area not in BOARD_AREAS:
        raise ValueError(f"area {area!r} is not one of {', '.join(BOARD_AREAS)}")
    for name, value in (
        ("story", story),
        ("done_when", done_when),
        ("priority_reason", priority_reason),
    ):
        if not value.strip():
            raise ValueError(
                f"{name} is empty — a card filed from a conversation carries "
                "its brief or the brief is lost with the conversation"
            )

    task_id = idea_task_id(project_id, title)
    ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        existing = conn.execute(
            "SELECT title FROM cards WHERE task_id = ?", (task_id,)
        ).fetchone()
        if existing is not None:
            raise ValueError(
                f"{task_id} already exists ({existing[0]!r}) — two ideas cannot "
                "share one title; name this one differently"
            )
        conn.execute(
            """
            INSERT INTO cards
                (task_id, board, kind, category, title, stage, actor, priority,
                 area, priority_reason, filed_at, story, done_when, blocked_by,
                 agent_model, agent_effort)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id, "workflows", kind, "idea", title.strip(),
                Stage.UNATTENDED.value, actor.strip() or None,
                priority, area, priority_reason.strip(),
                _now(), story.strip(), done_when.strip(),
                json.dumps([str(item) for item in blocked_by]),
                agent_model.strip(), agent_effort.strip(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return task_id


_CARD_COLUMNS = (
    "task_id, board, kind, category, title, stage, actor, last_heartbeat_at, "
    "priority, area, priority_reason, filed_at, "
    "evidence_test_id, evidence_red_reason, evidence_green, evidence_commit, "
    "answer, answered_by, answered_at, "
    "story, done_when, blocked_by, agent_model, agent_effort"
)


def _row_to_card(row: tuple[Any, ...]) -> Card:
    return Card(
        task_id=row[0],
        board=row[1],
        kind=row[2],
        category=row[3],
        title=row[4],
        stage=Stage(row[5]),
        actor=row[6],
        last_heartbeat_at=row[7],
        priority=row[8],
        area=row[9],
        priority_reason=row[10],
        filed_at=row[11],
        evidence_test_id=row[12],
        evidence_red_reason=row[13],
        evidence_green=bool(row[14]),
        evidence_commit=row[15],
        answer=row[16],
        answered_by=row[17],
        answered_at=row[18],
        story=row[19],
        done_when=row[20],
        blocked_by=_decode_blocked_by(row[21]),
        agent_model=row[22],
        agent_effort=row[23],
    )


def read_card(db_path: Path, task_id: str) -> Card:
    if not db_path.is_file():
        # No store yet means no card yet — the same "no record of that"
        # honesty `async_tasks.py`'s `TaskStatus.UNKNOWN` names, not a crash
        # over a transport a caller cannot otherwise distinguish from a
        # genuine miss.
        raise KeyError(task_id)
    # `kanban-patrol/17`+`21` found this live: a store built before this
    # column set existed (only `patrol.run_patrol` called `ensure_schema`
    # directly) crashed every later read with "no such column" rather than
    # being repaired. Guarded on `is_file()` so this never *creates* a store
    # on a mere read — same rule the check above already holds — only
    # repairs one that is already there, same repair loop `26` already
    # wrote for exactly this situation.
    ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {_CARD_COLUMNS} FROM cards WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise KeyError(task_id)
    return _row_to_card(row)


_STAGE_SEQUENCE = list(Stage)


def _required_previous(stage: Stage) -> Stage:
    """The one stage a transition *to* `stage` must come from. Stage only
    ever advances one step at a time — this is the entire ordering rule,
    expressed once so every caller checks the same thing."""
    return _STAGE_SEQUENCE[_ORDER[stage] - 1]


def _require_matching_test_id(
    task_id: str, stage_word: str, test_id: str, recorded: str
) -> None:
    """The one sentence `green` and `finished` both need when a supplied
    `test_id` disagrees with the one recorded at `red` — `kanban-patrol/33`
    found `finished` reading this same parameter and silently ignoring it.
    A blank `test_id` is not a mismatch here; callers that require one
    non-blank (`green`) check that separately before calling this."""
    if test_id and test_id != recorded:
        raise MissingEvidenceError(
            f"{task_id}: {stage_word} test_id {test_id!r} does not match the "
            f"red test_id {recorded!r} recorded on this card"
        )


def set_stage(
    db_path: Path,
    task_id: str,
    stage: Stage,
    *,
    actor: str,
    test_id: str = "",
    reason: str = "",
    commit: str = "",
) -> SetStageResult:
    """The one write path.

    **Attend (`stage == ATTENDED`) is a race, not a logic error** — two
    coding agents legitimately racing for one card is `kanban-patrol/13`'s own
    finding, so a conflict here is reported through `SetStageResult.ok`, told
    plainly who won, never raised.

    **Every later transition (red/green/finished) is a logic error, not a
    race** — only the actor that already holds the card advances it, so a
    mismatch there (skipping a stage, moving backward) is the caller's own
    mistake and raises `StageOrderError` rather than being folded into `ok`.

    **Atomic against the database, not against a value read a moment ago:**
    the `WHERE` clause names the *required* previous stage literally — never
    `current.stage.value` captured earlier — which is what makes this a
    single conditional `UPDATE` rather than the read-then-write shape that
    passes every single-caller test and loses a real race.

    **`kanban-patrol/17`+`21`: the evidence gate.** Checked before the atomic
    UPDATE, same as the stage-order check above — a card only reaches `red`
    with a test id and a reason, only reaches `green` with the *same* test
    id already recorded at `red`, and only reaches `finished` once red and
    green are both already durably on the row. `MissingEvidenceError` names
    exactly what is absent; it is never folded into `ok` because — like
    `StageOrderError` — it is the caller's own mistake, not a race.
    """
    if not actor.strip():
        # `kanban-patrol/20`: the floor, not full identity. The CLI's trust
        # boundary is the shell it runs in — a deliberate, stated decision,
        # not an oversight. The MCP door is no longer in the same position:
        # `29` resolves the caller through `IPrincipals` before this is
        # called, so on a deployment that identifies its callers the string
        # arriving here is the server's own finding rather than the model's
        # claim. (This comment said the installed library exposed no request
        # context at all; `28` found that it does, at
        # `RequestContext.request`.) Either way "already attended by " with
        # nothing in the blank is meaningless to a human reading the card,
        # so the floor stands: an actor must be a real, non-blank string.
        raise MissingEvidenceError(f"{task_id}: actor must be a real, non-blank name")

    current = read_card(db_path, task_id)
    required_previous = _required_previous(stage)

    if stage == Stage.ATTENDED:
        # Attend is a race only between UNATTENDED (fresh) and ATTENDED
        # (someone else just won it) — either is a legitimate concurrent
        # outcome, told through `ok`, never raised. Anything already past
        # attended (red/green/finished) is not a race at all: it is moving
        # backward on a card the actor already progressed, a logic error.
        if current.stage not in (Stage.UNATTENDED, Stage.ATTENDED):
            raise StageOrderError(
                f"{task_id}: cannot move from {current.stage.value} back to "
                f"{stage.value} — stage only ever advances"
            )
    elif stage == Stage.FINISHED:
        # Ordering for `finished` is enforced by the evidence check below,
        # not here: `evidence_green` can only be True once a `green`
        # transition has actually happened, and a `green` transition can
        # only happen after `red` — so a complete-evidence check already
        # implies the correct stage was reached. Checking literal order
        # here as well would reject `test_finished_without_evidence_is_refused`
        # (red -> finished, skipping green) with the wrong exception:
        # `StageOrderError` rather than the more specific `MissingEvidenceError`
        # this gate exists to raise.
        pass
    elif current.stage != required_previous:
        raise StageOrderError(
            f"{task_id}: cannot move from {current.stage.value} to {stage.value} "
            "— stage only ever advances, one step at a time"
        )

    evidence_test_id = current.evidence_test_id
    evidence_red_reason = current.evidence_red_reason
    evidence_green = current.evidence_green
    evidence_commit = current.evidence_commit

    # `kanban-patrol/17`+`21`, hardened: `.strip()` before every truthiness
    # check below, everywhere evidence is read as a string — a confirmed
    # real bug otherwise, the same shape as the blank-actor gap `20` already
    # closed. `bool(" ")` is `True` in Python, so `reason=" "` passed this
    # gate silently until this fix; a whitespace string is exactly as
    # meaningless as an empty one to anyone reading a card's evidence.
    test_id = test_id.strip()
    reason = reason.strip()
    commit = commit.strip()

    if stage == Stage.RED:
        if not test_id:
            raise MissingEvidenceError(f"{task_id}: red requires test_id")
        if not reason:
            raise MissingEvidenceError(f"{task_id}: red requires reason")
        evidence_test_id = test_id
        evidence_red_reason = reason
    elif stage == Stage.GREEN:
        if not test_id:
            raise MissingEvidenceError(f"{task_id}: green requires test_id")
        _require_matching_test_id(task_id, "green", test_id, current.evidence_test_id)
        evidence_green = True
    elif stage == Stage.FINISHED:
        # `kanban-patrol/33`: `test_id` is optional at `finished` — the
        # recorded id from `red`/`green` is the evidence — but when an
        # agent does supply one it is checked against that recorded id with
        # the same wording `green` uses, rather than being read for
        # `commit` alone and silently dropped.
        _require_matching_test_id(task_id, "finished", test_id, current.evidence_test_id)
        # `kanban-patrol/17`'s own bar names four things, not three — "the
        # commit or diff that carries the work" is the fourth, and it was
        # optional here until this fix let a card reach Resolved without
        # ever naming what actually changed.
        missing = []
        if not current.evidence_test_id:
            missing.append("test_id")
        if not current.evidence_red_reason:
            missing.append("red reason")
        if not current.evidence_green:
            missing.append("green")
        if not commit:
            missing.append("commit")
        if missing:
            raise MissingEvidenceError(
                f"{task_id}: finished requires evidence — missing {', '.join(missing)}"
            )
        evidence_commit = commit

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE cards
            SET stage = ?, actor = ?, last_heartbeat_at = ?,
                evidence_test_id = ?, evidence_red_reason = ?,
                evidence_green = ?, evidence_commit = ?
            WHERE task_id = ? AND stage = ?
            """,
            (
                stage.value, actor, _now(),
                evidence_test_id, evidence_red_reason,
                int(evidence_green), evidence_commit,
                task_id, required_previous.value,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if cursor.rowcount == 0:
        if stage != Stage.ATTENDED:
            # A concurrent second advance of an already-progressed card is
            # not a race this schema allows at all (only the holder calls
            # these) — treat it the same as any other order violation.
            raise StageOrderError(
                f"{task_id}: cannot move to {stage.value} — card is no longer at "
                f"{required_previous.value}"
            )
        # Lost the attend race between the read above and this write —
        # reread to report who actually holds it, truthfully.
        loser_view = read_card(db_path, task_id)
        return SetStageResult(
            ok=False,
            reason=f"already attended by {loser_view.actor} — card is at {loser_view.stage.value}",
        )
    return SetStageResult(ok=True)


def release_card(
    db_path: Path, task_id: str, *, threshold_seconds: int = 3600
) -> SetStageResult:
    """The human half of "flag, never auto-release" — `kanban-patrol/19`.

    `flagged_stale` only ever reports; nothing writes on its own. This is the
    one function a human's own explicit press calls, and it is guarded twice:

    - **A card must already be flagged.** `task_id` is checked against
      `flagged_stale`'s own list first — a human can only release what the
      system has already named as stale, never an arbitrary active card by
      accident. This is the exact discipline that keeps "a human decides"
      honest even once a Release button exists: the button cannot invent
      staleness, only act on what was already found.
    - **Atomic against the database, same discipline as `set_stage`.** The
      `UPDATE`'s `WHERE` clause still guards `stage != 'unattended'` — a
      genuine resume between the `flagged_stale` check above and this write
      (someone else's `set_stage` call landing first) must not be silently
      clobbered. Zero rows affected is treated exactly like "no longer
      stale," reported through `SetStageResult`, never raised.

    A successful release resets the row to a fresh, unattended state —
    `stage`, `actor`, `last_heartbeat_at`, and all four evidence fields all
    the way back to their filed-but-never-attended defaults — so the card
    looks exactly as if nobody had ever touched it. A partial reset would
    leave stale evidence to bleed into whoever attends next, which is the
    same bug this module already refuses at the `red`/`green` evidence gate,
    just at the opposite end of the lifecycle.
    """
    if task_id not in flagged_stale(db_path, threshold_seconds=threshold_seconds):
        return SetStageResult(
            ok=False,
            reason=f"{task_id}: not stale — a card can only be released once it has been flagged",
        )

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE cards
            SET stage = ?, actor = NULL, last_heartbeat_at = NULL,
                evidence_test_id = '', evidence_red_reason = '',
                evidence_green = 0, evidence_commit = ''
            WHERE task_id = ? AND stage != ?
            """,
            (Stage.UNATTENDED.value, task_id, Stage.UNATTENDED.value),
        )
        conn.commit()
    finally:
        conn.close()

    if cursor.rowcount == 0:
        # Someone else's `set_stage` genuinely won the race between the
        # `flagged_stale` read above and this write — reported the same
        # honest way, never a silent clobber of whoever is now resuming.
        return SetStageResult(
            ok=False,
            reason=f"{task_id}: not stale — a card can only be released once it has been flagged",
        )
    return SetStageResult(ok=True)


def answer_card(
    db_path: Path, task_id: str, *, actor: str, answer: str
) -> SetStageResult:
    """Record the decision a person made on a Needs You card —
    `kanban-patrol/15`, the owner's decision of 2026-09-04.

    **The card goes back to Detected, never to Resolved.** A decision is not
    evidence that anything was built, so `17`'s gate is still the only road
    to Resolved; and the card must not stay in Needs You either, because that
    is the column a person reads for outstanding questions. `column_for` does
    the move on its own, from the answer this writes — no second stored
    column, the same `18` rule the rest of this module keeps.

    **One write path, and it writes once.** The stage is untouched: the card
    is still `unattended`, so an agent attends it next exactly as it would
    any Detected card. Two refusals and one loss:

    - A blank actor or a blank answer is `MissingEvidenceError` — the
      caller's own mistake, named, never recorded as a decision nobody made.
      `.strip()` first, because `bool(" ")` is `True`.
    - A card that is not a judgement waiting in Needs You is
      `StageOrderError`: a `bug` was never in question, and a claimed
      judgement already has somebody on it.
    - A **second** answer is a race, not a mistake — two people reading one
      board and both deciding is ordinary — so it is reported through
      `SetStageResult.ok` naming who answered first, exactly as a lost
      attend is, and the first decision stands.

    **Atomic against the database, not against the read above.** The
    `WHERE` clause requires the answer to still be blank and the card to
    still be unattended, so two callers that both read a blank answer do not
    both write one — the same discipline `set_stage` uses, and the reason
    this is a conditional `UPDATE` rather than a read-then-write.
    """
    if not actor.strip():
        raise MissingEvidenceError(f"{task_id}: actor must be a real, non-blank name")
    answer = answer.strip()
    if not answer:
        raise MissingEvidenceError(f"{task_id}: answer must be a real, non-blank decision")

    current = read_card(db_path, task_id)
    if current.answer.strip():
        return SetStageResult(
            ok=False,
            reason=(
                f"{task_id}: already answered by {current.answered_by} "
                f"at {current.answered_at} — an answer is written once"
            ),
        )
    if column_for(current) != "needsYou":
        raise StageOrderError(
            f"{task_id}: not waiting on a decision — a {current.kind} card at "
            f"{current.stage.value} is in {column_for(current)}, and only a "
            "judgement nobody has claimed carries a question to answer"
        )

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE cards
            SET answer = ?, answered_by = ?, answered_at = ?
            WHERE task_id = ? AND stage = ? AND answer = ''
            """,
            (answer, actor, _now(), task_id, Stage.UNATTENDED.value),
        )
        conn.commit()
    finally:
        conn.close()

    if cursor.rowcount == 0:
        # Lost between the read above and this write — reread and report who
        # actually holds the decision, truthfully, never a silent overwrite.
        loser_view = read_card(db_path, task_id)
        if loser_view.answer.strip():
            return SetStageResult(
                ok=False,
                reason=(
                    f"{task_id}: already answered by {loser_view.answered_by} "
                    f"at {loser_view.answered_at} — an answer is written once"
                ),
            )
        return SetStageResult(
            ok=False,
            reason=f"{task_id}: no longer waiting on a decision — card is at "
            f"{loser_view.stage.value}",
        )
    return SetStageResult(ok=True)


def list_cards(db_path: Path) -> list[Card]:
    """Every card, current stage included. Empty — never an error — when
    nothing has been filed yet: `ensure_schema` was never called, so the
    file itself may not exist, and "no store yet" and "store, no rows" mean
    the same thing to a reader."""
    if not db_path.is_file():
        return []
    # Same repair-before-read as `read_card` — `kanban-patrol/17`+`21` found
    # a store built before these columns existed crashing every list, not
    # just a single-card read.
    ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"SELECT {_CARD_COLUMNS} FROM cards").fetchall()
    finally:
        conn.close()
    return [_row_to_card(row) for row in rows]


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
       priority.
    2. **Unblocked cards that block nothing**, by priority (high, med, low).
    3. **Blocked cards, last**, in the *same* sub-order as 1+2 combined —
       dependents first, priority second — so a blocked card that itself
       unblocks a chain still sorts ahead of a blocked card nobody is
       waiting on, even though neither can be picked up yet.

    `why_here` names exactly one of those three rules: "unblocks N cards",
    "<priority> priority, nothing waits on it", or "blocked by <ids>".
    """
    live = [card for card in cards if card.stage is not Stage.FINISHED]
    finished_ids = {card.task_id for card in cards if card.stage is Stage.FINISHED}

    def outstanding_blockers(card: Card) -> tuple[str, ...]:
        return tuple(b for b in card.blocked_by if b not in finished_ids)

    dependents: dict[str, list[str]] = {card.task_id: [] for card in live}
    for card in live:
        for blocker in outstanding_blockers(card):
            if blocker in dependents:
                dependents[blocker].append(card.task_id)

    def priority_rank(card: Card) -> int:
        try:
            return BOARD_PRIORITIES.index(card.priority)
        except ValueError:
            return len(BOARD_PRIORITIES)

    def sort_key(card: Card) -> tuple[int, int, str]:
        # Most dependents first (negated for ascending sort), then priority,
        # then title for a stable, readable tie-break.
        return (-len(dependents[card.task_id]), priority_rank(card), card.title)

    unblocked = [c for c in live if not outstanding_blockers(c)]
    blocked = [c for c in live if outstanding_blockers(c)]
    ordered = sorted(unblocked, key=sort_key) + sorted(blocked, key=sort_key)

    rows = []
    for rank, card in enumerate(ordered, start=1):
        blockers = outstanding_blockers(card)
        n_dependents = len(dependents[card.task_id])
        if blockers:
            why_here = f"blocked by {', '.join(blockers)}"
        elif n_dependents:
            plural = "card" if n_dependents == 1 else "cards"
            why_here = f"unblocks {n_dependents} {plural}"
        else:
            why_here = f"{card.priority} priority, nothing waits on it"
        rows.append(TriageRow(card=card, rank=rank, why_here=why_here))
    return tuple(rows)


def flagged_stale(db_path: Path, *, threshold_seconds: int) -> list[str]:
    """Cards whose last heartbeat is older than the threshold. Read-only —
    flags, never releases. `kanban-patrol/19`: a human presses Release
    themselves; this function must never change a row, only report on it.

    Two stages are excluded by construction (`WHERE stage NOT IN (...)`),
    and for the same reason at both ends of the lifecycle: staleness is
    about an abandoned *claim*.

    - An `unattended` card has no claim to abandon.
    - A `finished` card's claim was not abandoned, it was *discharged*
      (`kanban-patrol/32`). Nobody writes to a resolved card again, which
      is what resolved means, so its heartbeat is older than any threshold
      within the hour — and flagging it offered `release_card`, the one
      control here that empties all four evidence fields, on the one column
      that is read-only. Excluded here rather than at the card because this
      is where the fact is computed: the API row's `stale`, the CLI's
      `kanban release` and the MCP `kanban_release_card` all read it, and a
      rule spelled at one door is a rule the other two do not have.

    **No store yet is an empty answer, never a crash** — the same guard
    `read_card`/`list_cards` already carry, missing here until
    `kanban-patrol/19`'s Release wiring gave this function its first real
    caller outside its own test file and found the gap live: a fresh
    project's kanban board asking "is anything stale" before a single card
    has ever been filed hit `no such table: cards` instead of the honest
    "no, nothing is."
    """
    if not db_path.is_file():
        return []
    ensure_schema(db_path)
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT task_id, last_heartbeat_at FROM cards "
            "WHERE stage NOT IN (?, ?)",
            (Stage.UNATTENDED.value, Stage.FINISHED.value),
        ).fetchall()
    finally:
        conn.close()

    stale = []
    for task_id, last_heartbeat_at in rows:
        if last_heartbeat_at is None:
            continue
        age = (now - datetime.fromisoformat(last_heartbeat_at)).total_seconds()
        if age > threshold_seconds:
            stale.append(task_id)
    return stale
