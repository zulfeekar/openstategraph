"""`tool.mssql-query` — the T-SQL sibling, and the two mechanisms that are not
the SQLite one's (`osg-agent-experience/34`).

The SQLite family's docstring is proud that *"safety is the driver's, not
string matching"*: `mode=ro` is a property of the file the connection opens,
so however a statement is spelled the engine refuses it. **No MSSQL driver
offers that.** `ApplicationIntent=ReadOnly` is an availability-group routing
hint — it picks a replica, it does not refuse a write — so the guard here is
two things that are named rather than implied:

- a **statement gate**: exactly one statement, and it must be `SELECT` or
  `WITH … SELECT`;
- a transaction that is **never committed** (`autocommit=False`, always rolled
  back), so a write that somehow reached the server does not survive the call.

The tests below spend the failure list from the ticket's dimension 5 one input
at a time, which is the point of writing that list: a rule argued for and not
fired at is a rule this repository has shipped broken before.

Nothing here opens a socket. The driver is reached through one seam
(`_connect`) so a stub cursor can stand in for a warehouse, which is also the
only proof available in this pass — the owner's decision on 2026-09-04 was that
there is no live database yet and compile-and-validate is the whole proof.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openstategraph.prebuilt_mssql import MssqlQueryTool

#: The owner's `lenses.yaml` shape, reduced to what the allowlist reads: a
#: `resolvers` map whose members carry a `pin` map, and the pin **values** are
#: the physical tables a query may name.
LENSES = """
version: 1
resolvers:
  sales_invoices:
    description: Invoice line volumes.
    primary: [dbo.invoice_line]
    pin:
      dbo.invoice_line: dbo.invoice_line_v2
      dbo.dim_customer: dbo.dim_customer_latest
  catalogue_tracks:
    pin:
      dbo.track_counts: dbo.track_counts_v1r0
"""


@pytest.fixture()
def allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A lenses YAML inside a workflows root, returned as its relative path."""
    root = tmp_path / "workflows"
    (root / "cpl").mkdir(parents=True)
    (root / "cpl" / "lenses.yaml").write_text(LENSES, encoding="utf-8")
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    return "cpl/lenses.yaml"


class _StubCursor:
    """Just enough of a DB-API cursor to answer one SELECT."""

    def __init__(self) -> None:
        self.description = [("region", None), ("tonnes", None)]
        self.executed: list[str] = []

    def execute(self, sql: str) -> "_StubCursor":
        self.executed.append(sql)
        return self

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        return [("NW Europe", 1200), ("US Gulf", 980)][:size]


class _StubConnection:
    def __init__(self) -> None:
        self.cursor_obj = _StubCursor()
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> _StubCursor:
        return self.cursor_obj

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def stub(monkeypatch: pytest.MonkeyPatch) -> _StubConnection:
    """Stand a stub connection in at the module's single driver seam."""
    import contextlib

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


