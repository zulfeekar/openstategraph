"""`tool.mssql-query` — one read-only T-SQL statement against a warehouse.

The T-SQL leaf of the SQL family. What it owns is the whole of what a leaf is
allowed to own (`osg-agent-experience/40`): **a driver, a connection, and a
dialect name**. The statement gate, the allowlist, the environment-variable
name and the order the refusals happen in are `_WarehouseExplorerBase`'s, one
rung up in `prebuilt_warehouse`; the `maxRows` parse, the truncation-aware
markdown table and `side_effecting = False` are `_SqlExplorerBase`'s, one rung
above that (`39`).

It sits *beside* `_SqliteExplorerBase` rather than under it (`39`). That rung
holds `database`, `_db()` and `_refusal()`, and a warehouse read over ODBC has
no file for any of them to name; while this class inherited them, a refusal
reachable from an MSSQL node could have told its reader to set a `.sqlite` path.

**Read-only here is not what read-only is in `prebuilt_sql`.** The family rung
says why for every dialect; what is specific to this one is that MSSQL *can*
supply the second mechanism and does. `ApplicationIntent=ReadOnly` — the string
an experienced reader will expect to see here — is an availability-group
**routing** hint: it picks a replica to talk to, and against a standalone server
it refuses nothing. So beyond the family's statement gate, the connection is
opened with `autocommit=False` and rolled back and closed in a `finally`, so
anything that reached the server despite the gate does not survive the call.
`DatabricksQueryTool` is the leaf that cannot do this, and its docstring says so
rather than leaving a reader to assume the family guarantee is uniform.

**No credential is ever held.** The `connection` field holds the *name* of an
environment variable, never a connection string — a document is committed. A
value pasted where a name goes is refused as a value, and the refusal does not
echo it back.

**And the connection is no longer one string.** `osg-agent-experience/73`: with
that variable unset the login is composed from named parts —
`MSSQL_DB_SERVER`, `MSSQL_DB_NAME`, and either a SQL login or an Azure AD
service principal — because a login that needs a secret otherwise needs the
secret pasted into the URL beside the variable that already held it, and
because ODBC Driver 18's own Azure AD flow hung for a full login timeout rather
than reporting that the secret had expired. `mssql_connection.resolve_connection`
is the one place that decides; this leaf calls it and stays a driver, a
connection and a dialect name (`40`).

`pyodbc` is an optional extra (`openstategraph[mssql]`), imported lazily at the
one seam below, so the base wheel gains nothing and the unconfigured path — the
only path this pass can prove, by the owner's decision of 2026-09-04 — needs no
driver at all. `msal` rides in the same extra and is imported the same way, at
`mssql_connection`'s own seam.
"""

from __future__ import annotations

import contextlib
import importlib
import os
from typing import Any, Iterator

from pydantic import Field

from openstategraph.install_hint import EXTRA_MARKERS
from openstategraph.mssql_connection import (
    DRIVER_EXTRA,
    ConnectionPlan,
    resolve_connection,
)
from openstategraph.prebuilt_sql import DEFAULT_MAX_ROWS
from openstategraph.prebuilt_warehouse import (
    WarehouseQueryArgs,
    _WarehouseExplorerBase,
    pins_from,
    statement_refusal,
    tables_named,
)

__all__ = [
    "DEFAULT_CONNECTION_ENV",
    "DRIVER_EXTRA",
    "DRIVER_MODULES",
    "MSSQL_TOOLS",
    "MssqlQueryArgs",
    "MssqlQueryTool",
    # Re-exported where they were first written (`34`) so a reader who followed
    # a citation here still lands on them; the definitions moved up a rung in
    # `40` and this module is not a second copy of any of them.
    "pins_from",
    "statement_refusal",
    "tables_named",
]

#: The variable a document names when its author names nothing else. A default
#: *name* is safe in a way a default value never is — it is a pointer, and the
#: thing it points at is refused when unset. Ours rather than a vendor's,
#: because ODBC has no conventional variable for a DSN — the Databricks leaf
#: inherits three vendor-documented names instead, and says why.
DEFAULT_CONNECTION_ENV = "OPENSTATEGRAPH_MSSQL_URL"

