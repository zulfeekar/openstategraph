"""`osg-agent-experience/78` — three refusals, three sentences, one pin list.

A warehouse read can fail in three unrelated ways and, until this ticket, all
three arrived at the model wearing one sentence: *"The database refused the
query: … Rewrite the SELECT against the allowed tables: …"*. Measured on a
live run of 2026-09-06 with the server unreachable, that sentence carried an
ODBC `HYT00 Login timeout expired` — a fault raised by `SQLDriverConnect`,
before any statement was sent — and told the model to rewrite a query nothing
had objected to. The run spent its whole budget doing exactly that.

So the classes are separated here rather than described:

1. **Connection** — the driver is not importable, or the connect/login failed.
   No statement reached the server, so the remedy is never a rewrite, and the
   sentence says so in words a model reads.
2. **Statement gate / the server's own refusal** — a rewrite is the remedy, and
   the pins are named so the rewrite has somewhere to land.
3. **Allowlist** — a table nobody pinned, named beside the ones that are.

And the list itself: whole, or elided with a count. Never cut mid-name, which
is the third defect the ticket recorded (`gb.region_gro` is not a table).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

import pytest

from openstategraph.prebuilt_databricks import DatabricksQueryTool
from openstategraph.prebuilt_mssql import MssqlQueryTool
from openstategraph.prebuilt_warehouse import pin_list

CARGO = "\n".join(
    [
        "resolvers:",
        "  cargo_flows:",
        "    pin:",
        "      gb.flow: gb.flow_v1r0",
        "      gb.country: gb.country_v1r0",
        "  gas_balances:",
        "    pin:",
        "      gb.balance: gb.balance_v1r0",
    ]
)


@pytest.fixture()
def allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = tmp_path / "workflows"
    (root / "analyst").mkdir(parents=True)
    (root / "analyst" / "lenses.yaml").write_text(CARGO, encoding="utf-8")
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    return "analyst/lenses.yaml"


@pytest.fixture()
def mssql_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSTATEGRAPH_MSSQL_URL", "Server=nowhere;Database=warehouse")


def _tool(allowlist: str, **kw: Any) -> MssqlQueryTool:
    return MssqlQueryTool(allowlist=allowlist, pins="cargo_flows", **kw)


def _run(tool: Any, query: str = "SELECT * FROM gb.flow_v1r0") -> str:
    result = tool.run(query=query)
    assert not result.ok
    return result.error or ""


def _fails_at(module: str, monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """Make this leaf's one driver seam raise on __enter__ — a connect fault."""
    import importlib

    @contextlib.contextmanager
    def _boom(*args: Any, **kwargs: Any) -> Iterator[Any]:
        raise exc
        yield  # pragma: no cover

    monkeypatch.setattr(importlib.import_module(module), "_connect", _boom)


class _Cursor:
    description = [("a", None)]

    def execute(self, sql: str) -> "_Cursor":
        raise RuntimeError("Invalid column name 'tonnnes'.")


class _Connection:
    def cursor(self) -> _Cursor:
        return _Cursor()

    def rollback(self) -> None: ...

    def close(self) -> None: ...


