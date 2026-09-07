"""The store's migration runner, run against a fake libpq —
`team-board-and-gap-reports/13`.

The first live open of `PostgresKanbanStore` against a real database died on
its own first migration file::

    kanban_postgres.py:179 in _migrate: conn.execute(path.read_text(...))
    psycopg.errors.SyntaxError: cannot insert multiple commands into a
    prepared statement

`Connection.execute` speaks the *extended* query protocol, which carries one
command per message. A migration file holds twenty. Nothing caught it here
because ticket 03 had no database to run SQL against and said so, and the
maintainers' CLI applies the same directory through its own runner — so the
one path that had never executed a `.sql` file was ours.

So this suite fakes the layer the fix reaches for. `pgconn.exec_` is libpq's
*simple* query protocol: it takes a whole script and returns one result, which
is exactly the shape a migration file has. A fake `pgconn` records the bytes
handed to it, so the pin is the thing the defect was about — how many commands
went in one call — rather than a mock of our own control flow.

The second half is the ledger. The owner's database had already had both files
applied by the CLI before the store ever opened, and the CLI records what it
applied in its own table. A runner that reads only our ledger re-runs every
file on a database that is already at head; every file is idempotent, so it
would work, but "it works because nothing we do matters" is not a migration
runner. One seam reads both ledgers and unions them.
"""

from __future__ import annotations

from typing import Any

import pytest

psycopg = pytest.importorskip("psycopg")

from openstategraph.kanban_postgres import (  # noqa: E402
    CLI_LEDGER_TABLE,
    LEDGER_TABLE,
    MigrationFailed,
    PostgresKanbanStore,
    migration_files,
)


class FakeResult:
    """One libpq result. `status` is the real enum, so a test that passes
    against this fake is a test whose comparison would pass against libpq."""

    def __init__(self, status: Any, error: bytes = b"") -> None:
        self.status = status
        self.error_message = error


class FakePgConn:
    def __init__(self, fail_on: bytes | None = None) -> None:
        self.scripts: list[bytes] = []
        self._fail_on = fail_on

    def exec_(self, sql: bytes) -> FakeResult:
        self.scripts.append(sql)
        if self._fail_on is not None and self._fail_on in sql:
            return FakeResult(
                psycopg.pq.ExecStatus.FATAL_ERROR, b'relation "cards" is broken'
            )
        return FakeResult(psycopg.pq.ExecStatus.COMMAND_OK)


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.rowcount = len(rows)

    def __iter__(self) -> Any:
        return iter(self._rows)

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class FakeConnection:
    """Just enough of a psycopg connection for `_migrate`: parameterised
    statements go through `execute`, whole scripts do not go through it at all.
    """

    def __init__(self, pool: FakePool) -> None:
        self._pool = pool
        self.pgconn = pool.pgconn

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> FakeCursor:
        self._pool.statements.append(sql)
        lowered = " ".join(sql.lower().split())
        if "to_regclass" in lowered:
            assert params is not None
            name = params[0]
            return FakeCursor([{"present": name if name in self._pool.tables else None}])
        if lowered.startswith(f"select version from {LEDGER_TABLE}"):
            return FakeCursor([{"version": v} for v in sorted(self._pool.ours)])
        if lowered.startswith(f"select version from {CLI_LEDGER_TABLE}"):
            return FakeCursor([{"version": v} for v in sorted(self._pool.theirs)])
        if lowered.startswith("insert into") and LEDGER_TABLE in lowered:
            assert params is not None
            self._pool.ours.add(params[0])
            return FakeCursor([])
        return FakeCursor([])

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakePool:
    def __init__(
        self,
        *,
        ours: set[str] | None = None,
        theirs: set[str] | None = None,
        cli_ledger_exists: bool = True,
        fail_on: bytes | None = None,
    ) -> None:
        self.ours = set(ours or ())
        self.theirs = set(theirs or ())
        self.tables = {LEDGER_TABLE}
        if cli_ledger_exists:
            self.tables.add(CLI_LEDGER_TABLE)
        self.pgconn = FakePgConn(fail_on=fail_on)
        self.statements: list[str] = []
        self.closed = False

    def connection(self) -> FakeConnection:
        return FakeConnection(self)

    def close(self) -> None:
        self.closed = True


def a_store(pool: FakePool) -> PostgresKanbanStore:
    return PostgresKanbanStore("postgresql://x/y", pool=pool, project_hash="deadbeef")


def test_a_whole_migration_file_goes_to_libpq_in_one_call() -> None:
    """The defect, at the layer it lived. Every file this build ships arrives
    at `exec_` whole — byte for byte what is on disk — rather than as a
    parameterised statement that libpq refuses for holding more than one
    command."""
    pool = FakePool()
    a_store(pool)._migrate()

    on_disk = [path.read_text(encoding="utf-8").encode("utf-8") for path in migration_files()]
    assert pool.pgconn.scripts == on_disk
    assert any(script.count(b";") > 1 for script in on_disk), (
        "the pin needs a multi-command file to be about anything"
    )


