"""Chinook database tools — concrete, workflow-scoped.

These live under the workflow, not in the shared catalogue, because they are this
workflow's *vocabulary* rather than the builder's grammar. Put them in the global
palette and every future workflow carries every past workflow's tools.

Real SQL, via the stdlib ``sqlite3`` — no dependency. The previous TypeScript
version regex-parsed the table out of the ``FROM`` clause and returned fabricated
rows, which cannot validate that generated SQL is *correct* — and correctness is
the entire risk in text-to-SQL.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field

from dyflow.abc.tool import BaseTool, NoArgs, ToolResult

#: Ships with the workflow, beside the tools that read it.
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "Chinook_Sqlite.sqlite"

#: An agent asking for `SELECT * FROM Track` should not get 3,503 rows of context.
DEFAULT_MAX_ROWS = 200


def connect_readonly(path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Opens the database **read-only at the driver level**.

    This is the actual safety boundary, and it is worth being precise about why.
    The earlier implementation checked the SQL string for ``DELETE``/``DROP`` and
    hoped — a check that is trivially bypassed (``/**/drop``, a subquery, mixed
    case, a compound statement) and that gives a false sense of protection.

    ``mode=ro`` is enforced by SQLite itself: a write attempt fails with
    ``OperationalError`` no matter how the statement is spelled. String checks
    elsewhere in this file exist to give *clear errors*, not to provide security.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Chinook database not found at {path}. "
            "Run scripts/fetch_chinook.sh to download it."
        )
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _rows_to_markdown(columns: list[str], rows: list[tuple], truncated: bool) -> str:
    """Markdown table — the shape an LLM reads back most reliably."""
    if not columns:
        return "_No rows._"
    head = f"| {' | '.join(columns)} |"
    rule = f"| {' | '.join('---' for _ in columns)} |"
    body = [f"| {' | '.join('' if c is None else str(c) for c in row)} |" for row in rows]
    out = [head, rule, *body]
    if truncated:
        out.append(f"\n_Truncated to {len(rows)} rows._")
    if not rows:
        out.append("\n_Query returned no rows._")
    return "\n".join(out)


class ListTablesTool(BaseTool):
    """Every table, with row counts — the orientation an agent needs first."""

    name = "chinook_list_tables"
    node_type = "tool.chinook-get-all-tables"
    description = (
        "List all tables in the Chinook music-store database with their row counts. "
        "Call this first to discover what data is available."
    )
    Args = NoArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        with connect_readonly() as conn:
            names = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            rows = []
            for name in names:
                # The name comes from sqlite_master, not from the caller, so
                # quoting it is safe — it cannot be attacker-controlled.
                count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                rows.append((name, count))

        return ToolResult(content=_rows_to_markdown(["Table", "Rows"], rows, False))


class GetTableSchemaArgs(BaseModel):
    model_config = {"extra": "forbid"}
    table: str = Field(description="Exact table name, e.g. 'Track' or 'InvoiceLine'.")


class GetTableSchemaTool(BaseTool):
    """Columns, types, primary key **and foreign keys** for one table.

    Foreign keys are included deliberately: without them a model has to guess how
    to join, and almost every interesting Chinook question needs a join
    (``InvoiceLine → Track → Genre``). Omitting them is the single biggest cause
    of wrong generated SQL.
    """

    name = "chinook_get_table_schema"
    node_type = "tool.chinook-get-schema"
    description = (
        "Get the columns, types, primary key and foreign keys of one Chinook table. "
        "Use the foreign keys to work out how to join tables."
    )
    Args = GetTableSchemaArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, GetTableSchemaArgs)
        with connect_readonly() as conn:
            known = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            # Validate against the real schema: PRAGMA cannot be parameterised,
            # so an existence check is the only safe way to accept a name.
            if args.table not in known:
                return ToolResult.failure(
                    f"Unknown table '{args.table}'. Available: {', '.join(sorted(known))}"
                )

            cols = [
                (row[1], row[2], "yes" if row[5] else "")
                for row in conn.execute(f'PRAGMA table_info("{args.table}")')
            ]
            fks = [
                (row[3], f"{row[2]}.{row[4]}")
                for row in conn.execute(f'PRAGMA foreign_key_list("{args.table}")')
            ]

        parts = [
            f"### {args.table}",
            _rows_to_markdown(["Column", "Type", "PK"], cols, False),
        ]
        if fks:
            parts += [
                "\n**Foreign keys**",
                _rows_to_markdown(["Column", "References"], fks, False),
            ]
        return ToolResult(content="\n".join(parts))


class ExecuteSqlArgs(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(description="A single read-only SQL SELECT statement.")
    # `None`, not a baked-in default: a Pydantic field default is fixed at
    # class-definition time, which cannot vary per canvas node. Leaving it
    # unset means "use this tool instance's own configured ceiling" —
    # resolved in `_execute`, where `self.row_cap` (an __init__ param, not a
    # class attribute) can actually differ per instance.
    max_rows: int | None = Field(
        default=None, ge=1, le=1000, description="Row cap. Omit to use the configured default."
    )


class ExecuteSqlTool(BaseTool):
    """Runs one read-only SELECT and returns a Markdown table."""

    name = "chinook_execute_sql"
    node_type = "tool.chinook-execute-sql"
    description = (
        "Execute a single read-only SQL SELECT against the Chinook database and "
        "return the rows. Use chinook_get_table_schema first to get column names "
        "and foreign keys."
    )
    Args = ExecuteSqlArgs

    def __init__(self, *, row_cap: int = DEFAULT_MAX_ROWS) -> None:
        # Found by a TS-schema-vs-Python-factory diff: the canvas node's own
        # "Max rows" field (`ChinookDatabaseNode.ts`) was fully inert on the
        # backend — every instance always used the bare class default,
        # regardless of what a developer configured. `row_cap` is this
        # instance's ceiling, set by whichever node in the document this
        # particular tool object was built for (see `node_runtime.py`'s
        # Chinook tool binding). A **hard** ceiling, not merely a fallback
        # default: if a developer set it on the canvas, an agent asking for
        # more should still be capped, not silently granted a bigger window
        # than the developer configured.
        self.row_cap = row_cap

    def configure(self, data):
        """The bound node's "Max rows" field becomes this instance's ceiling.

        A fresh instance, never a mutation — two nodes of this type with two
        different caps in one document must not clobber each other.
        """
        configured = data.get("maxRows")
        if isinstance(configured, (int, float)) and configured > 0:
            return type(self)(row_cap=int(configured))
        if isinstance(configured, str) and configured.strip().isdigit():
            return type(self)(row_cap=int(configured.strip()))
        return self

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, ExecuteSqlArgs)
        sql = args.query.strip().rstrip(";").strip()
        if not sql:
            return ToolResult.failure("Query is empty")
        # Clear errors, not security — the read-only connection is the boundary.
        if ";" in sql:
            return ToolResult.failure("Only one statement per query")
        if not sql.lower().startswith(("select", "with")):
            return ToolResult.failure("Only SELECT queries are allowed")

        effective_max = min(args.max_rows, self.row_cap) if args.max_rows is not None else self.row_cap

        with connect_readonly() as conn:
            try:
                cursor = conn.execute(sql)
            except sqlite3.Error as exc:
                # Handed back for the agent to read and retry, not raised.
                return ToolResult.failure(f"SQL error: {exc}")

            columns = [d[0] for d in cursor.description or []]
            rows = cursor.fetchmany(effective_max + 1)

        truncated = len(rows) > effective_max
        return ToolResult(
            content=_rows_to_markdown(columns, rows[:effective_max], truncated)
        )


#: The workflow's tool catalogue. Discovery (ticket 18) reads this.
TOOLS = [ListTablesTool(), GetTableSchemaTool(), ExecuteSqlTool()]

__all__ = [
    "TOOLS",
    "ExecuteSqlTool",
    "GetTableSchemaTool",
    "ListTablesTool",
    "connect_readonly",
]
