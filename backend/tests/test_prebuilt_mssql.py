"""`tool.mssql-query` — what is this leaf's and not the family's.

**Most of this file moved on 2026-09-05** (`osg-agent-experience/40`). The
statement gate, the allowlist, the "a field holds a variable name" refusals, the
row cap, the markdown table and the registration are the *family's*, and they
are asserted once, parametrised by dialect, in `test_prebuilt_warehouse.py`.
Leaving copies here would have been two statements of one rule with a second
dialect arriving to make them disagree — the duplication defect the family base
exists to prevent, committed by the tests that guard it.

What is left is the T-SQL leaf's own:

- `EXEC`, which is a write no other dialect in this family spells;
- the **uncommitted transaction**, which is the one read-only mechanism MSSQL
  can supply and Databricks cannot — asserted here rather than described, so
  the difference between the two leaves cannot quietly disappear;
- `pyodbc`, and the extra a missing driver names;
- the default connection variable, which is ours (`OPENSTATEGRAPH_MSSQL_URL`)
  because ODBC has no conventional one — the Databricks leaf borrows the
  vendor's three instead, and that asymmetry is a decision, not an oversight;
- the card hint that says the allowlist path is a refusal rather than a
  convention (`41`);
- and the family base holding nothing shaped for a file (`39`).

Nothing here opens a socket, and no driver is installed in this checkout.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest

from openstategraph.prebuilt_mssql import DEFAULT_CONNECTION_ENV, MssqlQueryTool
from tests.test_prebuilt_warehouse import LENSES, _StubConnection


@pytest.fixture()
def allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A lenses YAML inside a workflows root, returned as its relative path."""
    root = tmp_path / "workflows"
    (root / "analyst").mkdir(parents=True)
    (root / "analyst" / "lenses.yaml").write_text(LENSES, encoding="utf-8")
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    return "analyst/lenses.yaml"


@pytest.fixture()
def connected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DEFAULT_CONNECTION_ENV, "Server=warehouse;Database=warehouse")


@pytest.fixture()
def stub(monkeypatch: pytest.MonkeyPatch) -> _StubConnection:
    """Stand a stub connection in at this module's single driver seam."""
    import openstategraph.prebuilt_mssql as mod

    conn = _StubConnection()

    @contextlib.contextmanager
    def _fake(dsn: str) -> Any:
        try:
            yield conn
        finally:
            conn.rollback()
            conn.close()

    monkeypatch.setattr(mod, "_connect", _fake)
    return conn


