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

`pyodbc` is an optional extra (`openstategraph[mssql]`), imported lazily at the
one seam below, so the base wheel gains nothing and the unconfigured path — the
only path this pass can prove, by the owner's decision of 2026-09-04 — needs no
driver at all.
"""

from __future__ import annotations

import contextlib
import importlib
from typing import Any, Iterator

from pydantic import Field

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

#: The extra that carries the driver. Named in the refusal rather than in a
#: doc page, because the refusal is where somebody is standing when they need it.
DRIVER_EXTRA = "openstategraph[mssql]"


@contextlib.contextmanager
def _connect(dsn: str) -> Iterator[Any]:
    """The one driver seam — lazy, uncommitted, always closed.

    Lazy so the base wheel carries no driver and the unconfigured path needs
    none. `autocommit=False` with an unconditional `rollback()` is the half of
    read-only the driver can actually give; the other half is the family's
    `statement_refusal`.
    """
    pyodbc = importlib.import_module("pyodbc")
    connection = pyodbc.connect(dsn, autocommit=False)
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
        dsn, refusal = self._env_value(
            key="connection",
            name=self.connection,
            default=DEFAULT_CONNECTION_ENV,
            holds="an ODBC connection string",
        )
        return (dsn,), refusal

    def _open(self, target: tuple[Any, ...]) -> Any:
        return _connect(*target)


MSSQL_TOOLS = [MssqlQueryTool()]
