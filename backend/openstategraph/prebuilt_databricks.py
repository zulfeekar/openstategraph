"""`tool.databricks-query` — one read-only SELECT against a SQL warehouse.

The third leaf of the SQL family (`osg-agent-experience/40`), and the one that
was built to test the shape rather than to serve a caller: `39` split the family
so that a new dialect would cost *a driver, a connection and a dialect name*,
and this module is the receipt. Everything else — the one-statement gate, the
allowlist of pinned tables, the "a field holds a variable **name**" refusals,
the order those refusals happen in, the row cap and the markdown table — is
inherited from `_WarehouseExplorerBase` and `_SqlExplorerBase` and appears
nowhere below.

**Three variables, not one, and they are the vendor's own names.** The MSSQL
leaf's `connection` field names a single variable holding an ODBC DSN, because
ODBC has a DSN and no conventional variable to keep it in, so we minted
`OPENSTATEGRAPH_MSSQL_URL`. `databricks-sql-connector` has neither: its
`sql.connect()` takes `server_hostname`, `http_path` and `access_token` as three
separate arguments, and there is no connection-string form in its API to fold
them into. Inventing `OPENSTATEGRAPH_DATABRICKS_URL` would have meant defining a
URL grammar nobody documents, parsing it here, and putting a token inside a
string — three costs for the cosmetic benefit of one field looking like the
other leaf's.

So the card carries three fields, each holding the *name* of a variable, and
their defaults are the names Databricks' own documentation uses in every
example — `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`,
`DATABRICKS_TOKEN` (verified 2026-09-05 against the Python SQL connector page,
connector 4.5.0). A machine already set up for the connector therefore works
with no card edits at all, which is the argument for borrowing a vendor's names
rather than minting our own: the alternative is a second name for a variable the
developer has already exported.

**Read-only is the family's weaker word, and here it is weaker still.** The rung
explains why no warehouse gets SQLite's `mode=ro`. What is specific to this leaf
is that it cannot supply MSSQL's *second* mechanism either. A Databricks SQL
warehouse has no session read-only mode, and the connector's `autocommit`
handling has moved between releases — 4.2.0 changed the commit/autocommit
properties on the connection object, and passing `autocommit` at connect time
has been observed to fail against warehouses with *"Configuration AUTOCOMMIT is
not available"*. So this leaf does not ask for one. It calls `rollback()` on the
way out if the connection offers it, suppressing the refusal if it does not,
and the guarantee it actually makes is the statement gate plus the allowlist.
A workflow that needs more wants a service principal that cannot write, and
`docs/on-the-canvas.md` says so for both warehouse leaves at once.

**No live warehouse was reachable while this was built, and no driver is
installed in this checkout.** Both halves are stated rather than implied: the
tests drive a stub cursor through the one seam below, and the missing-driver
path is the one path this pass can prove end to end — which it does, by naming
the extra.

`databricks-sql-connector` is an optional extra (`openstategraph[databricks]`),
imported lazily at the one seam below, so the base wheel's dependencies are
unchanged.
"""

from __future__ import annotations

import contextlib
import importlib
from typing import Any, Iterator

from pydantic import Field

from openstategraph.prebuilt_sql import DEFAULT_MAX_ROWS
from openstategraph.prebuilt_warehouse import WarehouseQueryArgs, _WarehouseExplorerBase

#: The three variables Databricks' own examples read. Defaults are *names*, and
#: a name is safe in a way a value never is — it is a pointer, and the thing it
#: points at is refused when unset.
DEFAULT_HOST_ENV = "DATABRICKS_SERVER_HOSTNAME"
DEFAULT_HTTP_PATH_ENV = "DATABRICKS_HTTP_PATH"
DEFAULT_TOKEN_ENV = "DATABRICKS_TOKEN"

#: The extra that carries the driver. Named in the refusal rather than in a doc
#: page, because the refusal is where somebody is standing when they need it.
DRIVER_EXTRA = "openstategraph[databricks]"


@contextlib.contextmanager
def _connect(server_hostname: str, http_path: str, access_token: str) -> Iterator[Any]:
    """The one driver seam — lazy, and always closed.

    The three keyword arguments are the connector's own, in the order its
    documentation writes them. No `autocommit` is passed: see the module
    docstring — asking for one has been observed to fail against a warehouse,
    and a connection that refuses to open is a worse answer than a read whose
    transaction guarantee is honestly described as absent.
    """
    driver = importlib.import_module("databricks.sql")
    connection = driver.connect(
        server_hostname=server_hostname,
        http_path=http_path,
        access_token=access_token,
    )
    try:
        yield connection
    finally:
        # Offered rather than promised: a warehouse with no session transaction
        # raises here, and that is not an error the caller can act on.
        with contextlib.suppress(Exception):
            connection.rollback()
        with contextlib.suppress(Exception):
            connection.close()


class DatabricksQueryArgs(WarehouseQueryArgs):
    query: str = Field(description="A single read-only Databricks SQL SELECT statement.")


class DatabricksQueryTool(_WarehouseExplorerBase):
    """One Databricks SQL SELECT, against tables an allowlist pinned."""

    name = "databricks_query"
    node_type = "tool.databricks-query"
    description = (
        "Run one read-only SELECT against the configured Databricks SQL warehouse. "
        "Only tables pinned in the workflow's allowlist may be named; the refusal "
        "lists them."
    )
    Args = DatabricksQueryArgs

    _driver_extra = DRIVER_EXTRA
    _driver_label = "Databricks SQL"

    def __init__(
        self,
        *,
        server_hostname: str = DEFAULT_HOST_ENV,
        http_path: str = DEFAULT_HTTP_PATH_ENV,
        token: str = DEFAULT_TOKEN_ENV,
        allowlist: str = "",
        pins: str = "",
        row_cap: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self.server_hostname = server_hostname
        self.http_path = http_path
        self.token = token
        super().__init__(allowlist=allowlist, pins=pins, row_cap=row_cap)

    def configure(self, data: dict[str, Any]) -> "DatabricksQueryTool":
        def named(key: str, current: str) -> str:
            return str(data.get(key) or "").strip() or current

        return type(self)(
            server_hostname=named("serverHostname", self.server_hostname),
            http_path=named("httpPath", self.http_path),
            token=named("token", self.token),
            allowlist=str(data.get("allowlist") or "").strip() or self.allowlist,
            pins=str(data.get("pins") or "").strip() or self.pins,
            row_cap=self._row_cap_from(data, self.row_cap),
        )

    def _connection(self) -> tuple[tuple[Any, ...], str | None]:
        """The three variables, resolved in the order the connector takes them.

        First refusal wins, so a node with nothing configured is told about its
        hostname rather than about all three at once — one thing to go and do.
        """
        resolved: list[str] = []
        for key, name, default, holds in (
            ("serverHostname", self.server_hostname, DEFAULT_HOST_ENV,
             "a workspace hostname such as 'dbc-1234.cloud.databricks.com'"),
            ("httpPath", self.http_path, DEFAULT_HTTP_PATH_ENV,
             "a warehouse HTTP path such as '/sql/1.0/warehouses/abc123'"),
            ("token", self.token, DEFAULT_TOKEN_ENV, "a personal access token"),
        ):
            value, refusal = self._env_value(key=key, name=name, default=default, holds=holds)
            if refusal:
                return (), refusal
            resolved.append(value)
        return tuple(resolved), None

    def _open(self, target: tuple[Any, ...]) -> Any:
        return _connect(*target)


DATABRICKS_TOOLS = [DatabricksQueryTool()]
