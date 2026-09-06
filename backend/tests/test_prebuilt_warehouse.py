"""The warehouse family, asserted once and parametrised by dialect.

`osg-agent-experience/40` asked one question of the shape `39` left behind: *if
a leaf needs more than a driver, a connection and a dialect name to exist, the
base is wrong.* These are the tests that answer it. Every assertion here was
written against `tool.mssql-query` in `34` and lives in this file now because a
second leaf — `tool.databricks-query` — must pass every one of them unchanged.
A behaviour that needs a per-dialect version of its test is a behaviour that did
not belong on the rung, and moving these rather than copying them is what makes
that visible.

What stays in `test_prebuilt_mssql.py` and `test_prebuilt_databricks.py` is what
is genuinely one dialect's: which driver module is imported, which extra a
missing driver names, whether the connection can decline to commit, and the
field a leaf reads to find its connection — three variables for one and a single
one for the other, which is the whole reason this is parametrised by a
descriptor rather than by a class name.

Nothing here opens a socket. Each leaf reaches its driver through one seam, so a
stub cursor stands in for a warehouse — which remains the only proof available:
the owner's decision of 2026-09-04 was that there is no live database, and
neither driver is installed in this checkout.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

from openstategraph.prebuilt_databricks import DatabricksQueryTool
from openstategraph.prebuilt_mssql import MssqlQueryTool

#: The owner's `lenses.yaml` shape, reduced to what the allowlist reads: a
#: `resolvers` map whose members carry a `pin` map, and the pin **values** are
#: the physical tables a query may name.
#:
#: The third resolver is three-part on purpose. Unity Catalog names a table
#: `catalog.schema.table`, and until `40` the identifier scan had exactly two
#: capture groups — it read `main.sales.invoice_line` as the table `main.sales`,
#: which no pin can ever name, so a legal Databricks query was refused with a
#: sentence naming a table nobody had written. T-SQL writes four-part names too,
#: so this is not a Databricks special case; it is a defect `34` shipped that
#: only a second dialect made visible.
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
  unity_catalogue:
    pin:
      main.sales.invoice_line: main.sales.invoice_line_v2
"""


@dataclass(frozen=True)
class Dialect:
    """One leaf, and the three things about it a family test has to be told."""

    label: str
    module: str
    node_type: str
    make: Callable[..., Any]
    #: The variables its `_connection()` reads, with values that resolve.
    env: dict[str, str] = field(default_factory=dict)
    #: The card keys its `configure()` reads, beyond `allowlist` and `maxRows`.
    connection_keys: tuple[str, ...] = ()


DIALECTS = [
    Dialect(
        label="mssql",
        module="openstategraph.prebuilt_mssql",
        node_type="tool.mssql-query",
        make=lambda **kw: MssqlQueryTool(**kw),
        env={"OPENSTATEGRAPH_MSSQL_URL": "Server=warehouse;Database=warehouse"},
        connection_keys=("connection",),
    ),
    Dialect(
        label="databricks",
        module="openstategraph.prebuilt_databricks",
        node_type="tool.databricks-query",
        make=lambda **kw: DatabricksQueryTool(**kw),
        env={
            "DATABRICKS_SERVER_HOSTNAME": "dbc-example.cloud.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/abc123",
            "DATABRICKS_TOKEN": "a-token-value",
        },
        connection_keys=("serverHostname", "httpPath", "token"),
    ),
]


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


@pytest.fixture(params=DIALECTS, ids=lambda d: d.label)
def dialect(request: pytest.FixtureRequest) -> Dialect:
    return request.param


@pytest.fixture()
def allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A lenses YAML inside a workflows root, returned as its relative path."""
    root = tmp_path / "workflows"
    (root / "analyst").mkdir(parents=True)
    (root / "analyst" / "lenses.yaml").write_text(LENSES, encoding="utf-8")
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    return "analyst/lenses.yaml"


@pytest.fixture()
def connected(dialect: Dialect, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every variable this dialect reads, set to something that resolves."""
    for name, value in dialect.env.items():
        monkeypatch.setenv(name, value)


