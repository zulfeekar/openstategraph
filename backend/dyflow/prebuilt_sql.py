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
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dyflow.abc.tool import BaseTool, NoArgs, ToolResult

WORKFLOWS_ROOT = Path(__file__).resolve().parent.parent.parent / "workflows"
DEFAULT_MAX_ROWS = 200


def _resolve_database(configured: str) -> Path | None:
    """The configured path, jailed to workflows/. None means refused."""
    if not configured.strip():
        return None
    candidate = (WORKFLOWS_ROOT / configured.strip()).resolve()
    try:
        candidate.relative_to(WORKFLOWS_ROOT)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _markdown(headers: list[str], rows: list[tuple]) -> str:
    head = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


class _SqlExplorerBase(BaseTool):
    """Shared per-node configuration: which database file, declared once."""

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


class SqlListTablesTool(_SqlExplorerBase):
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


class SqlGetSchemaTool(_SqlExplorerBase):
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


class SqlQueryTool(_SqlExplorerBase):
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
        cap = data.get("maxRows")
        try:
            row_cap = int(str(cap).strip()) if cap else self.row_cap
        except ValueError:
            row_cap = self.row_cap
        return type(self)(database=database, row_cap=row_cap)

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, SqlQueryArgs)
        db = self._db()
        if db is None:
            return self._refusal()
        cap = min(args.max_rows or self.row_cap, self.row_cap)
        try:
            with _connect(db) as conn:
                cursor = conn.execute(args.query)
                headers = [d[0] for d in cursor.description or []]
                rows = cursor.fetchmany(cap + 1)
        except sqlite3.Error as exc:
            return ToolResult.failure(f"SQL error: {exc}")
        truncated = len(rows) > cap
        content = _markdown(headers, [tuple(r) for r in rows[:cap]]) if headers else "(no result set)"
        if truncated:
            content += f"\n\n_(truncated at {cap} rows)_"
        return ToolResult(content=content)


SQL_EXPLORER_TOOLS = [SqlListTablesTool(), SqlGetSchemaTool(), SqlQueryTool()]