#: The optional modules this leaf can import: the ODBC driver, and the token
#: library the Azure AD shape needs (`73`). Both are lazy, which is what makes
#: the extra optional and keeps either of them out of the type gate's graph —
#: the property `test_the_type_gate_survives_a_newer_stub.py` asserts rather
#: than assumes.
#:
#: **Read from the one table rather than declared here** (`79`): "what makes
#: `[mssql]` present" is also what an install hint has to know to keep the
#: extras it is not repairing, and two spellings of that is how the hint and
#: the leaf drift apart.
DRIVER_MODULES = EXTRA_MARKERS["mssql"]

#: `DRIVER_EXTRA` is defined in `mssql_connection` and re-exported here, not
#: restated: the refusal that names an install line is written in both modules
#: and two spellings of one extra is the drift `CLAUDE.md` names.


@contextlib.contextmanager
def _connect(plan: ConnectionPlan) -> Iterator[Any]:
    """The one driver seam — lazy, uncommitted, always closed.

    Lazy so the base wheel carries no driver and the unconfigured path needs
    none. `autocommit=False` with an unconditional `rollback()` is the half of
    read-only the driver can actually give; the other half is the family's
    `statement_refusal`.

    `attrs_before` is empty on every shape but the Azure AD one, where it
    carries the access token we fetched ourselves (`73`) — so the driver is
    handed a token rather than asked to go and get one.
    """
    pyodbc = importlib.import_module("pyodbc")
    connection = pyodbc.connect(
        plan.connection_string, autocommit=False, attrs_before=plan.attrs_before
    )
    try:
        yield connection
    finally:
        with contextlib.suppress(Exception):
            connection.rollback()
        with contextlib.suppress(Exception):
            connection.close()


class MssqlQueryArgs(WarehouseQueryArgs):
    query: str = Field(description="A single read-only T-SQL SELECT statement.")


class MssqlQueryTool(_WarehouseExplorerBase):
    """One T-SQL SELECT, against tables an allowlist pinned."""

    name = "mssql_query"
    node_type = "tool.mssql-query"
    description = (
        "Run one read-only T-SQL SELECT against the configured MSSQL database. "
        "Only tables pinned in the workflow's allowlist may be named; the "
        "refusal lists them."
    )
    Args = MssqlQueryArgs

    _driver_extra = DRIVER_EXTRA
    _driver_label = "MSSQL"

    def __init__(
        self,
        *,
        connection: str = DEFAULT_CONNECTION_ENV,
        allowlist: str = "",
        pins: str = "",
        row_cap: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self.connection = connection
        super().__init__(allowlist=allowlist, pins=pins, row_cap=row_cap)

    def configure(self, data: dict[str, Any]) -> "MssqlQueryTool":
        connection = str(data.get("connection") or "").strip() or self.connection
        allowlist = str(data.get("allowlist") or "").strip() or self.allowlist
        pins = str(data.get("pins") or "").strip() or self.pins
        row_cap = self._row_cap_from(data, self.row_cap)
        return type(self)(
            connection=connection, allowlist=allowlist, pins=pins, row_cap=row_cap
        )

    def _connection(self) -> tuple[tuple[Any, ...], str | None]:
        """The URL variable if it is set, otherwise the named parts (`73`).

        `required=False` is the whole of the change on this rung: an unset URL
        variable is a fork here, not a refusal, because there are two more
        shapes to try. A *pasted* value is still refused first and unchanged —
        a committed credential is a committed credential whichever shape would
        have answered next.
        """
        url, refusal = self._env_value(
            key="connection",
            name=self.connection,
            default=DEFAULT_CONNECTION_ENV,
            holds="an ODBC connection string",
            required=False,
        )
        if refusal:
            return (), refusal
        plan, refusal = resolve_connection(
            os.environ, url=url, url_name=(self.connection or DEFAULT_CONNECTION_ENV).strip()
        )
        if plan is None:
            return (), refusal
        return (plan,), None

    def _open(self, target: tuple[Any, ...]) -> Any:
        return _connect(*target)


MSSQL_TOOLS = [MssqlQueryTool()]