@pytest.fixture()
def stub(dialect: Dialect, monkeypatch: pytest.MonkeyPatch) -> _StubConnection:
    """Stand a stub connection in at this leaf's single driver seam."""
    import importlib

    module = importlib.import_module(dialect.module)
    conn = _StubConnection()

    @contextlib.contextmanager
    def _fake(*args: Any, **kwargs: Any) -> Any:
        try:
            yield conn
        finally:
            with contextlib.suppress(Exception):
                conn.rollback()
            conn.close()

    monkeypatch.setattr(module, "_connect", _fake)
    return conn


class TestTheEnvironmentVariableIsNamedNotHeld:
    """Honesty gate 13, for every leaf: a field holds a name, never a value."""

    def test_an_unset_variable_refuses_by_name_and_does_not_raise(
        self, dialect: Dialect, allowlist: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in dialect.env:
            monkeypatch.delenv(name, raising=False)
        result = dialect.make(allowlist=allowlist).run(
            query="SELECT 1 FROM dbo.invoice_line_v2"
        )
        assert result.error is not None
        assert any(name in result.error for name in dialect.env), result.error

    def test_a_variable_set_to_blank_is_the_same_refusal(
        self, dialect: Dialect, allowlist: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in dialect.env:
            monkeypatch.setenv(name, "   ")
        result = dialect.make(allowlist=allowlist).run(
            query="SELECT 1 FROM dbo.invoice_line_v2"
        )
        assert result.error is not None
        assert any(name in result.error for name in dialect.env), result.error

    @pytest.mark.usefixtures("connected")
    def test_a_pasted_value_is_refused_as_a_value_and_never_echoed(
        self, dialect: Dialect, allowlist: str
    ) -> None:
        """A DSN, a URL or a token pasted where a *name* goes.

        The refusal must say the field holds a name, and must not repeat what
        was pasted — a refusal that echoes a credential has published it into a
        run log.
        """
        pasted = "Driver={ODBC Driver 18};Server=x;Pwd=hunter2"
        for key in dialect.connection_keys:
            result = dialect.make(allowlist=allowlist, **{_attr(key): pasted}).run(
                query="SELECT 1 FROM dbo.invoice_line_v2"
            )
            assert result.error is not None, key
            assert "hunter2" not in result.error, key
            assert "name" in result.error.lower(), key


def _attr(field_key: str) -> str:
    """`serverHostname` → `server_hostname`: the card's key as the leaf's kwarg."""
    import re

    return re.sub(r"(?<!^)(?=[A-Z])", "_", field_key).lower()


@pytest.mark.usefixtures("connected")
class TestTheStatementGate:
    """Read-only is a gate here, because no warehouse driver offers one."""

    @pytest.mark.parametrize(
        "query",
        [
            "DELETE FROM dbo.invoice_line_v2",
            "UPDATE dbo.invoice_line_v2 SET tonnes = 0",
            "INSERT INTO dbo.invoice_line_v2 (tonnes) VALUES (1)",
            "DROP TABLE dbo.invoice_line_v2",
            "TRUNCATE TABLE dbo.invoice_line_v2",
            "MERGE dbo.invoice_line_v2 USING x ON 1=1",
            "/**/dRoP TABLE dbo.invoice_line_v2",
            "SELECT * INTO other FROM dbo.invoice_line_v2",
        ],
    )
    def test_a_statement_that_is_not_a_select_is_refused(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection, query: str
    ) -> None:
        result = dialect.make(allowlist=allowlist).run(query=query)
        assert result.error is not None, query
        assert stub.cursor_obj.executed == [], query

    def test_a_second_statement_is_refused(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        result = dialect.make(allowlist=allowlist).run(
            query="SELECT 1 FROM dbo.invoice_line_v2; DROP TABLE dbo.dim_customer_latest"
        )
        assert result.error is not None
        assert "one" in result.error.lower()
        assert stub.cursor_obj.executed == []

    def test_a_cte_leading_to_a_select_is_allowed(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        result = dialect.make(allowlist=allowlist).run(
            query="WITH t AS (SELECT 1 AS a FROM dbo.invoice_line_v2) SELECT a FROM t"
        )
        assert result.error is None, result.error
        assert stub.cursor_obj.executed


@pytest.mark.usefixtures("connected")
class TestTheAllowlist:
    def test_an_unpinned_table_is_refused_and_the_pins_are_printed(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        result = dialect.make(allowlist=allowlist).run(
            query="SELECT * FROM dbo.employee_salary"
        )
        assert result.error is not None
        assert "dbo.employee_salary" in result.error
        assert "dbo.invoice_line_v2" in result.error
        assert "dbo.track_counts_v1r0" in result.error
        assert stub.cursor_obj.executed == []

    def test_the_logical_name_is_not_the_pin(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        """`dbo.invoice_line` is a key; `dbo.invoice_line_v2` is what may be read."""
        result = dialect.make(allowlist=allowlist).run(
            query="SELECT * FROM dbo.invoice_line"
        )
        assert result.error is not None and "dbo.invoice_line" in result.error

    def test_every_table_in_a_join_is_checked(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        result = dialect.make(allowlist=allowlist).run(
            query=(
                "SELECT c.tonnes FROM dbo.invoice_line_v2 AS c "
                "JOIN dbo.employee_salary AS p ON p.id = c.id"
            )
        )
        assert result.error is not None and "dbo.employee_salary" in result.error

    def test_a_three_part_name_is_read_whole(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        """`catalog.schema.table`, which `34`'s two-group regex could not see.

        The pinned three-part name runs; the unpinned one is refused **by its
        whole name**. Both halves matter: the first is the legal query that was
        refused, and the second is what would happen if the fix were to stop
        scanning three-part names at all.
        """
        allowed = dialect.make(allowlist=allowlist).run(
            query="SELECT region FROM main.sales.invoice_line_v2"
        )
        assert allowed.error is None, allowed.error

        refused = dialect.make(allowlist=allowlist).run(
            query="SELECT region FROM main.hr.employee_salary"
        )
        assert refused.error is not None
        assert "main.hr.employee_salary" in refused.error

    def test_an_allowlist_outside_the_workflows_root_is_refused(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        result = dialect.make(allowlist="../../etc/passwd").run(
            query="SELECT 1 FROM dbo.invoice_line_v2"
        )
        assert result.error is not None and "allowlist" in result.error.lower()
        assert "outside the workflows root" in result.error.lower()

    def test_an_unset_allowlist_is_refused_rather_than_permitting_everything(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        """The dangerous default is the one that reads as configured."""
        result = dialect.make().run(query="SELECT 1 FROM dbo.invoice_line_v2")
        assert result.error is not None and "allowlist" in result.error.lower()


@pytest.mark.usefixtures("connected")
class TestAQueryThatRuns:
    def test_rows_come_back_as_the_familys_markdown_table(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        result = dialect.make(allowlist=allowlist).run(
            query="SELECT region, tonnes FROM dbo.invoice_line_v2"
        )
        assert result.error is None, result.error
        assert "| region | tonnes |" in result.content
        assert "| NW Europe | 1200 |" in result.content

    def test_the_connection_is_always_closed(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        """Closed for every dialect. *Rolled back* is a per-leaf promise."""
        dialect.make(allowlist=allowlist).run(query="SELECT region FROM dbo.invoice_line_v2")
        assert stub.closed

    def test_the_row_cap_bounds_the_answer(
        self, dialect: Dialect, allowlist: str, stub: _StubConnection
    ) -> None:
        result = dialect.make(allowlist=allowlist, row_cap=1).run(
            query="SELECT region, tonnes FROM dbo.invoice_line_v2"
        )
        assert "NW Europe" in result.content
        assert "US Gulf" not in result.content
        assert "truncated" in result.content


class TestTheFamilyContract:
    """The four canonical assertions, plus what the family already promises."""

    def test_it_is_a_read_and_says_so(self, dialect: Dialect) -> None:
        tool = dialect.make()
        assert type(tool).side_effecting is False
        assert type(tool).open_world is False

    def test_configure_returns_a_fresh_instance(self, dialect: Dialect) -> None:
        tool = dialect.make()
        data = {"allowlist": "analyst/lenses.yaml", "maxRows": "50"}
        data.update({key: f"VAR_{key.upper()}" for key in dialect.connection_keys})
        configured = tool.configure(data)
        assert configured is not tool
        assert isinstance(configured, type(tool))
        assert configured.allowlist == "analyst/lenses.yaml"
        assert configured.row_cap == 50
        assert tool.allowlist == ""
        for key in dialect.connection_keys:
            assert getattr(configured, _attr(key)) == f"VAR_{key.upper()}"

    def test_configure_is_deterministic(self, dialect: Dialect) -> None:
        data = {"allowlist": "analyst/lenses.yaml", "maxRows": "50"}
        data.update({key: f"VAR_{key.upper()}" for key in dialect.connection_keys})
        first, second = dialect.make().configure(data), dialect.make().configure(data)
        for attr in ("allowlist", "row_cap", *(_attr(k) for k in dialect.connection_keys)):
            assert getattr(first, attr) == getattr(second, attr), attr

    def test_an_invalid_argument_comes_back_as_data(self, dialect: Dialect) -> None:
        result = dialect.make().run(nonsense=1)
        assert result.ok is False and result.error

    def test_it_sits_on_the_warehouse_rung_and_not_on_the_file_one(
        self, dialect: Dialect
    ) -> None:
        """Never a copy — the ticket's own rule, and never the SQLite rung."""
        from openstategraph.prebuilt_sql import _SqlExplorerBase, _SqliteExplorerBase
        from openstategraph.prebuilt_warehouse import _WarehouseExplorerBase

        leaf = type(dialect.make())
        assert issubclass(leaf, _WarehouseExplorerBase)
        assert issubclass(leaf, _SqlExplorerBase)
        assert not issubclass(leaf, _SqliteExplorerBase)

    def test_the_leaf_declares_no_database_field(self, dialect: Dialect) -> None:
        """`39` — a warehouse has no `.sqlite` path to be told to go and set."""
        assert not hasattr(dialect.make(), "database")

    def test_no_refusal_this_node_can_produce_names_sqlite(
        self, dialect: Dialect, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every refusal reachable from an unconfigured node of this dialect.

        Asked of the tool rather than of the source, so a member inherited from
        anywhere is included: whatever a reader standing at this node can be
        told, none of it names a file format this node cannot read.
        """
        for name in dialect.env:
            monkeypatch.delenv(name, raising=False)
        pasted = {_attr(key): "Server=tcp:x;Uid=y" for key in dialect.connection_keys}
        blank = {_attr(key): "" for key in dialect.connection_keys}
        refusals = [
            dialect.make().run(query="SELECT 1"),
            dialect.make(allowlist="nowhere/lenses.yaml").run(query="SELECT 1"),
            dialect.make(allowlist="../../etc/passwd").run(query="SELECT 1"),
            dialect.make(**blank).run(query="SELECT 1"),
            dialect.make(**pasted).run(query="SELECT 1"),
        ]
        texts = [str(result.error or "") for result in refusals]
        assert all(texts), texts
        assert not any("sqlite" in text.lower() for text in texts), texts


class TestEachLeafIsRegisteredNotWiredIn:
    def test_the_process_tool_layer_carries_it(self, dialect: Dialect) -> None:
        """Registered into the process layer — never wired into the engine."""
        from openstategraph.api.registries import _process_tool_layer

        builtin, _plugins = _process_tool_layer()
        assert dialect.node_type in builtin

    def test_the_node_vocabulary_lists_it_with_its_keys(self, dialect: Dialect) -> None:
        import json

        specs = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "openstategraph"
                / "compile"
                / "port_specs.json"
            ).read_text(encoding="utf-8")
        )
        entry = next(
            (e for e in specs["node_types"] if e["type"] == dialect.node_type), None
        )
        assert entry is not None, f"{dialect.node_type} is missing from the catalogue"
        expected = {"allowlist", "maxRows", *dialect.connection_keys}
        assert expected <= set(entry["field_keys"])
