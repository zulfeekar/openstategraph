"""Every table the shared board brings into `public` fails closed —
`team-board-and-gap-reports/14`.

`supabase db advisors --type security`, run against the owner's project right
after `0003` was applied::

    ERROR rls_disabled_in_public — Table `public.kanban_schema_migrations`
    is public, but RLS has not been enabled.

`0002` enabled and forced RLS on `cards`, `0003` did the same for
`gap_report_rate` in the file that created it, and the migration ledger had
neither — because it was the one table no migration file created. The store
creates it itself, in `_migrate`, before it can read which files a database has
already run; a census that reads only `*.sql` therefore cannot see it, and did
not. `0004` now creates it as well, so that the maintainers' CLI can apply the
same file against a database our runner has never opened.

So this suite counts tables from **both** places a table can be born:

- every `create table if not exists public.<name>` in `kanban_migrations/*.sql`;
- `LEDGER_TABLE`, the one the runner creates in Python.

and holds each to `enable row level security` **and** `force row level
security` somewhere in the migration files — the same or a later one, since
`0002` secures a table `0001` created.

`test_the_shared_board_has_a_reviewable_schema` already makes the first half of
that claim. It is not extended in place because the claim here is a different
one: not *the SQL secures the tables the SQL creates*, which is a closed loop,
but *the SQL secures every table this package puts in `public`*, whichever file
— or module — created it. The ledger is the whole difference between the two
sentences, and it is the table the advisor named.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

from openstategraph.kanban_postgres import LEDGER_TABLE, migration_files

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "openstategraph"


def migration_sql() -> str:
    """Every migration, commentary stripped — what the database is told.

    The same reading `test_the_shared_board_has_a_reviewable_schema` does, and
    for the same reason: these files argue for themselves at length, and a
    paragraph *about* row security is not row security.
    """
    lines: list[str] = []
    for path in migration_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            lines.append(line.split("--", 1)[0].rstrip())
    return "\n".join(lines)


def tables_this_package_creates() -> set[str]:
    """Every table the board puts in `public`, from both of its two makers."""
    from_files = set(
        re.findall(
            r"create table if not exists (public\.\w+)",
            migration_sql(),
            re.IGNORECASE,
        )
    )
    assert from_files, "no tables created by the migration files"
    return from_files | {LEDGER_TABLE}


def test_the_ledger_is_counted_as_a_table_this_package_creates() -> None:
    """The census's own premise, pinned. The ledger is born in Python, in
    `_migrate`, because it must exist before the runner can read which files a
    database has already had applied — so a census reading only `.sql` returns
    a set that does not contain it, which is exactly the state the advisor
    found and would be indistinguishable from a green run without this line."""
    assert LEDGER_TABLE in tables_this_package_creates()
    ledger_ddl = re.search(
        r"create table if not exists \{LEDGER_TABLE\}",
        (PACKAGE_ROOT / "kanban_postgres.py").read_text(encoding="utf-8"),
    )
    assert ledger_ddl is not None, (
        "the runner no longer creates the ledger itself — if a migration file "
        "does it now, drop this special case rather than leaving two makers "
        "claimed for one table"
    )


def test_the_ledger_s_two_makers_declare_the_same_columns() -> None:
    """`0004` creates the ledger as well as securing it, because the CLI
    applier never opens the store and would otherwise be asked to alter a
    relation that is not there. That is a second copy of one table's shape, and
    a second copy is a thing that drifts — so the columns are compared rather
    than trusted. There is no third place: this is a two-column ledger, not
    schema anybody reviews, and the alternative (the runner reading its own
    `.sql`) is a chicken-and-egg the runner cannot have."""
    runner = (PACKAGE_ROOT / "kanban_postgres.py").read_text(encoding="utf-8")
    in_python = set(re.findall(r"\b(version|applied_at)\b", runner))
    body = re.search(
        rf"create table if not exists {re.escape(LEDGER_TABLE)} \((.*?)\);",
        migration_sql(),
        re.DOTALL,
    )
    assert body is not None, f"no migration creates {LEDGER_TABLE}"
    in_sql = {
        line.strip().split()[0] for line in body.group(1).splitlines() if line.strip()
    }
    assert in_sql == in_python, f"the ledger is {in_sql} in SQL and {in_python} in Python"
    assert "timestamptz" in body.group(1) and "timestamptz" in runner


@pytest.mark.parametrize("table", sorted(tables_this_package_creates()))
def test_every_table_has_row_security_enabled_and_forced(table: str) -> None:
    """`enable` alone leaves the table owner exempt; the store connects as an
    owner-level role, so `force` is the half that makes the claim about
    anything other than a hypothetical second account. Neither is asked for in
    the file that created the table — `0002` secures `0001`'s table — so the
    search is over all of them, in order."""
    sql = migration_sql()
    assert f"alter table {table} enable row level security" in sql, (
        f"{table} is public with RLS disabled — the advisor reports this as "
        "rls_disabled_in_public"
    )
    assert f"alter table {table} force row level security" in sql, (
        f"{table} enables RLS without forcing it, so its owner is exempt"
    )


@pytest.mark.parametrize("table", sorted(tables_this_package_creates()))
def test_no_table_is_secured_before_it_exists(table: str) -> None:
    """A migration that alters a table nothing has created yet fails on apply,
    on the owner's database, at the one moment nobody is watching a test run.
    Filename order is apply order for both appliers, so the file that secures a
    table may not sort before the file that creates it — and a table born in
    Python must be created by the file that secures it, since the CLI applier
    never opens the store."""
    securing = next(
        path
        for path in migration_files()
        if f"alter table {table} enable row level security"
        in path.read_text(encoding="utf-8")
    )
    creating = [
        path
        for path in migration_files()
        if re.search(
            rf"create table if not exists {re.escape(table)}\b",
            path.read_text(encoding="utf-8"),
        )
    ]
    assert creating, (
        f"{securing.name} secures {table} without any file creating it — the "
        "CLI applies these files against a database our runner has never "
        "opened, where the table would not be there"
    )
    assert creating[0].name <= securing.name, (
        f"{securing.name} secures {table}, created only in {creating[0].name}"
    )


#: The live half. `OPENSTATEGRAPH_KANBAN_TEST_URL` and never the board's own
#: variable, for the reason `test_the_shared_board_applies_its_own_migrations`
#: gives: the board variable points at the maintainers' real board.
LIVE_URL_ENV = "OPENSTATEGRAPH_KANBAN_TEST_URL"


def test_the_runner_still_works_through_forced_rls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forcing RLS on the ledger with no policy at all is a table that fails
    closed for every role that is not `bypassrls`, and the runner *writes* that
    ledger on every open. The claim that this is safe rests entirely on the URL
    naming an owner-level role, which is a property of a database and cannot be
    read off a file — so it is asserted where a database exists and skipped
    where one does not, rather than believed."""
    url = os.environ.get(LIVE_URL_ENV, "").strip()
    if not url:
        pytest.skip(
            f"{LIVE_URL_ENV} is not set — forced RLS on the ledger is only "
            "provable against a database. Export it to a scratch database."
        )
    pytest.importorskip("psycopg")
    from openstategraph import kanban_postgres as mod

    with mod.open_postgres_kanban_store(url) as first:
        assert first.store_digest() != "unreadable"

    applied: list[str] = []
    real = mod._run_script

    def recording(conn: Any, path: Any) -> None:
        applied.append(path.name)
        real(conn, path)

    monkeypatch.setattr(mod, "_run_script", recording)
    with mod.open_postgres_kanban_store(url) as second:
        assert second.store_digest() != "unreadable"
    assert applied == [], (
        f"the second open re-applied {applied} — the runner could not read its "
        "own ledger back through the row security it just enabled"
    )
