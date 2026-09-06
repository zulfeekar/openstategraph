"""`tool.databricks-query` — what is this leaf's and not the family's.

The family behaviour is asserted once, parametrised by dialect, in
`test_prebuilt_warehouse.py`; this leaf passes every one of those unchanged,
which is the answer `osg-agent-experience/40` set out to get. What is here is
the residue — the four things that are genuinely Databricks' and would be a lie
if they were written as the family's:

- the driver module the seam imports, and the extra a missing one names;
- the three variables, with the vendor's own names as their defaults;
- a **pasted personal access token**, which the regex alone admits — `dapi…` is
  a credential *and* a legal environment-variable name, the same collision
  `CLAUDE.md` records for `ghp_…`;
- the transaction guarantee this leaf does **not** make, asserted rather than
  described, so the docstring cannot drift away from the code.

Nothing here opens a socket, and no driver is installed in this checkout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openstategraph.prebuilt_databricks import DatabricksQueryTool
from tests.test_prebuilt_warehouse import LENSES


@pytest.fixture()
def allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = tmp_path / "workflows"
    (root / "analyst").mkdir(parents=True)
    (root / "analyst" / "lenses.yaml").write_text(LENSES, encoding="utf-8")
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    return "analyst/lenses.yaml"


@pytest.fixture()
def connected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_SERVER_HOSTNAME", "dbc-example.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc123")
    monkeypatch.setenv("DATABRICKS_TOKEN", "a-token-value")


class _FakeCursor:
    def __init__(self) -> None:
        self.description = [("region", None), ("tonnes", None)]
        self.executed: list[str] = []

    def execute(self, sql: str) -> "_FakeCursor":
        self.executed.append(sql)
        return self

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        return [("NW Europe", 1200), ("US Gulf", 980)][:size]


class _FakeConnection:
    def __init__(self, *, rollback_raises: bool) -> None:
        self._rollback_raises = rollback_raises
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor()

    def rollback(self) -> None:
        if self._rollback_raises:
            raise RuntimeError("Configuration AUTOCOMMIT is not available. SQLSTATE: 42K0I")

    def close(self) -> None:
        self.closed = True


class _FakeDriver:
    """`databricks.sql`, as much of it as this leaf calls: `connect(**kwargs)`.

    Injected at `importlib.import_module` rather than at `_connect`, so every
    line of the shipped seam runs — the lazy import, the keyword names, and the
    `finally` that rolls back and closes.
    """

    def __init__(self, *, rollback_raises: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.connection: _FakeConnection | None = None
        self._rollback_raises = rollback_raises

    def connect(self, **kwargs: Any) -> _FakeConnection:
        self.calls.append(kwargs)
        self.connection = _FakeConnection(rollback_raises=self._rollback_raises)
        return self.connection


def _install(monkeypatch: pytest.MonkeyPatch, driver: _FakeDriver) -> None:
    import openstategraph.prebuilt_databricks as mod

    def _import(name: str) -> Any:
        assert name == "databricks.sql", name
        return driver

    monkeypatch.setattr(mod.importlib, "import_module", _import)



class TestTheThreeVariablesAreTheVendorsOwn:
    """One field per connector argument, defaulting to the documented name.

    Verified 2026-09-05 against the Databricks Python SQL connector page: every
    example reads `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH` and
    `DATABRICKS_TOKEN`, and `sql.connect()` takes the three as separate
    arguments with no connection-string form. A single `OPENSTATEGRAPH_*` URL
    field would have meant inventing a grammar nobody documents.
    """

    def test_the_defaults_are_names_the_connector_documents(self) -> None:
        tool = DatabricksQueryTool()
        assert tool.server_hostname == "DATABRICKS_SERVER_HOSTNAME"
        assert tool.http_path == "DATABRICKS_HTTP_PATH"
        assert tool.token == "DATABRICKS_TOKEN"

    def test_the_first_missing_variable_is_the_one_reported(
        self, allowlist: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One thing to go and do, not three at once.

        The hostname is resolved first, so a node with nothing configured is
        told about the hostname; set that and the next refusal moves on.
        """
        for name in ("DATABRICKS_SERVER_HOSTNAME", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN"):
            monkeypatch.delenv(name, raising=False)
        query = "SELECT 1 FROM dbo.invoice_line_v2"

        first = DatabricksQueryTool(allowlist=allowlist).run(query=query)
        assert first.error is not None
        assert "DATABRICKS_SERVER_HOSTNAME" in first.error
        assert "DATABRICKS_HTTP_PATH" not in first.error

        monkeypatch.setenv("DATABRICKS_SERVER_HOSTNAME", "dbc-example.cloud.databricks.com")
        second = DatabricksQueryTool(allowlist=allowlist).run(query=query)
        assert second.error is not None and "DATABRICKS_HTTP_PATH" in second.error

    def test_the_variables_reach_the_driver_by_the_connectors_own_names(
        self, allowlist: str, connected: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`server_hostname=`, `http_path=`, `access_token=` — the vendor's names.

        Asserted against a **fake driver module** standing in for
        `databricks.sql` rather than against a patched `_connect`, so the real
        seam runs: a leaf that resolved its three variables in a different order
        would send a token where a hostname goes, and the failure would come
        back from the vendor rather than from us. No driver is installed here,
        so this is also the only way to watch the call at all.
        """
        driver = _FakeDriver()
        _install(monkeypatch, driver)
        DatabricksQueryTool(allowlist=allowlist).run(query="SELECT 1 FROM dbo.invoice_line_v2")
        assert driver.calls == [
            {
                "server_hostname": "dbc-example.cloud.databricks.com",
                "http_path": "/sql/1.0/warehouses/abc123",
                "access_token": "a-token-value",
            }
        ]


class TestAPastedTokenIsRefusedThoughItIsALegalVariableName:
    """The collision `CLAUDE.md` records for `ghp_…`, in this field.

    A Databricks personal access token begins `dapi` and is otherwise letters
    and digits — so it matches the POSIX environment-variable name regex
    exactly. The regex on its own therefore accepts a pasted credential into a
    committed document and then refuses the query for naming a variable nobody
    set, which reads as a configuration mistake rather than as a leak.

    The fix is the maintained prefix list, not a cleverer rule, for the reason
    that list already carries: an entropy heuristic refuses legitimate values.
    """

    def test_a_pasted_token_is_refused_as_a_value(
        self, allowlist: str, connected: None
    ) -> None:
        # `connected` matters: with the other two variables resolving, the
        # refusal this asserts is the token's own. Without it the hostname
        # refuses first and the test passes having proved nothing — which is
        # how it was first written.
        pasted = "dapi1234567890abcdef1234567890abcdef"
        result = DatabricksQueryTool(allowlist=allowlist, token=pasted).run(
            query="SELECT 1 FROM dbo.invoice_line_v2"
        )
        assert result.error is not None
        assert pasted not in result.error
        assert "name" in result.error.lower()

    def test_the_prefix_is_on_the_one_maintained_list(self) -> None:
        """Named there, not re-listed here — one list, consulted twice."""
        from openstategraph.config_file import SECRET_VALUE_PREFIXES, looks_like_a_secret

        assert "dapi" in SECRET_VALUE_PREFIXES
        assert looks_like_a_secret("dapi1234567890abcdef1234567890abcdef")

    def test_an_ordinary_variable_name_is_still_accepted(
        self, allowlist: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The widening's cost, paid at the same time it is taken.

        A prefix list that refuses a legitimate name is worse than none, so the
        name a person would actually choose is asserted to still work.
        """
        monkeypatch.setenv("WAREHOUSE_TOKEN", "a-token-value")
        tool = DatabricksQueryTool(allowlist=allowlist, token="WAREHOUSE_TOKEN")
        assert tool.configure({"token": "WAREHOUSE_TOKEN"}).token == "WAREHOUSE_TOKEN"


class TestTheDriverIsOptional:
    def test_the_base_wheel_does_not_gain_a_driver(self) -> None:
        import tomllib

        pyproject = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        project = pyproject["project"]
        assert not any("databricks" in dep for dep in project["dependencies"])
        assert any(
            "databricks-sql-connector" in dep
            for dep in project["optional-dependencies"]["databricks"]
        )

    def test_a_missing_driver_refuses_by_naming_the_extra(
        self, allowlist: str, connected: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one path this pass can prove end to end — no driver is installed.

        Asserted through the real seam rather than through a patched `_connect`,
        so it is the module's own lazy import that is being watched.
        """
        import openstategraph.prebuilt_databricks as mod

        def _no_driver(name: str) -> Any:
            raise ModuleNotFoundError("No module named 'databricks'")

        monkeypatch.setattr(mod.importlib, "import_module", _no_driver)
        result = DatabricksQueryTool(allowlist=allowlist).run(
            query="SELECT 1 FROM dbo.invoice_line_v2"
        )
        assert result.error is not None
        assert "openstategraph[databricks]" in result.error
        assert "Databricks SQL" in result.error

    def test_the_seam_imports_the_connectors_own_module(self) -> None:
        """`databricks.sql`, which is what the extra installs.

        Read off the source rather than run, because running it needs the
        driver: the point is that the name in the lazy import and the name of
        the distribution in `[databricks]` describe the same install.
        """
        source = (
            Path(__file__).resolve().parents[1]
            / "openstategraph"
            / "prebuilt_databricks.py"
        ).read_text(encoding="utf-8")
        assert 'importlib.import_module("databricks.sql")' in source


class TestTheTransactionGuaranteeThisLeafDoesNotMake:
    """The difference from the T-SQL sibling, asserted so it cannot drift.

    `MssqlQueryTool` opens its connection `autocommit=False` and rolls back
    unconditionally — half of read-only that the driver can actually give.
    Databricks SQL has no session read-only, and the connector's autocommit
    handling has moved between releases (4.2.0 changed it; passing `autocommit`
    at connect time has been observed to fail with *"Configuration AUTOCOMMIT is
    not available"*). So this leaf asks for neither, and its guarantee is the
    statement gate plus the allowlist.

    A rollback is still *offered* on the way out and suppressed if the
    connection refuses it — free where it works, silent where it does not.
    """

    def test_the_seam_does_not_ask_for_autocommit(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "openstategraph"
            / "prebuilt_databricks.py"
        ).read_text(encoding="utf-8")
        connect = source[source.index("def _connect(") : source.index("class DatabricksQueryArgs")]
        assert "autocommit=" not in connect

    def test_a_connection_that_cannot_roll_back_still_closes(
        self, allowlist: str, connected: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The warehouse refuses `rollback()`; the query still answers.

        Through the real seam, against a fake driver — patching `_connect`
        would have tested a copy of the `finally` block rather than the one
        that ships.
        """
        driver = _FakeDriver(rollback_raises=True)
        _install(monkeypatch, driver)
        result = DatabricksQueryTool(allowlist=allowlist).run(
            query="SELECT region FROM dbo.invoice_line_v2"
        )
        assert result.error is None, result.error
        assert driver.connection is not None and driver.connection.closed
