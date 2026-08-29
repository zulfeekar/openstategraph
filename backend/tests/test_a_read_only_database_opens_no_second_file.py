"""`mode=ro` says *this file is read-only*. It does not say *only this file*.

`the-boundary-nobody-checked/06`. The connection is opened with `uri=True`
so that `mode=ro` can be spelled at all — and `uri=True` is also what makes
SQLite honour URI parameters in `ATTACH`, where an attached database carries
its **own** mode. The string reaching `execute()` is a tool-call argument, so
it is written by a model.

Probed on this checkout before the fix, against a real `mode=ro` connection:

    ATTACH DATABASE 'file:/tmp/…?mode=rwc' AS x   ->  ok, file created
    VACUUM INTO '/tmp/…'                          ->  ok, 825 KB written

The second line is the one the ticket did not have. `VACUUM INTO` needs no
attach and no second statement, so the bound the ticket recorded — *file
creation only, because sqlite3 refuses two statements per `execute` and the
tool opens a fresh connection per call* — held for `ATTACH` and did not hold
for the file family as a whole: a single model-authored statement copies the
whole database to any absolute path the process can write.

Both are one action code. SQLite reports `ATTACH`, `DETACH`, `VACUUM` and
`VACUUM INTO` to an authorizer as `SQLITE_ATTACH`/`SQLITE_DETACH`, with the
target path as `arg1`, so denying the pair closes the family at the driver —
which is the property `prebuilt_sql`'s docstring is proud of and the reason
nothing here parses SQL.
"""

from __future__ import annotations

import ast
import pathlib
import sqlite3

import pytest

import openstategraph
from openstategraph.evaluation.denotation import execute_query
from openstategraph.prebuilt_sql import SqlGetSchemaTool, SqlListTablesTool, SqlQueryTool
from openstategraph.readonly_sqlite import readonly_connection
from openstategraph.workflows_root import workflows_root

CHINOOK = "chinook-assistant/data/Chinook_Sqlite.sqlite"

PACKAGE_ROOT = pathlib.Path(openstategraph.__path__[0])
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _database() -> pathlib.Path:
    return workflows_root() / CHINOOK


@pytest.fixture()
def target(tmp_path: pathlib.Path) -> pathlib.Path:
    """A path the process can certainly write, that certainly does not exist."""
    return tmp_path / "second.db"


def _statements(path: pathlib.Path) -> list[str]:
    return [
        f"ATTACH DATABASE 'file:{path}?mode=rwc' AS x",
        f"ATTACH DATABASE '{path}' AS x",
        f"VACUUM INTO '{path}'",
        f"vacuum   into   '{path}'",
    ]


class TestTheToolCannotReachASecondFile:
    """The layer the defect lives at: the tool, asserting on the filesystem."""

    @pytest.mark.parametrize("index", range(4))
    def test_no_file_appears(self, target: pathlib.Path, index: int) -> None:
        statement = _statements(target)[index]
        result = SqlQueryTool(database=CHINOOK).run(query=statement)

        assert result.error is not None, statement
        assert not target.exists(), f"{statement} created {target}"

    def test_the_refusal_names_a_next_step_in_our_words(
        self, target: pathlib.Path
    ) -> None:
        """A bare `not authorized` teaches a model nothing it can act on."""
        result = SqlQueryTool(database=CHINOOK).run(
            query=f"ATTACH DATABASE 'file:{target}?mode=rwc' AS x"
        )

        assert result.error is not None
        assert "second" in result.error.lower()
        assert "sql_list_tables" in result.error
        assert "not authorized" not in result.error


class TestTheEvalHarnessSharesTheBoundary:
    """`denotation` grades rather than runs, and the *predicted* query is still
    the model's — its own module docstring says so. Not an exemption."""

    @pytest.mark.parametrize("index", range(4))
    def test_a_predicted_query_creates_no_file(
        self, target: pathlib.Path, index: int
    ) -> None:
        outcome = execute_query(_database(), _statements(target)[index])

        assert not outcome.ok
        assert not target.exists()


class TestChinooksOwnToolsShareIt:
    """`ExecuteSqlTool` refuses a non-`SELECT` by prefix, and says in its own
    comment that the check is for clear errors rather than for safety. So the
    check is asserted at the connection, where the safety actually is."""

    def test_its_connection_refuses_a_second_file(
        self, target: pathlib.Path
    ) -> None:
        from openstategraph.compile.node_runtime import chinook_tool_registry

        assert chinook_tool_registry() is not None  # the tools import at all
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_chinook_under_test",
            REPO_ROOT / "workflows" / "chinook-assistant" / "tools" / "chinook.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        conn = module.connect_readonly()
        try:
            for statement in _statements(target):
                with pytest.raises(sqlite3.Error):
                    conn.execute(statement)
                assert not target.exists(), statement
        finally:
            conn.close()


class TestTheDatabaseIsStillReadable:
    """The refusal is narrow. Everything the family needs still works."""

    def test_tables_and_counts(self) -> None:
        result = SqlListTablesTool(database=CHINOOK).run()
        assert result.error is None and "Track" in result.content

    def test_pragma_backed_schema_still_answers(self) -> None:
        result = SqlGetSchemaTool(database=CHINOOK).run(table="Track")
        assert result.error is None and "Album.AlbumId" in result.content

    def test_a_join_still_answers(self) -> None:
        result = SqlQueryTool(database=CHINOOK).run(
            query="SELECT ar.Name FROM Artist ar JOIN Album al "
            "ON ar.ArtistId = al.ArtistId LIMIT 2"
        )
        assert result.error is None and result.content.strip()

    def test_a_gold_query_still_grades(self) -> None:
        outcome = execute_query(_database(), "SELECT COUNT(*) FROM Artist")
        assert outcome.ok and outcome.rows


class TestTheConnectionItself:
    def test_it_is_still_read_only(self) -> None:
        with readonly_connection(_database()) as conn:
            with pytest.raises(sqlite3.Error):
                conn.execute("DROP TABLE Artist")

    def test_it_records_what_it_refused(self, target: pathlib.Path) -> None:
        """So the sentence a model reads can name the file, not the errno."""
        with readonly_connection(_database()) as conn:
            with pytest.raises(sqlite3.Error):
                conn.execute(f"ATTACH DATABASE '{target}' AS x")
            assert conn.refused_second_file


class TestNoModuleOpensItsOwn:
    """One seam plus this test, the shape `api/diagram.py` landed today.

    Six call sites spelled the same URI by hand; the seventh would have
    inherited the hole in silence.
    """

    def test_every_read_only_open_goes_through_the_seam(self) -> None:
        roots = [PACKAGE_ROOT, REPO_ROOT / "workflows"]
        offenders: list[str] = []
        for root in roots:
            for path in sorted(root.rglob("*.py")):
                if path.name == "readonly_sqlite.py":
                    continue
                # Parsed, not grepped: this file and three docstrings quote the
                # very URI they exist to forbid.
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "connect"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "sqlite3"
                        and any(kw.arg == "uri" for kw in node.keywords)
                    ):
                        offenders.append(str(path))
                        break
        assert not offenders, (
            "these open a URI sqlite connection by hand, so `mode=ro` is theirs "
            f"and the ATTACH refusal is not: {offenders} — call "
            "openstategraph.readonly_sqlite.readonly_connection"
        )
