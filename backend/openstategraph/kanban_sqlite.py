"""The card store's sqlite concrete — `team-board-and-gap-reports/02`.

`SqliteKanbanStore` is the one member the family has today: one file per
project, `workflows/.openstategraph/kanban.sqlite`, addressed by
`kanban_store.kanban_store_location`. It is also **the only module in the card
path that knows what a `db_path` is** — every rule and every refusal lives one
rung up, on `abc.kanban_store.AbstractKanbanStore`, so a second store cannot
disagree with any of them.

What is left here is exactly what an engine has an opinion about:

- **The schema, and its repair.** `ensure_schema` builds the table if there is
  none and adds each declared column that is missing if there is one —
  per-column, additive only, deliberately not a versioned migration list
  (`kanban-patrol/26`): every change this schema has needed has been "add a
  column", never a rename, and the fuller machinery would solve a problem that
  has not happened.
- **The conditional writes.** `_advance_stage`, `_reset_card` and
  `_record_answer` are each a single `UPDATE ... WHERE`, never a
  read-then-check-then-write, because the latter passes every single-caller
  test and loses a card to whichever caller wrote last with both believing they
  own it (`kanban-patrol/13`, a real one). The base decides *whether* a write is
  allowed; this decides that the write, once allowed, cannot race.
- **The encoding.** `blocked_by` is JSON text in a column and a tuple of ids on
  a `Card`; `evidence_green` is an `INTEGER` here and a `bool` there. Nothing
  above this module should have to know either.
- **The digest.** `mtime_ns`, size and three aggregates — a question about a
  *file*, which is why a second store answers it its own way rather than
  inheriting this one.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from openstategraph.abc.kanban_store import AbstractKanbanStore
from openstategraph.kanban_store import Card, CardEvidence, Stage

#: Every column this schema declares, past `CREATE TABLE`'s own reach once a
#: store already exists — `kanban-patrol/26`. One source for both: the
#: `CREATE TABLE` below (a fresh store) and the repair loop beside it (an old
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
    # `osg-agent-experience/85`. The one column this ticket adds, and it is
    # added the way `26` made cheap: an existing kanban.sqlite gains it on the
    # next open, in place, with every row it already holds intact. Nothing is
    # rewritten and nothing is dropped.
    "finished_reason": "TEXT NOT NULL DEFAULT ''",
    # `team-board-and-gap-reports/15`. The finding a patrol card was minted
    # from, as JSON — added the same way `26` made cheap: an existing
    # kanban.sqlite gains it on the next open, in place, with every row it
    # already holds intact. A card filed before it existed reads back with
    # `""`, which is exactly what it means — no finding behind this card.
    "gap_evidence": "TEXT NOT NULL DEFAULT ''",
    # `team-board-and-gap-reports/17`. How many times this finding has been
    # reported from this install — the shared board's `0003` column, mirrored
    # here so one `Card` reads back the same from either store. `DEFAULT 1`
    # and not `0`, the same word the migration uses and for its reason: a card
    # exists because something was reported once.
    "count": "INTEGER NOT NULL DEFAULT 1",
}

_CARD_COLUMNS = (
    "task_id, board, kind, category, title, stage, actor, last_heartbeat_at, "
    "priority, area, priority_reason, filed_at, "
    "evidence_test_id, evidence_red_reason, evidence_green, evidence_commit, "
    "answer, answered_by, answered_at, "
    "story, done_when, blocked_by, agent_model, agent_effort, finished_reason, "
    "gap_evidence, count"
)


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
        finished_reason=row[24],
        gap_evidence=row[25],
        count=row[26],
    )


class SqliteKanbanStore(AbstractKanbanStore):
    """One project's board, in one sqlite file.

    Ten public members, at the ceiling and not over it: the eight
    `IKanbanStore` declares, plus `path` — the address a door prints when it
    cannot find a card — and `ensure_schema`, which `patrol` calls before a
    sweep so a repair happens once rather than on every filing.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def ensure_schema(self) -> None:
        """Build the store if it does not exist; repair it, column by column,
        if it does — `kanban-patrol/26`.

        The story this closes: the old version only knew "build one if there's
        none," so a store made before a column existed was left exactly as it
        was, and the next read of that column crashed.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
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

    def list_cards(self) -> list[Card]:
        """Every card, current stage included. Empty — never an error — when
        nothing has been filed yet: the file itself may not exist, and "no
        store yet" and "store, no rows" mean the same thing to a reader. The
        door that must tell those apart asks `kanban_store_location`
        (`osg-agent-experience/65`), never this."""
        if not self.path.is_file():
            return []
        # Same repair-before-read as `_fetch_card` — `kanban-patrol/17`+`21`
        # found a store built before these columns existed crashing every
        # list, not just a single-card read.
        self.ensure_schema()
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute(f"SELECT {_CARD_COLUMNS} FROM cards").fetchall()
        finally:
            conn.close()
        return [_row_to_card(row) for row in rows]

    def store_digest(self) -> str:
        """A cheap answer to *has anything in this store changed* —
        `osg-agent-experience/36`.

        The board's live stream watches the file the way `live.LiveWorkflows`
        watches a package: the store is the truth and the server is one reader
        of it, so the only honest question a poll can ask is whether the bytes
        moved. Every write door — from this process or from an `openstategraph
        kanban stage` in another — goes through sqlite, so the file's
        `mtime_ns` and size move for all of them and for none of the reads.

        **The four aggregates are not redundancy for its own sake.**
        `mtime_ns` alone is coarse on filesystems that round it, and sqlite can
        rewrite a page without changing the row count; `count(*)` catches a
        filing, `max(last_heartbeat_at)` catches every stage write (which
        always stamps it), `max(answered_at)` catches an answer.

        Opaque on purpose: it is compared, never parsed. An absent store has a
        digest too — asking never creates anything, and a watcher must not
        raise on a project whose board has never been opened.
        """
        if not self.path.is_file():
            return "absent"
        stat = self.path.stat()
        parts: list[str] = [str(stat.st_mtime_ns), str(stat.st_size)]
        try:
            self.ensure_schema()
            conn = sqlite3.connect(self.path)
            try:
                row = conn.execute(
                    "SELECT count(*), max(last_heartbeat_at), max(answered_at) FROM cards"
                ).fetchone()
            finally:
                conn.close()
            parts.extend(str(value) for value in row)
        except sqlite3.Error:
            # A store mid-write (or not one) is not a reason to kill the
            # watcher; the file stamp above is still a true answer to "did the
            # bytes move".
            parts.append("unreadable")
        return "|".join(parts)

    # -- the primitives `AbstractKanbanStore` decides with -----------------

    def _insert_card(self, card: Card) -> bool:
        """`INSERT OR IGNORE`, and the return value is what the base needs to
        tell the two filings apart: a patrol re-filing one finding is a no-op,
        while two ideas under one title is a refusal the base words."""
        self.ensure_schema()
        conn = sqlite3.connect(self.path)
        try:
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO cards ({_CARD_COLUMNS}) "
                f"VALUES ({', '.join('?' * len(_CARD_COLUMNS.split(', ')))})",
                (
                    card.task_id, card.board, card.kind, card.category, card.title,
                    card.stage.value, card.actor, card.last_heartbeat_at,
                    card.priority, card.area, card.priority_reason, card.filed_at,
                    card.evidence_test_id, card.evidence_red_reason,
                    int(card.evidence_green), card.evidence_commit,
                    card.answer, card.answered_by, card.answered_at,
                    card.story, card.done_when, json.dumps(list(card.blocked_by)),
                    card.agent_model, card.agent_effort, card.finished_reason,
                    card.gap_evidence, card.count,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return cursor.rowcount > 0

    def _fetch_card(self, task_id: str) -> Card | None:
        if not self.path.is_file():
            # No store yet means no card yet — the same "no record of that"
            # honesty `async_tasks.py`'s `TaskStatus.UNKNOWN` names, not a
            # crash over a transport a caller cannot otherwise distinguish
            # from a genuine miss.
            return None
        # `kanban-patrol/17`+`21` found this live: a store built before this
        # column set existed crashed every later read with "no such column"
        # rather than being repaired. Guarded on `is_file()` so this never
        # *creates* a store on a mere read, only repairs one already there.
        self.ensure_schema()
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                f"SELECT {_CARD_COLUMNS} FROM cards WHERE task_id = ?", (task_id,)
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else _row_to_card(row)

    def _advance_stage(
        self,
        task_id: str,
        *,
        required_previous: Stage,
        stage: Stage,
        actor: str,
        heartbeat: str,
        evidence: CardEvidence,
    ) -> bool:
        """**Atomic against the database, not against a value read a moment
        ago:** the `WHERE` clause names the *required* previous stage
        literally, which is what makes this a single conditional `UPDATE`
        rather than the read-then-write shape that passes every single-caller
        test and loses a real race."""
        conn = sqlite3.connect(self.path)
        try:
            cursor = conn.execute(
                """
                UPDATE cards
                SET stage = ?, actor = ?, last_heartbeat_at = ?,
                    evidence_test_id = ?, evidence_red_reason = ?,
                    evidence_green = ?, evidence_commit = ?, finished_reason = ?
                WHERE task_id = ? AND stage = ?
                """,
                (
                    stage.value, actor, heartbeat,
                    evidence.test_id, evidence.red_reason,
                    int(evidence.green), evidence.commit, evidence.finished_reason,
                    task_id, required_previous.value,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return cursor.rowcount > 0

    def _reset_card(self, task_id: str) -> bool:
        """Back to filed-but-never-attended, evidence included. The `WHERE`
        still guards `stage != 'unattended'` — a genuine resume landing between
        the base's staleness check and this write must not be clobbered."""
        conn = sqlite3.connect(self.path)
        try:
            cursor = conn.execute(
                """
                UPDATE cards
                SET stage = ?, actor = NULL, last_heartbeat_at = NULL,
                    evidence_test_id = '', evidence_red_reason = '',
                    evidence_green = 0, evidence_commit = '', finished_reason = ''
                WHERE task_id = ? AND stage != ?
                """,
                (Stage.UNATTENDED.value, task_id, Stage.UNATTENDED.value),
            )
            conn.commit()
        finally:
            conn.close()
        return cursor.rowcount > 0

    def _record_answer(self, task_id: str, *, answer: str, actor: str, at: str) -> bool:
        """The `WHERE` requires the answer to still be blank and the card to
        still be unattended, so two callers that both read a blank answer do
        not both write one."""
        conn = sqlite3.connect(self.path)
        try:
            cursor = conn.execute(
                """
                UPDATE cards
                SET answer = ?, answered_by = ?, answered_at = ?
                WHERE task_id = ? AND stage = ? AND answer = ''
                """,
                (answer, actor, at, task_id, Stage.UNATTENDED.value),
            )
            conn.commit()
        finally:
            conn.close()
        return cursor.rowcount > 0


def open_sqlite_kanban_store(url: str) -> SqliteKanbanStore:
    """The opener `kanban_store`'s registry holds under `sqlite`. A URL rather
    than a path because every store in that registry is addressed the same way
    and `OPENSTATEGRAPH_KANBAN_URL` is what a second one arrives as."""
    return SqliteKanbanStore(url.removeprefix("sqlite:///").removeprefix("sqlite://"))
