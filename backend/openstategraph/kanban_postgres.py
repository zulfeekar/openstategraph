"""The card store's Postgres concrete — `team-board-and-gap-reports/03`.

`kanban.sqlite` is one file on one laptop, resolved per project *per machine*.
Two maintainers working one map each file cards into their own copy and
neither ever sees the other's. `PostgresKanbanStore` is the second member of
the family `team-board-and-gap-reports/02` opened: one shared table, keyed by a
hash of the project id, reached by one environment variable.

## What this module knows, and what it deliberately does not

It knows Postgres. It does not know which Postgres, which vendor, or that a
vendor exists — the owner's decision, and `CLAUDE.md`'s Ollama rule in its
general form: *never reach a vendor without naming a variable someone can set,
see and revoke*. `OPENSTATEGRAPH_KANBAN_URL` is that variable, and it is
**not** `OPENSTATEGRAPH_POSTGRES_URL`: that one means "put this deployment's
durable run state here" and is a thing an adopter sets for durability, while
this one means "join the maintainers' shared board". One setting meaning both
would put a maintainer's cards into an adopter's checkpoint database the first
time anybody set it.

Every rule stays one rung up on `AbstractKanbanStore`. What is left here is
what an engine has an opinion about, and it is the same short list the SQLite
store carries:

- **The schema, and how it arrives.** Numbered `.sql` files in
  `kanban_migrations/`, applied in filename order and recorded in a ledger
  table, rather than the SQLite store's additive `ALTER TABLE` repair loop.
  Not because that loop is wrong — its docstring argues its case and every
  change that schema has needed really was "add a column" — but because these
  files are also what a maintainer's CLI pushes at the shared database, and a
  hidden `ALTER` loop is not something a second tool can push or a reviewer can
  read. Every file is idempotent, so the two paths cannot fight.
- **The conditional writes.** `_advance_stage`, `_reset_card` and
  `_record_answer` are each a single `UPDATE ... WHERE`, exactly as in SQLite
  and for exactly the reason `kanban-patrol/13` recorded — except that on this
  store two maintainers racing for one card stops being hypothetical.
- **The encoding.** `blocked_by` is `text[]` here and JSON text there;
  `evidence_green` is a `boolean` here and an `INTEGER` there. A `Card` is the
  same either way, which is the point of both.
- **The tenancy key.** Every statement carries `project_hash = %s`. The
  database enforces the same thing through RLS for every reader that is not
  the owner role, and the owner role has `bypassrls`, so the `where` clause is
  not belt-and-braces — it is the only thing scoping *our own* reads.

## A misconfiguration raises; it does not degrade

`postgres.py`'s rule, copied rather than re-derived. Unset is the SQLite store
and always will be. Set and reachable is this one. Set and unreachable raises
at resolution, naming the variable — a board that quietly fell back to a local
file when the shared one was asked for is two people disagreeing about what
the board says, discovered a week later.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from openstategraph.abc.kanban_store import AbstractKanbanStore
from openstategraph.kanban_store import KANBAN_URL_ENV, Card, CardEvidence, Stage

#: The migrations this store applies, and the ones the maintainers' CLI pushes
#: — one directory, reached from two places. The migrations directory at the
#: repository root, where the maintainers' migration CLI looks, is a symlink to
#: this one rather than a second copy: one copy of the bytes makes drift
#: impossible instead of merely detectable.
MIGRATIONS_DIR = Path(__file__).parent / "kanban_migrations"

#: Where an applied migration is recorded. Prefixed, and deliberately not the
#: bare `schema_migrations` every tool wants to own: the shared database is not
#: ours alone, and a generic name in a shared schema is a landgrab that the
#: next tool discovers by failing. Created by this store rather than by a
#: migration file, because it has to exist before the first file can be
#: recorded and a ledger is not schema anybody reviews.
LEDGER_TABLE = "public.kanban_schema_migrations"

#: Column order, derived from the `Card` dataclass rather than typed again.
#: The two the table has and a card does not are named separately.
CARD_COLUMNS: tuple[str, ...] = tuple(field.name for field in dataclasses.fields(Card))


def migration_files() -> tuple[Path, ...]:
    """Every migration, in the order both appliers run them: filename order,
    which is version order because the prefix is digits."""
    return tuple(sorted(MIGRATIONS_DIR.glob("*.sql")))


def _row_to_card(row: dict[str, Any]) -> Card:
    """A `dict_row` back as a `Card`. Addressed by name rather than by
    position: the column order in a migration file and the field order on the
    dataclass are two things nobody would notice diverging."""
    values = dict(row)
    values["stage"] = Stage(values["stage"])
    values["blocked_by"] = tuple(values["blocked_by"] or ())
    values["evidence_green"] = bool(values["evidence_green"])
    return Card(**{name: values[name] for name in CARD_COLUMNS})


class PostgresKanbanStore(AbstractKanbanStore):
    """One project's cards in a table many projects share.

    Nine public members: the eight `IKanbanStore` declares, and `location` —
    the redacted address a door prints when it cannot find a card. The DSN is
    never printed raw anywhere, by `postgres.redacted`, because a connection
    string is the most useful thing to put in an error and the worst thing to
    leak.
    """

    def __init__(
        self, url: str, *, pool: Any = None, project_hash: str | None = None
    ) -> None:
        self._url = url
        self._pool = pool
        self._resolved_hash: str | None = project_hash
        self._migrated = False

    # -- addressing --------------------------------------------------------

    @property
    def location(self) -> str:
        from openstategraph.postgres import redacted

        return redacted(self._url)

    def _hash(self) -> str:
        """The tenancy key: a hash of this project's id, never the id.

        Resolved on first use rather than at construction. Opening a store must
        not require a config file — `open_kanban_store` is called by doors that
        only want to ask where the board is — and a project with no id is a
        refusal `project_id_for_board` already words.
        """
        if self._resolved_hash is None:
            from openstategraph.gap_report import hashed_project_id
            from openstategraph.project_identity import project_id_for_board

            self._resolved_hash = hashed_project_id(project_id_for_board())
        return self._resolved_hash

    def _ensure_pool(self) -> Any:
        if self._pool is None:
            from openstategraph.postgres import open_pool

            self._pool = open_pool(self._url, env_var=KANBAN_URL_ENV)
        return self._pool

    def _connection(self) -> Any:
        pool = self._ensure_pool()
        self._migrate()
        return pool.connection()

    # -- migrations --------------------------------------------------------

    def _migrate(self) -> None:
        """Apply every file this build ships that this database has not run.

        Idempotent twice over: the ledger skips a file already applied, and
        every file is written so that applying it again is a no-op anyway —
        which is what lets a maintainer's CLI push the same directory without
        the two appliers having to know about each other.
        """
        if self._migrated:
            return
        self._migrated = True
        with self._ensure_pool().connection() as conn:
            conn.execute(
                f"create table if not exists {LEDGER_TABLE} ("
                "version text primary key, applied_at timestamptz not null default now())"
            )
            applied = {
                row["version"]
                for row in conn.execute(f"select version from {LEDGER_TABLE}")
            }
            for path in migration_files():
                version = path.name.split("_", 1)[0]
                if version in applied:
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    f"insert into {LEDGER_TABLE} (version) values (%s) "
                    "on conflict (version) do nothing",
                    (version,),
                )

    # -- what `AbstractKanbanStore` decides with ---------------------------

    def list_cards(self) -> list[Card]:
        """This project's cards. Empty, never an error — the same answer the
        SQLite store gives for a board nobody has filed into."""
        with self._connection() as conn:
            rows = conn.execute(
                f"select {', '.join(CARD_COLUMNS)} from public.cards "
                "where project_hash = %s",
                (self._hash(),),
            ).fetchall()
        return [_row_to_card(row) for row in rows]

    def store_digest(self) -> str:
        """The same cheap *has anything changed* the file store answers with a
        stat, asked the way a table can answer it.

        `count(*)` catches a filing; `max(updated_at)` catches every write of
        any kind, because a trigger maintains it and no caller can forget to.
        The two heartbeat aggregates the SQLite digest carries are not repeated
        here — they exist there because a file has no `updated_at`.

        Opaque on purpose: compared, never parsed. A database that cannot be
        reached at this moment is not a reason to kill the board's watcher, so
        the failure is a value like any other.
        """
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "select count(*) as cards, max(updated_at) as latest "
                    "from public.cards where project_hash = %s",
                    (self._hash(),),
                ).fetchone()
        except Exception:
            return "unreadable"
        return f"{row['cards']}|{row['latest']}"

    def _insert_card(self, card: Card) -> bool:
        """`on conflict (task_id) do nothing` — the atomic form of the SQLite
        store's `INSERT OR IGNORE`, never a check-then-insert. The base turns
        the `False` into whichever of the two sentences the caller earns."""
        columns = ("project_hash", *CARD_COLUMNS)
        placeholders = ", ".join(["%s"] * len(columns))
        with self._connection() as conn:
            cursor = conn.execute(
                f"insert into public.cards ({', '.join(columns)}) "
                f"values ({placeholders}) on conflict (task_id) do nothing",
                (self._hash(), *self._card_values(card)),
            )
        return bool(cursor.rowcount > 0)

    @staticmethod
    def _card_values(card: Card) -> tuple[Any, ...]:
        values = dataclasses.asdict(card)
        values["stage"] = card.stage.value
        values["blocked_by"] = list(card.blocked_by)
        return tuple(values[name] for name in CARD_COLUMNS)

    def _fetch_card(self, task_id: str) -> Card | None:
        with self._connection() as conn:
            row = conn.execute(
                f"select {', '.join(CARD_COLUMNS)} from public.cards "
                "where task_id = %s and project_hash = %s",
                (task_id, self._hash()),
            ).fetchone()
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
        """One conditional `UPDATE`, guarded on the stage the caller believes
        the card is at. Two maintainers claiming one card is the case this
        store exists for, and a read-then-write here would lose one of them
        while telling both they had won."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                update public.cards
                set stage = %s, actor = %s, last_heartbeat_at = %s,
                    evidence_test_id = %s, evidence_red_reason = %s,
                    evidence_green = %s, evidence_commit = %s, finished_reason = %s
                where task_id = %s and project_hash = %s and stage = %s
                """,
                (
                    stage.value, actor, heartbeat,
                    evidence.test_id, evidence.red_reason,
                    evidence.green, evidence.commit, evidence.finished_reason,
                    task_id, self._hash(), required_previous.value,
                ),
            )
        return bool(cursor.rowcount > 0)

    def _reset_card(self, task_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                update public.cards
                set stage = %s, actor = null, last_heartbeat_at = null,
                    evidence_test_id = '', evidence_red_reason = '',
                    evidence_green = false, evidence_commit = '', finished_reason = ''
                where task_id = %s and project_hash = %s and stage <> %s
                """,
                (
                    Stage.UNATTENDED.value,
                    task_id,
                    self._hash(),
                    Stage.UNATTENDED.value,
                ),
            )
        return bool(cursor.rowcount > 0)

    def _record_answer(self, task_id: str, *, answer: str, actor: str, at: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                update public.cards
                set answer = %s, answered_by = %s, answered_at = %s
                where task_id = %s and project_hash = %s and stage = %s and answer = ''
                """,
                (answer, actor, at, task_id, self._hash(), Stage.UNATTENDED.value),
            )
        return bool(cursor.rowcount > 0)


def open_postgres_kanban_store(url: str) -> PostgresKanbanStore:
    """The opener `kanban_store`'s registry holds under `postgresql` and
    `postgres` — both spellings, because a DSN copied out of a hosting
    dashboard is as likely to carry one as the other and a maintainer who
    pasted the short form is not making a different request.

    The pool opens **here**, not on the first card. That is the whole of
    "a misconfiguration raises; it does not degrade": a URL that names a
    database nobody can reach fails when the board is opened, with
    `OPENSTATEGRAPH_KANBAN_URL` named in the sentence, rather than at the
    moment somebody files their first card into nothing.
    """
    from openstategraph.postgres import open_pool

    store = PostgresKanbanStore(url, pool=open_pool(url, env_var=KANBAN_URL_ENV))
    store._migrate()
    return store