class TestTheEnvironmentVariableIsNamedNotHeld:
    def test_an_unset_variable_refuses_by_name_and_does_not_raise(
        self, allowlist: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENSTATEGRAPH_MSSQL_URL", raising=False)
        tool = MssqlQueryTool(connection="OPENSTATEGRAPH_MSSQL_URL", allowlist=allowlist)
        result = tool.run(query="SELECT 1 FROM dbo.invoice_line_v2")
        assert result.error is not None
        assert "OPENSTATEGRAPH_MSSQL_URL" in result.error

    def test_a_variable_set_to_blank_is_the_same_refusal(
        self, allowlist: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CPL_DSN", "   ")
        tool = MssqlQueryTool(connection="CPL_DSN", allowlist=allowlist)
        result = tool.run(query="SELECT 1 FROM dbo.invoice_line_v2")
        assert result.error is not None and "CPL_DSN" in result.error

    def test_the_connection_string_itself_is_never_the_field(
        self, allowlist: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A document is committed, so the field holds a **name**.

        Pasting a DSN produces a refusal that names it as a value, not a
        connection attempt — honesty gate 13, and the same refusal the config
        file gives for a pasted secret.
        """
        monkeypatch.delenv("Driver", raising=False)
        tool = MssqlQueryTool(
            connection="Driver={ODBC Driver 18};Server=x;Pwd=hunter2",
            allowlist=allowlist,
        )
        result = tool.run(query="SELECT 1 FROM dbo.invoice_line_v2")
        assert result.error is not None
        assert "hunter2" not in result.error
        assert "name" in result.error.lower()


class TestTheStatementGate:
    """Read-only is a gate here, because the driver does not offer one."""

    @pytest.fixture(autouse=True)
    def _dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_MSSQL_URL", "Server=warehouse;Database=cpl")

    @pytest.mark.parametrize(
        "query",
        [
            "DELETE FROM dbo.invoice_line_v2",
            "UPDATE dbo.invoice_line_v2 SET tonnes = 0",
            "INSERT INTO dbo.invoice_line_v2 (tonnes) VALUES (1)",
            "DROP TABLE dbo.invoice_line_v2",
            "TRUNCATE TABLE dbo.invoice_line_v2",
            "EXEC sp_who",
            "MERGE dbo.invoice_line_v2 USING x ON 1=1",
            "/**/dRoP TABLE dbo.invoice_line_v2",
            "SELECT * INTO other FROM dbo.invoice_line_v2",
        ],
    )
    def test_a_statement_that_is_not_a_select_is_refused(
        self, allowlist: str, stub: _StubConnection, query: str
    ) -> None:
        result = MssqlQueryTool(allowlist=allowlist).run(query=query)
        assert result.error is not None, query
        assert stub.cursor_obj.executed == [], query

    def test_a_second_statement_is_refused(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        result = MssqlQueryTool(allowlist=allowlist).run(
            query="SELECT 1 FROM dbo.invoice_line_v2; DROP TABLE dbo.dim_customer_latest"
        )
        assert result.error is not None
        assert "one" in result.error.lower()
        assert stub.cursor_obj.executed == []

    def test_a_cte_leading_to_a_select_is_allowed(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        result = MssqlQueryTool(allowlist=allowlist).run(
            query="WITH t AS (SELECT 1 AS a FROM dbo.invoice_line_v2) SELECT a FROM t"
        )
        assert result.error is None, result.error
        assert stub.cursor_obj.executed


class TestTheAllowlist:
    @pytest.fixture(autouse=True)
    def _dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_MSSQL_URL", "Server=warehouse;Database=cpl")

    def test_an_unpinned_table_is_refused_and_the_pins_are_printed(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        result = MssqlQueryTool(allowlist=allowlist).run(
            query="SELECT * FROM dbo.employee_salary"
        )
        assert result.error is not None
        assert "dbo.employee_salary" in result.error
        assert "dbo.invoice_line_v2" in result.error
        assert "dbo.track_counts_v1r0" in result.error
        assert stub.cursor_obj.executed == []

    def test_the_logical_name_is_not_the_pin(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        """`dbo.invoice_line` is a key; `dbo.invoice_line_v2` is what may be read.

        The whole point of a pin is that the version is chosen by a human, so
        naming the unversioned logical table is exactly the mistake the pin
        exists to catch.
        """
        result = MssqlQueryTool(allowlist=allowlist).run(query="SELECT * FROM dbo.invoice_line")
        assert result.error is not None and "dbo.invoice_line" in result.error

    def test_every_table_in_a_join_is_checked(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        result = MssqlQueryTool(allowlist=allowlist).run(
            query=(
                "SELECT c.tonnes FROM dbo.invoice_line_v2 AS c "
                "JOIN dbo.employee_salary AS p ON p.id = c.id"
            )
        )
        assert result.error is not None and "dbo.employee_salary" in result.error

    def test_an_allowlist_outside_the_workflows_root_is_refused(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        result = MssqlQueryTool(allowlist="../../etc/passwd").run(
            query="SELECT 1 FROM dbo.invoice_line_v2"
        )
        assert result.error is not None and "allowlist" in result.error.lower()

    def test_an_unset_allowlist_is_refused_rather_than_permitting_everything(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        """The dangerous default is the one that reads as configured."""
        result = MssqlQueryTool().run(query="SELECT 1 FROM dbo.invoice_line_v2")
        assert result.error is not None and "allowlist" in result.error.lower()


class TestAQueryThatRuns:
    @pytest.fixture(autouse=True)
    def _dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_MSSQL_URL", "Server=warehouse;Database=cpl")

    def test_rows_come_back_as_the_familys_markdown_table(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        result = MssqlQueryTool(allowlist=allowlist).run(
            query="SELECT region, tonnes FROM dbo.invoice_line_v2"
        )
        assert result.error is None, result.error
        assert "| region | tonnes |" in result.content
        assert "| NW Europe | 1200 |" in result.content

    def test_the_transaction_is_always_rolled_back(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        MssqlQueryTool(allowlist=allowlist).run(
            query="SELECT region FROM dbo.invoice_line_v2"
        )
        assert stub.rolled_back and stub.closed

    def test_the_row_cap_bounds_the_answer(
        self, allowlist: str, stub: _StubConnection
    ) -> None:
        result = MssqlQueryTool(allowlist=allowlist, row_cap=1).run(
            query="SELECT region, tonnes FROM dbo.invoice_line_v2"
        )
        assert "NW Europe" in result.content
        assert "US Gulf" not in result.content
        assert "truncated" in result.content


class TestTheFamilyContract:
    """The four canonical assertions, plus what the family already promises."""

    def test_it_is_a_read_and_says_so(self) -> None:
        assert MssqlQueryTool.side_effecting is False
        assert MssqlQueryTool.open_world is False

    def test_configure_returns_a_fresh_instance(self) -> None:
        tool = MssqlQueryTool()
        configured = tool.configure(
            {"connection": "CPL_DSN", "allowlist": "cpl/lenses.yaml", "maxRows": "50"}
        )
        assert configured is not tool
        assert isinstance(configured, MssqlQueryTool)
        assert configured.connection == "CPL_DSN"
        assert configured.allowlist == "cpl/lenses.yaml"
        assert configured.row_cap == 50
        assert tool.connection == "OPENSTATEGRAPH_MSSQL_URL"

    def test_configure_is_deterministic(self) -> None:
        data = {"connection": "CPL_DSN", "allowlist": "cpl/lenses.yaml", "maxRows": "50"}
        first, second = MssqlQueryTool().configure(data), MssqlQueryTool().configure(data)
        assert (first.connection, first.allowlist, first.row_cap) == (
            second.connection,
            second.allowlist,
            second.row_cap,
        )

    def test_an_invalid_argument_comes_back_as_data(self) -> None:
        result = MssqlQueryTool().run(nonsense=1)
        assert result.ok is False and result.error

    def test_it_shares_the_sqlite_familys_base(self) -> None:
        """Never a copy — the ticket's own rule.

        The dialect and the connection differ; the `configure` shape, the
        markdown table and the refusal shape are the family's.
        """
        from openstategraph.prebuilt_sql import _SqlExplorerBase

        assert issubclass(MssqlQueryTool, _SqlExplorerBase)


class TestItIsRegisteredNotWiredIn:
    def test_the_process_tool_layer_carries_it(self) -> None:
        """Registered into the process layer — never wired into the engine.

        `_process_tool_layer` is the list `docs/building-an-atom.md` names;
        `build_tool_registry` assembles layers and holds no list of its own.
        """
        from openstategraph.api.registries import _process_tool_layer

        builtin, _plugins = _process_tool_layer()
        assert "tool.mssql-query" in builtin

    def test_the_node_vocabulary_lists_it(self) -> None:
        import json
        from pathlib import Path

        specs = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "openstategraph"
                / "compile"
                / "port_specs.json"
            ).read_text(encoding="utf-8")
        )
        entry = next(
            (e for e in specs["node_types"] if e["type"] == "tool.mssql-query"), None
        )
        assert entry is not None, "tool.mssql-query is missing from the generated catalogue"
        assert {"connection", "allowlist", "maxRows"} <= set(entry["field_keys"])


class TestTheDriverIsOptional:
    def test_the_base_wheel_does_not_gain_a_driver(self) -> None:
        """`pyodbc` is an extra, and the four core dependencies are unchanged."""
        import tomllib
        from pathlib import Path

        pyproject = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        project = pyproject["project"]
        assert not any("pyodbc" in dep for dep in project["dependencies"])
        assert any("pyodbc" in dep for dep in project["optional-dependencies"]["mssql"])

    def test_a_missing_driver_refuses_by_naming_the_extra(
        self, allowlist: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import openstategraph.prebuilt_mssql as mod

        monkeypatch.setenv("OPENSTATEGRAPH_MSSQL_URL", "Server=warehouse")

        def _no_driver(name: str) -> Any:
            raise ModuleNotFoundError("No module named 'pyodbc'")

        monkeypatch.setattr(mod.importlib, "import_module", _no_driver)
        result = MssqlQueryTool(allowlist=allowlist).run(
            query="SELECT 1 FROM dbo.invoice_line_v2"
        )
        assert result.error is not None
        assert "openstategraph[mssql]" in result.error
