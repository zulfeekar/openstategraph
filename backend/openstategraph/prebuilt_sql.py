"""Prebuilt SQL Explorer tools — ticket 66's Schema Explorer, generalized.

The Chinook tools proved the shape (list → schema+FKs → read-only query);
this family ships it for **any** SQLite database a workflow carries, so the
user's 6-tables-with-JOIN-rules scenario is configuration, not code: drop
`data/business.sqlite` in a workflow package, add the three nodes, point
them at the file.

Safety is the driver's, not string matching (the chinook lesson): the
connection is opened ``mode=ro`` so SQLite itself refuses writes however a
statement is spelled, and the database path must resolve inside
``workflows/`` — a canvas field can never reach an arbitrary host file.

Two files' worth of that claim, not one. ``mode=ro`` is about the file it
opens; the *model-authored* string reaching :meth:`SqlQueryTool._execute`
could still reach a second one through ``ATTACH`` or ``VACUUM INTO``, both of
which the URI form makes writable. The connection therefore comes from
``openstategraph.readonly_sqlite``, which denies that family at the same
driver level and for the same reason — still nothing here parses SQL
(`the-boundary-nobody-checked/06`).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult
from openstategraph.readonly_sqlite import readonly_closing, sql_error_text
from openstategraph.workflows_root import workflows_root

DEFAULT_MAX_ROWS = 200


def _resolve_database(configured: str) -> Path | None:
    """The configured path, jailed to workflows/. None means refused.

    The root is resolved per call (`openstategraph.workflows_root`), never
    frozen at import: a module constant computed from `__file__` points inside
    site-packages once this is an installed wheel, and every configured
    database path would be refused for a reason nobody could see.
    """
    if not configured.strip():
        return None
    root = workflows_root()
    candidate = (root / configured.strip()).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


#: The one seam. Read-only, one file, and a `with` block that closes — the
#: argument for all three is `openstategraph.readonly_sqlite`.
_connect = readonly_closing


def _markdown(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


class _SqlExplorerBase(BaseTool):
    """What every SQL dialect shares, and nothing a single dialect owns.

    The rung `osg-agent-experience/39` split out. Until then this class also
    held `database`, `_db()` and `_refusal()` — three members shaped for a
    file, inherited by `MssqlQueryTool`, which reads a warehouse over ODBC and
    has no file at all; `_refusal()`'s sentence told its reader to set a
    `.sqlite` path. Nothing called it there, which is the reason it survived a
    ticket: a latent wrong message waits for the fifth member of the family to
    reach for it because it is there.

    What is left is what a dialect cannot change: reading is not a side
    effect, the row cap is parsed from the same card field, and rows come back
    as the same truncation-aware markdown table. File-shaped configuration is
    :class:`_SqliteExplorerBase`, one rung down; a warehouse leaf sits beside
    that rung rather than under it, and a third dialect adds a driver and a
    dialect rather than a base.
    """

    #: The whole family reads — `launch-readiness` 121. `SqlQueryTool` too:
    #: the driver enforces read-only, so a repeat is a repeat of a SELECT.
    side_effecting = False

    @staticmethod
    def _row_cap_from(data: dict[str, Any], current: int) -> int:
        """The card's `maxRows`, or the cap already in force.

        Blank and unparseable are the same answer — the field is optional and
        a node that mistypes it gets the default rather than a refusal.
        """
        raw = data.get("maxRows")
        try:
            return int(str(raw).strip()) if raw else current
        except ValueError:
            return current

    @staticmethod
    def _capped_table(headers: list[str], rows: list[tuple[Any, ...]], cap: int) -> str:
        """`cap` rows as markdown, saying so when there were more.

        `rows` carries `cap + 1` when the query overran, because that is how
        every leaf asks the driver whether it did.
        """
        content = _markdown(headers, [tuple(r) for r in rows[:cap]]) if headers else "(no result set)"
        if len(rows) > cap:
            content += f"\n\n_(truncated at {cap} rows)_"
        return content


class _SqliteExplorerBase(_SqlExplorerBase):
    """Shared per-node configuration for the file dialect: which database file.

    Everything here reads a `.sqlite` path jailed to the workflows root, so
    everything here is wrong on a node that has no file — which is why it is
    a rung and not the family base (`osg-agent-experience/39`).
    """

    def __init__(self, *, database: str = "") -> None:
        self.database = database

    def configure(self, data: dict[str, Any]) -> "BaseTool":
        configured = str(data.get("database") or "").strip()
        return type(self)(database=configured) if configured else self

    def _db(self) -> Path | None:
        return _resolve_database(self.database)

    def _refusal(self) -> ToolResult:
        return ToolResult.failure(
            f"No readable database at '{self.database or '(unset)'}'. Set the node's "
            "'database' field to a .sqlite path inside workflows/, e.g. "
            "'my-flow/data/business.sqlite'."
        )


class SqlListTablesTool(_SqliteExplorerBase):
    """Orientation first: every table with its row count."""

    name = "sql_list_tables"
    node_type = "tool.sql-list-tables"
    description = (
        "List all tables in the configured SQL database with row counts. "
        "Call this first to discover what data exists."
    )
    Args = NoArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        db = self._db()
        if db is None:
            return self._refusal()
        with _connect(db) as conn:
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            rows = [(n, conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]) for n in names]
        return ToolResult(content=_markdown(["Table", "Rows"], rows))


class SqlSchemaArgs(BaseModel):
    model_config = {"extra": "forbid"}
    table: str = Field(description="Exact table name.")


class SqlGetSchemaTool(_SqliteExplorerBase):
    """Columns, types, PK and — critically — foreign keys, the JOIN rules."""

    name = "sql_get_table_schema"
    node_type = "tool.sql-get-schema"
    description = (
        "Get one table's columns, types, primary key and foreign keys. "
        "The foreign keys are the JOIN rules — use them to connect tables."
    )
    Args = SqlSchemaArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, SqlSchemaArgs)
        db = self._db()
        if db is None:
            return self._refusal()
        with _connect(db) as conn:
            known = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if args.table not in known:
                return ToolResult.failure(
                    f"Unknown table '{args.table}'. Available: {', '.join(sorted(known))}")
            cols = [(r[1], r[2], "yes" if r[5] else "")
                    for r in conn.execute(f'PRAGMA table_info("{args.table}")')]
            fks = [(r[3], f"{r[2]}.{r[4]}")
                   for r in conn.execute(f'PRAGMA foreign_key_list("{args.table}")')]
        parts = [f"### {args.table}", _markdown(["Column", "Type", "PK"], cols)]
        if fks:
            parts += ["\n**Foreign keys (JOIN rules)**", _markdown(["Column", "References"], fks)]
        return ToolResult(content="\n".join(parts))


class SqlQueryArgs(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(description="A single read-only SELECT statement.")
    max_rows: int | None = Field(default=None, ge=1, le=1000)


class SqlQueryTool(_SqliteExplorerBase):
    """Read-only execution; the driver enforces read-only, not a regex."""

    name = "sql_query"
    node_type = "tool.sql-query"
    description = "Run one read-only SELECT against the configured database."
    Args = SqlQueryArgs

    def __init__(self, *, database: str = "", row_cap: int = DEFAULT_MAX_ROWS) -> None:
        super().__init__(database=database)
        self.row_cap = row_cap

    def configure(self, data: dict[str, Any]) -> "BaseTool":
        database = str(data.get("database") or "").strip() or self.database
        return type(self)(database=database, row_cap=self._row_cap_from(data, self.row_cap))

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, SqlQueryArgs)
        db = self._db()
        if db is None:
            return self._refusal()
        cap = min(args.max_rows or self.row_cap, self.row_cap)
        with _connect(db) as conn:
            try:
                cursor = conn.execute(args.query)
                headers = [d[0] for d in cursor.description or []]
                rows = cursor.fetchmany(cap + 1)
            except sqlite3.Error as exc:
                # `sql_error_text`, not `str(exc)`: a refused second file
                # reports as `not authorized`, which names nothing to do next.
                return ToolResult.failure(sql_error_text(
                    conn, exc,
                    instead="write a single SELECT against the tables "
                            "sql_list_tables reports."))
        return ToolResult(content=self._capped_table(headers, list(rows), cap))


SQL_EXPLORER_TOOLS = [SqlListTablesTool(), SqlGetSchemaTool(), SqlQueryTool()]
