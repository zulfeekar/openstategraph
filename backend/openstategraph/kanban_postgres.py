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

#: The *other* applier's ledger, read and never written —
#: `team-board-and-gap-reports/13`.
#:
#: The shared database has two appliers by design: this runner, and the
#: maintainers' migration CLI pointed at the same directory by a symlink. The
#: owner's project was already at head when the store first opened it, because
#: the CLI had pushed both files the day before — and a runner that reads only
#: its own ledger concludes that nothing has ever been applied. Every file is
#: idempotent, so it would have "worked"; a migration runner whose correctness
#: rests on nothing it does mattering is not one. So the applied set is the
#: union of the two ledgers, resolved through one seam.
#:
#: This is the one place in the package that names the tool it shares the
#: database with, and `test_the_shared_board_has_a_reviewable_schema` records
#: the exception with its argument. It is an identifier in a database somebody
#: else's tool created — not an SDK, a key, a client, or a dependency — and the
#: honest alternative is to pretend the other applier is not there.
CLI_LEDGER_TABLE = "supabase_migrations.schema_migrations"


class MigrationFailed(RuntimeError):
    """A migration script libpq refused.

    Its own class rather than a bare `RuntimeError` because the caller that
    matters is `open_postgres_kanban_store`, which has to give the pool back
    before it re-raises, and "which exception means the schema is not there"
    should not be a string match.
    """


#: Column order, derived from the `Card` dataclass rather than typed again.
#: The two the table has and a card does not are named separately.
CARD_COLUMNS: tuple[str, ...] = tuple(field.name for field in dataclasses.fields(Card))


def migration_files() -> tuple[Path, ...]:
    """Every migration, in the order both appliers run them: filename order,
    which is version order because the prefix is digits."""
    return tuple(sorted(MIGRATIONS_DIR.glob("*.sql")))


def _run_script(conn: Any, path: Path) -> None:
    """One migration file, applied whole — `team-board-and-gap-reports/13`.

    `Connection.execute` speaks the **extended** query protocol, which carries
    exactly one command per message; handing it a file of twenty raises
    *cannot insert multiple commands into a prepared statement*, which is how
    the first live open of this store died. `pgconn.exec_` is libpq's **simple**
    query protocol: a whole script in, one result out, which is the shape a
    migration file has.

    A splitter was the alternative the ticket allowed and is not what this is,
    for the reason a splitter always loses: to know where a `;` ends a
    statement it must track dollar-quoting, string literals, comments and
    nested `$function$` bodies — a small SQL lexer maintained here, in a
    package whose only job is to hand somebody else's parser the bytes. libpq
    already has that parser.

    `exec_` does not raise. It returns a result carrying a status, so a runner
    that does not read it applies a broken file, records it as applied, and
    never runs it again. The file name goes in the message because libpq's own
    error says which *statement* failed and nothing about which file it was in.
    """
    from psycopg import pq

    result = conn.pgconn.exec_(path.read_text(encoding="utf-8").encode("utf-8"))
    if result.status in (
        pq.ExecStatus.COMMAND_OK,
        pq.ExecStatus.TUPLES_OK,
        pq.ExecStatus.EMPTY_QUERY,
    ):
        return
    detail = bytes(result.error_message or b"").decode("utf-8", "replace").strip()
    raise MigrationFailed(f"{path.name} was refused by the database: {detail}")


def _applied_versions(conn: Any) -> set[str]:
    """Every version this database has already had applied, by either applier.

    Two ledgers, one seam, unioned — see `CLI_LEDGER_TABLE` for why the second
    one is read at all. It is asked for by `to_regclass` rather than by
    catching the error from selecting it: a database nobody has pushed to with
    that CLI simply has no such schema, and that is an ordinary state of
    affairs rather than something worth logging a failed statement for.
    """
    versions = {
        row["version"] for row in conn.execute(f"select version from {LEDGER_TABLE}")
    }
    present = conn.execute(
        "select to_regclass(%s) as present", (CLI_LEDGER_TABLE,)
    ).fetchone()
    if present is None or present["present"] is None:
        return versions
    rows = conn.execute(f"select version from {CLI_LEDGER_TABLE}").fetchall()
    return versions | {row["version"] for row in rows}


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
        with self._ensure_pool().connection() as conn:
            conn.execute(
                f"create table if not exists {LEDGER_TABLE} ("
                "version text primary key, applied_at timestamptz not null default now())"
            )
            applied = _applied_versions(conn)
            for path in migration_files():
                version = path.name.split("_", 1)[0]
                if version in applied:
                    continue
                _run_script(conn, path)
                conn.execute(
                    f"insert into {LEDGER_TABLE} (version) values (%s) "
                    "on conflict (version) do nothing",
                    (version,),
                )
        self._migrated = True

    # -- giving the pool back ---------------------------------------------

    def close(self) -> None:
        """Hand the pool back. Idempotent, because the two ways out of a store
        — `close()` and leaving the `with` — must be able to happen both."""
        pool, self._pool = self._pool, None
        self._migrated = False
        if pool is not None:
            pool.close()

    def __enter__(self) -> PostgresKanbanStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

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

    And a pool that opened is given back if anything after it fails
    (`team-board-and-gap-reports/13`). The first live open raised on its own
    first migration file and then hung for five seconds on
    *couldn't stop thread 'pool-1-worker-0'*, because the pool had workers and
    nothing owned it: the store had not been returned and the caller had
    nothing to close. Every exit path from here closes it or hands back a store
    that can.
    """
    from openstategraph import postgres

    store = PostgresKanbanStore(
        url, pool=postgres.open_pool(url, env_var=KANBAN_URL_ENV)
    )
    try:
        store._migrate()
    except Exception:
        store.close()
        raise
    return store