def test_no_migration_file_is_handed_to_a_prepared_statement() -> None:
    """The narrower half of the same claim: the parameterised path carries the
    ledger and nothing else. A file that reached `execute` would raise the
    live traceback again."""
    pool = FakePool()
    a_store(pool)._migrate()
    bodies = {path.read_text(encoding="utf-8") for path in migration_files()}
    assert not (set(pool.statements) & bodies)


def test_a_file_the_other_applier_already_ran_is_not_applied_again() -> None:
    """The owner's database was at head before the store ever opened it: the
    maintainers' CLI had pushed both files and recorded them in its own ledger.
    One seam reads both ledgers, so our runner starts from what the database
    actually is rather than from what we happen to have written down."""
    versions = [path.name.split("_", 1)[0] for path in migration_files()]
    pool = FakePool(theirs=set(versions))
    a_store(pool)._migrate()
    assert pool.pgconn.scripts == []


def test_the_other_applier_s_ledger_is_optional() -> None:
    """A database nobody has ever pushed to with that CLI has no such schema.
    The seam asks whether the table is there rather than catching an error,
    because a failed statement is a real thing to have logged and this is not
    one."""
    pool = FakePool(cli_ledger_exists=False)
    a_store(pool)._migrate()
    assert len(pool.pgconn.scripts) == len(migration_files())


def test_our_own_ledger_still_skips_what_we_applied() -> None:
    versions = [path.name.split("_", 1)[0] for path in migration_files()]
    pool = FakePool(ours=set(versions))
    a_store(pool)._migrate()
    assert pool.pgconn.scripts == []


def test_applying_records_the_version_so_the_second_open_applies_nothing() -> None:
    pool = FakePool()
    a_store(pool)._migrate()
    assert pool.ours == {path.name.split("_", 1)[0] for path in migration_files()}
    a_store(pool)._migrate()
    assert len(pool.pgconn.scripts) == len(migration_files())


def test_a_failed_script_raises_and_names_the_file() -> None:
    """`exec_` does not raise — it returns a result with a failure status, so a
    runner that does not read the status applies a broken migration, records
    it as applied and never runs it again. The message carries the file name
    because a libpq error alone says nothing about which of twenty statements
    in which of the files was the one."""
    first = migration_files()[0]
    pool = FakePool(fail_on=first.read_text(encoding="utf-8").encode("utf-8")[:40])
    with pytest.raises(MigrationFailed) as caught:
        a_store(pool)._migrate()
    assert first.name in str(caught.value)
    assert pool.ours == set()


def test_the_pool_is_closed_on_close_and_on_leaving_the_context() -> None:
    """The live failure left the pool's worker threads running ("couldn't stop
    thread 'pool-1-worker-0' within 5.0 seconds"): the store had no way to give
    its pool back. It has two now, and the second is the one a caller cannot
    forget."""
    pool = FakePool()
    store = a_store(pool)
    store.close()
    assert pool.closed

    second = FakePool()
    with a_store(second) as opened:
        opened._migrate()
    assert second.closed


def test_closing_twice_is_not_an_error() -> None:
    pool = FakePool()
    store = a_store(pool)
    store.close()
    store.close()
    assert pool.closed


def test_a_store_that_failed_to_migrate_gives_its_pool_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`open_postgres_kanban_store` opens the pool before it migrates, so the
    exit path the live traceback took is the one that must not leak threads."""
    from openstategraph import kanban_postgres, postgres

    first = migration_files()[0]
    pool = FakePool(fail_on=first.read_text(encoding="utf-8").encode("utf-8")[:40])
    monkeypatch.setattr(postgres, "open_pool", lambda url, **kwargs: pool)
    with pytest.raises(MigrationFailed):
        kanban_postgres.open_postgres_kanban_store("postgresql://x/y")
    assert pool.closed


#: The live half. A separate variable from `OPENSTATEGRAPH_KANBAN_URL` for the
#: reason `test_kanban_store_contract` gives: the board variable points at the
#: maintainers' real board, and a suite that migrated whatever a developer had
#: exported would be writing on the board it is meant to be independent of.
LIVE_URL_ENV = "OPENSTATEGRAPH_KANBAN_TEST_URL"


def test_a_second_open_of_a_real_database_applies_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fake above pins the bytes; only a database pins that libpq accepts
    them. Opened twice: the first open brings the schema to head from whatever
    the database was at, the second must find nothing left to do — which is the
    ledger claim and the idempotence claim at once, and is exactly what the
    first live open could not say."""
    import os

    url = os.environ.get(LIVE_URL_ENV, "").strip()
    if not url:
        pytest.skip(
            f"{LIVE_URL_ENV} is not set — this needs a database to be true "
            "about, and CI has none. Export it to a scratch database to run it."
        )
    from openstategraph import kanban_postgres as mod

    with mod.open_postgres_kanban_store(url) as first:
        assert first.store_digest() != "unreadable", (
            "the schema is not readable after the open that was meant to create it"
        )

    applied: list[Any] = []
    real = mod._run_script

    def recording(conn: Any, path: Any) -> None:
        applied.append(path.name)
        real(conn, path)

    monkeypatch.setattr(mod, "_run_script", recording)
    with mod.open_postgres_kanban_store(url) as second:
        assert second.store_digest() != "unreadable"
    assert applied == [], f"the second open re-applied {applied}"