def _statement_fails(module: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    @contextlib.contextmanager
    def _ok(*args: Any, **kwargs: Any) -> Iterator[Any]:
        yield _Connection()

    monkeypatch.setattr(importlib.import_module(module), "_connect", _ok)


class TestAConnectionFaultIsNotAStatementFault:
    """Done-when 1 and 4: named as a connection fault, no rewrite, no tables."""

    def test_a_login_timeout_does_not_ask_for_a_rewrite(
        self, allowlist: str, mssql_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fails_at(
            "openstategraph.prebuilt_mssql",
            monkeypatch,
            RuntimeError(
                "('HYT00', '[HYT00] [Microsoft][ODBC Driver 18 for SQL Server]"
                "Login timeout expired (0) (SQLDriverConnect)')"
            ),
        )
        message = _run(_tool(allowlist))
        assert "Login timeout expired" in message
        assert "Rewrite the SELECT" not in message
        assert "rewrite" in message.lower()  # it says NOT to
        assert "gb.balance_v1r0" not in message
        assert "gb.flow_v1r0" not in message

    def test_a_missing_driver_is_a_connection_fault_too(
        self, allowlist: str, mssql_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fails_at(
            "openstategraph.prebuilt_mssql",
            monkeypatch,
            ModuleNotFoundError("No module named 'pyodbc'"),
        )
        message = _run(_tool(allowlist))
        assert "Rewrite the SELECT" not in message
        assert "no query was sent" in message.lower()
        assert "openstategraph[" in message

    def test_the_other_leaf_separates_them_the_same_way(
        self, allowlist: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name, value in (
            ("DATABRICKS_SERVER_HOSTNAME", "dbc-1.cloud.databricks.com"),
            ("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc"),
            ("DATABRICKS_TOKEN", "a-token-value"),
        ):
            monkeypatch.setenv(name, value)
        _fails_at(
            "openstategraph.prebuilt_databricks",
            monkeypatch,
            RuntimeError("Error during request to server: connection refused"),
        )
        message = _run(
            DatabricksQueryTool(allowlist=allowlist, pins="cargo_flows"),
        )
        assert "connection refused" in message
        assert "Rewrite the SELECT" not in message


class TestAStatementFaultKeepsTheRewriteAdvice:
    """Done-when 1, second half: the class that *is* actionable keeps its remedy."""

    def test_a_server_side_statement_error_still_says_rewrite(
        self, allowlist: str, mssql_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _statement_fails("openstategraph.prebuilt_mssql", monkeypatch)
        message = _run(_tool(allowlist))
        assert "Invalid column name" in message
        assert "Rewrite the SELECT" in message
        assert "gb.flow_v1r0" in message


class TestTheListIsThisBindingsPins:
    """Done-when 2: the pins in force for the node that asked, not the file."""

    def test_an_unpinned_table_names_only_this_lens(
        self, allowlist: str, mssql_env: None
    ) -> None:
        message = _run(_tool(allowlist), "SELECT * FROM gb.nope")
        assert "gb.flow_v1r0" in message
        assert "gb.balance_v1r0" not in message


class TestTheListIsNeverCutMidName:
    """Done-when 3: elided with a count, and never ending inside an identifier."""

    def test_a_long_list_is_elided_and_says_so(self) -> None:
        names = {f"gb.region_growth_table_{n:03d}_v1r0" for n in range(200)}
        rendered = pin_list(names)
        assert len(rendered) < 900
        assert "more" in rendered
        assert str(len(names)) in rendered
        for shown in rendered.split(" (and ")[0].split(", "):
            assert shown in names

    def test_a_short_list_is_rendered_whole(self) -> None:
        assert pin_list({"a.b", "c.d"}) == "a.b, c.d"

    def test_no_refusal_ends_inside_an_identifier(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mssql_env: None
    ) -> None:
        root = tmp_path / "workflows"
        (root / "analyst").mkdir(parents=True)
        pins = "\n".join(
            [f"      gb.t{n:03d}: gb.region_growth_{n:03d}_v1r0" for n in range(200)]
        )
        (root / "analyst" / "lenses.yaml").write_text(
            f"resolvers:\n  cargo_flows:\n    pin:\n{pins}\n", encoding="utf-8"
        )
        monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
        message = _run(_tool("analyst/lenses.yaml"), "SELECT * FROM gb.nope")
        every = {f"gb.region_growth_{n:03d}_v1r0" for n in range(200)}
        listed = message.rsplit("Readable tables are: ", 1)[1]
        head = listed.split(" (and ")[0]
        for shown in head.split(", "):
            assert shown in every, f"cut mid-name: {shown!r}"
