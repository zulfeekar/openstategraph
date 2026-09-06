"""The shared board's schema, read as text — `team-board-and-gap-reports/03`.

CI has no Postgres, so nothing here connects to one. What it does instead is
read the migration files the store applies and the CLI pushes, and hold them
to the four things a reader cannot check by eye on a database they cannot see:

- **the column list is the `Card` dataclass**, so a new field on a card is a
  red test naming the migration that has to add it rather than a `KeyError` on
  somebody's board;
- **the `check` constraints are `Stage` / `BOARD_PRIORITIES` / `BOARD_AREAS`**,
  the same tuples the SQLite store and the editor already agree on. They are
  typed into a `.sql` file because a file `supabase db push` sends must be the
  bytes we applied — generating them at runtime would make the pushed file and
  the applied file two different things — so the pin is what keeps the one
  copy honest;
- **RLS is on and forced on every table these files create**, with every
  policy carrying an ownership predicate on `project_hash` rather than a bare
  role;
- **the package never learns the word Supabase.** The owner's decision, and
  the reason the store is "a Postgres URL" and nothing more.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from openstategraph.kanban_postgres import migration_files
from openstategraph.kanban_store import (
    BOARD_AREAS,
    BOARD_PRIORITIES,
    Card,
    Stage,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "backend" / "openstategraph"

#: The two columns the shared table has that a `Card` does not carry:
#: the tenancy key (a hash of the project id, never the id) and the
#: database-maintained watermark the board's poll reads.
EXTRA_COLUMNS = ("project_hash", "updated_at")


def migration_text() -> str:
    """Every migration, as SQL with its commentary removed.

    Stripped because these files argue for themselves at length, the way every
    module here does, and a comment that *names* `varchar` while explaining why
    the schema has none would fail the very assertion it agrees with. What is
    asserted below is what the database is told, not what a reader is told.
    """
    lines: list[str] = []
    for path in migration_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("--", 1)[0].rstrip()
            lines.append(code)
    return "\n".join(lines)


def create_table_body(sql: str, table: str) -> str:
    match = re.search(
        rf"create table if not exists public\.{table} \((.*?)\n\);",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert match is not None, f"no create table for {table}"
    return match.group(1)


def declared_columns(body: str) -> list[str]:
    names: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        names.append(stripped.split()[0])
    return names


def test_the_files_are_numbered_and_ordered() -> None:
    """Applied in filename order, by the store and by the CLI both. The digit
    prefix is what `supabase db push` reads as a version, so a file that does
    not carry one is a file only one of the two would apply."""
    names = [path.name for path in migration_files()]
    assert names, "no migrations shipped"
    assert names == sorted(names)
    for name in names:
        assert re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", name), name


def test_the_columns_are_the_card_plus_the_tenancy_key() -> None:
    body = create_table_body(migration_text(), "cards")
    expected = {field.name for field in dataclasses.fields(Card)} | set(EXTRA_COLUMNS)
    assert set(declared_columns(body)) == expected


@pytest.mark.parametrize(
    ("constraint", "values"),
    [
        ("cards_stage_check", tuple(stage.value for stage in Stage)),
        ("cards_priority_check", BOARD_PRIORITIES),
        ("cards_area_check", BOARD_AREAS),
    ],
)
def test_each_check_constraint_is_the_tuple_it_mirrors(
    constraint: str, values: tuple[str, ...]
) -> None:
    sql = migration_text()
    match = re.search(rf"constraint {constraint}\s*\n?\s*check \(([^)]*)\)", sql)
    assert match is not None, f"{constraint} is not declared"
    listed = tuple(re.findall(r"'([a-zA-Z]+)'", match.group(1)))
    assert listed == values, f"{constraint} lists {listed}, the tuple is {values}"


def test_every_table_these_files_create_has_rls_enabled_and_forced() -> None:
    sql = migration_text()
    tables = set(re.findall(r"create table if not exists (public\.\w+)", sql))
    assert tables, "no tables created"
    for table in tables:
        assert f"alter table {table} enable row level security" in sql, table
        assert f"alter table {table} force row level security" in sql, table


def test_every_policy_names_the_tenancy_key_rather_than_only_a_role() -> None:
    """`TO authenticated` alone is authentication without authorization. Every
    policy carries the ownership predicate as well, and an `update` carries it
    twice — without `with check` a row can be reassigned to another project."""
    sql = migration_text()
    policies = re.findall(
        r"create policy (\w+) on public\.\w+\s+for (\w+)(.*?);", sql, re.DOTALL
    )
    assert policies, "no policies declared"
    for name, command, body in policies:
        assert "project_hash" in body, f"{name} has no ownership predicate"
        assert "(select " in body, f"{name} calls a function per row"
        if command == "update":
            assert "using" in body and "with check" in body, name
        if command == "insert":
            assert "with check" in body, name


def test_the_anon_role_gets_no_policy_and_no_grant() -> None:
    """Insert-only for a door with no `gh` is `team-board-and-gap-reports/09`,
    and it arrives with its own migration. Until then `anon` reads nothing and
    writes nothing, said explicitly rather than left to a default."""
    sql = migration_text()
    assert "revoke all on table public.cards from anon" in sql
    assert not re.search(r"create policy \w+ on public\.\w+[^;]*to anon", sql)


def test_a_constraint_is_added_the_only_way_postgres_allows() -> None:
    """`add constraint if not exists` is a syntax error, so an idempotent
    migration guards on `pg_constraint` instead. Asserted because the failure
    is at apply time on the owner's database, not here."""
    sql = migration_text()
    assert "add constraint if not exists" not in sql
    if "add constraint" in sql:
        assert "pg_constraint" in sql


def test_the_types_are_the_postgres_ones() -> None:
    sql = migration_text()
    assert "varchar" not in sql
    assert not re.search(r"\btimestamp\b(?!tz)", sql)
    # Identifiers unquoted and lowercase: no `"CamelCase"` anywhere.
    assert not re.search(r'"[A-Za-z_]*[A-Z][A-Za-z_]*"', sql)


def test_the_cli_reads_the_same_bytes_the_store_applies() -> None:
    """One copy of the SQL, not two kept identical by a test.

    `supabase/migrations/` is where the CLI looks and
    `openstategraph/kanban_migrations/` is what ships in the wheel, so the
    obvious shape is a copy in each and a drift test. A symlink is better than
    a drift test for the same reason `CLAUDE.md` prefers resolving through the
    alias table to restating it: there is one copy of the bytes, so drift is
    not detected late, it is impossible. The CLI accepts it because its
    migration filter is `^([0-9]+)_(.*)\\.sql$` on the file name — a directory
    read follows the link like any other.
    """
    link = REPO_ROOT / "supabase" / "migrations"
    assert link.is_symlink(), f"{link} must be the symlink, never a second copy"
    assert link.resolve() == (PACKAGE_ROOT / "kanban_migrations").resolve()


def test_no_shipped_module_learns_the_word_supabase() -> None:
    """The owner's decision, as an instrument. From the package's point of
    view the team board is a Postgres URL — no vendor name, no SDK, no key.
    The repository knows the word (this test does, and so does the directory
    the CLI reads); the wheel does not."""
    offenders = [
        path.relative_to(PACKAGE_ROOT)
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".sql", ".json", ".yaml", ".yml", ".md"}
        and "supabase" in path.read_text(encoding="utf-8", errors="ignore").lower()
    ]
    assert offenders == [], f"shipped files name the vendor: {offenders}"
