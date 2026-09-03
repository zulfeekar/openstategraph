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

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
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
    caller (human or agent) can fix it, never a generic failure."""


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
                evidence_commit TEXT NOT NULL DEFAULT ''
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


_CARD_COLUMNS = (
    "task_id, board, kind, category, title, stage, actor, last_heartbeat_at, "
    "priority, area, priority_reason, filed_at, "
    "evidence_test_id, evidence_red_reason, evidence_green, evidence_commit"
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
        # `kanban-patrol/20`: not full identity — the CLI's trust boundary
        # is the shell it runs in (a deliberate, stated decision, not an
        # oversight), and the installed MCP library exposes no request
        # context a tool function could read one from at all (checked, not
        # assumed). But "already attended by " with nothing in the blank is
        # meaningless to a human reading the card, so this is the floor: an
        # actor must be a real, non-blank string.
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
        if test_id != current.evidence_test_id:
            raise MissingEvidenceError(
                f"{task_id}: green test_id {test_id!r} does not match the "
                f"red test_id {current.evidence_test_id!r} recorded on this card"
            )
        evidence_green = True
    elif stage == Stage.FINISHED:
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


def flagged_stale(db_path: Path, *, threshold_seconds: int) -> list[str]:
    """Cards whose last heartbeat is older than the threshold. Read-only —
    flags, never releases. `kanban-patrol/19`: a human presses Release
    themselves; this function must never change a row, only report on it.

    An `unattended` card is excluded by construction (`WHERE stage != ?`) —
    staleness is about an abandoned *claim*, and a card nobody has attended
    has no claim to abandon.

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
            "SELECT task_id, last_heartbeat_at FROM cards WHERE stage != ?",
            (Stage.UNATTENDED.value,),
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