@pytest.mark.usefixtures("connected")
class TestWhatOnlyTSqlSpells:
    def test_exec_is_refused(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        """A stored procedure can do anything, and its head is not `SELECT`.

        The family's gate covers it — `EXEC` is simply not `SELECT` or `WITH` —
        but it is written here because no other dialect in this family has the
        keyword, and a gate that stopped recognising it would be green in the
        parametrised suite.
        """
        result = MssqlQueryTool(allowlist=allowlist).run(query="EXEC sp_who")
        assert result.error is not None
        assert stub.cursor_obj.executed == []

    def test_the_default_connection_variable_is_ours_not_a_vendors(self) -> None:
        """ODBC publishes no conventional variable for a DSN, so we minted one.

        The Databricks leaf borrows the vendor's three names instead. Pinned so
        the asymmetry stays a decision somebody made rather than a difference
        somebody notices.
        """
        assert DEFAULT_CONNECTION_ENV == "OPENSTATEGRAPH_MSSQL_URL"
        assert MssqlQueryTool().connection == DEFAULT_CONNECTION_ENV


@pytest.mark.usefixtures("connected")
class TestTheTransactionIsAlwaysRolledBack:
    """The second read-only mechanism, which this leaf has and its sibling does not.

    `prebuilt_sql`'s SQLite tools get `mode=ro` from the driver; no warehouse
    driver offers that. MSSQL can at least decline to commit — `autocommit=False`
    with an unconditional `rollback()` — so anything that reached the server
    despite the statement gate does not survive the call. `DatabricksQueryTool`
    cannot make this promise and does not; asserting it here is what stops the
    two leaves' guarantees being read as one.
    """

    def test_a_query_that_ran_still_rolls_back_and_closes(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        MssqlQueryTool(allowlist=allowlist).run(query="SELECT region FROM dbo.invoice_line_v2")
        assert stub.rolled_back and stub.closed

    def test_the_seam_opens_without_autocommit(self) -> None:
        """Read off the source: running it needs a driver, which is not here."""
        source = (
            Path(__file__).resolve().parents[1] / "openstategraph" / "prebuilt_mssql.py"
        ).read_text(encoding="utf-8")
        assert "pyodbc.connect(dsn, autocommit=False)" in source


class TestTheDriverIsOptional:
    def test_the_base_wheel_does_not_gain_a_driver(self) -> None:
        """`pyodbc` is an extra, and the core dependencies are unchanged."""
        import tomllib

        pyproject = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        project = pyproject["project"]
        assert not any("pyodbc" in dep for dep in project["dependencies"])
        assert any("pyodbc" in dep for dep in project["optional-dependencies"]["mssql"])

    def test_a_missing_driver_refuses_by_naming_the_extra(
        self, allowlist: str, connected: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import openstategraph.prebuilt_mssql as mod

        def _no_driver(name: str) -> Any:
            raise ModuleNotFoundError("No module named 'pyodbc'")

        monkeypatch.setattr(mod.importlib, "import_module", _no_driver)
        result = MssqlQueryTool(allowlist=allowlist).run(
            query="SELECT 1 FROM dbo.invoice_line_v2"
        )
        assert result.error is not None
        assert "openstategraph[mssql]" in result.error


class TestTheFamilyBaseHoldsNothingShapedForAFile:
    """`osg-agent-experience/39` — asked of the base rather than of a leaf.

    The per-leaf half of this ("no refusal reachable from this node names
    sqlite") is parametrised in `test_prebuilt_warehouse.py`; what stays here is
    the statement about `_SqlExplorerBase` itself, which no leaf can make.
    """

    def test_the_family_base_holds_no_dialect_shaped_member(self) -> None:
        from openstategraph.prebuilt_sql import _SqlExplorerBase

        assert not hasattr(_SqlExplorerBase, "database")
        assert not hasattr(_SqlExplorerBase, "_db")
        assert not hasattr(_SqlExplorerBase, "_refusal")


class TestTheAllowlistHintNamesTheRefusal:
    """`osg-agent-experience/41` — the sentence and the behaviour, one fact.

    The field's hint said *"a YAML file inside `workflows/`"*, which reads as a
    convention. It is a refusal: `_pins()` resolves the path under the
    workflows root and calls `relative_to(root)`, so a file one level above it
    is refused and no query is sent. A session read the sentence as advice,
    then moved a 42 KB file and nine readers to satisfy it.

    Asserted against the generated catalogue rather than the TypeScript source,
    because the catalogue is what every non-editor door reads — and against the
    refusal's own words, so the two cannot drift into two descriptions of one
    rule.
    """

    OUTSIDE = "outside the workflows root"

    def _hint(self) -> str:
        from openstategraph.compile.node_catalogue import CATALOGUE

        schema = CATALOGUE.field_schema["tool.mssql-query"]
        record = next(
            node for node in CATALOGUE.nodes if node["type"] == "tool.mssql-query"
        )
        assert schema["allowlist"].path_root == "workflows"
        return next(
            field["hint"] for field in record["fields"] if field["key"] == "allowlist"
        )

    def test_the_hint_carries_the_refusals_own_words(self) -> None:
        assert self.OUTSIDE in self._hint().lower()
        assert "refused" in self._hint().lower()

    def test_the_refusal_says_the_same_thing(self) -> None:
        result = MssqlQueryTool(allowlist="../../etc/passwd").run(query="SELECT 1")
        assert result.ok is False
        assert self.OUTSIDE in str(result.error).lower()
