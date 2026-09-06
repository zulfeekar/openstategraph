"""Tests for the Chinook tools, against the **real** database.

Deliberately not against a fixture or a double. The whole point of these tools is
that generated SQL runs correctly over the actual schema, and a double would have
happily passed for the mock implementation these replaced.
"""

from __future__ import annotations

import sqlite3

import pytest

from openstategraph.abc.tool import ITool, ToolResult
from tools.chinook import (
    ExecuteSqlTool,
    GetTableSchemaTool,
    ListTablesTool,
    connect_readonly,
)


@pytest.fixture(scope="module")
def tables() -> ToolResult:
    return ListTablesTool().run()


class TestListTables:
    def test_lists_every_table_with_counts(self, tables: ToolResult) -> None:
        assert tables.ok, tables.error
        # Real counts from the shipped database, not invented ones.
        assert "Track" in tables.content
        assert "3503" in tables.content, "expected the real Track row count"

    def test_excludes_sqlite_internals(self, tables: ToolResult) -> None:
        assert "sqlite_" not in tables.content


class TestGetTableSchema:
    def test_returns_columns_and_types(self) -> None:
        result = GetTableSchemaTool().run(table="Track")
        assert result.ok, result.error
        assert "TrackId" in result.content
        assert "Composer" in result.content

    def test_includes_foreign_keys_so_joins_are_derivable(self) -> None:
        # Without these an LLM has to guess joins, and almost every interesting
        # Chinook question needs one. This is the highest-value part of the tool.
        result = GetTableSchemaTool().run(table="Track")
        assert result.ok, result.error
        assert "Foreign keys" in result.content
        assert "Genre.GenreId" in result.content
        assert "Album.AlbumId" in result.content

    def test_rejects_an_unknown_table_and_says_what_exists(self) -> None:
        result = GetTableSchemaTool().run(table="Nope")
        assert not result.ok
        assert "Unknown table" in (result.error or "")
        # The error is the agent's recovery path, so it must be actionable.
        assert "Track" in (result.error or "")

    def test_reports_missing_argument_as_data_not_an_exception(self) -> None:
        result = GetTableSchemaTool().run()
        assert not result.ok
        assert "Invalid arguments" in (result.error or "")


class TestExecuteSql:
    def test_runs_a_real_join_and_aggregate(self) -> None:
        """The question this workflow exists to answer."""
        result = ExecuteSqlTool().run(
            query="""
            SELECT g.Name AS Genre, ROUND(SUM(il.UnitPrice * il.Quantity), 2) AS Revenue
            FROM InvoiceLine il
            JOIN Track t ON t.TrackId = il.TrackId
            JOIN Genre g ON g.GenreId = t.GenreId
            GROUP BY g.Name
            ORDER BY Revenue DESC
            LIMIT 3
            """
        )
        assert result.ok, result.error
        # Verified independently against the shipped database.
        assert "Rock" in result.content
        assert "826.65" in result.content

    def test_returns_a_markdown_table(self) -> None:
        result = ExecuteSqlTool().run(query="SELECT Name FROM Genre ORDER BY Name LIMIT 2")
        assert result.ok, result.error
        assert result.content.startswith("| Name |")
        assert "| --- |" in result.content

    def test_caps_rows_and_says_so(self) -> None:
        result = ExecuteSqlTool().run(query="SELECT TrackId FROM Track", max_rows=5)
        assert result.ok, result.error
        assert "Truncated to 5 rows" in result.content

    def test_row_cap_is_the_default_when_the_caller_omits_max_rows(self) -> None:
        # Found by a TS-schema-vs-Python-factory diff: the canvas node's own
        # "Max rows" field was fully inert on the backend — every instance
        # always used the bare class default. `row_cap` is the per-instance
        # ceiling `node_runtime.py`'s tool binding sets from that field.
        result = ExecuteSqlTool(row_cap=3).run(query="SELECT TrackId FROM Track")
        assert result.ok, result.error
        assert "Truncated to 3 rows" in result.content

    def test_row_cap_is_a_hard_ceiling_even_when_the_caller_asks_for_more(self) -> None:
        # A developer who set this on the canvas means it — an agent asking
        # for more than the configured ceiling should still be capped, not
        # silently granted a bigger window than configured.
        result = ExecuteSqlTool(row_cap=3).run(query="SELECT TrackId FROM Track", max_rows=100)
        assert result.ok, result.error
        assert "Truncated to 3 rows" in result.content

    def test_a_caller_request_below_the_row_cap_is_still_honoured(self) -> None:
        result = ExecuteSqlTool(row_cap=100).run(query="SELECT TrackId FROM Track", max_rows=3)
        assert result.ok, result.error
        assert "Truncated to 3 rows" in result.content

    def test_reports_a_syntax_error_as_data_for_the_agent_to_retry(self) -> None:
        result = ExecuteSqlTool().run(query="SELECT nope FROM Track")
        assert not result.ok
        assert "SQL error" in (result.error or "")

    def test_handles_a_query_matching_nothing(self) -> None:
        result = ExecuteSqlTool().run(query="SELECT Name FROM Genre WHERE Name = 'nope'")
        assert result.ok, result.error
        assert "no rows" in result.content.lower()

    @pytest.mark.parametrize("query", ["", "   ", ";"])
    def test_rejects_an_empty_query(self, query: str) -> None:
        assert not ExecuteSqlTool().run(query=query).ok

    def test_rejects_multiple_statements(self) -> None:
        result = ExecuteSqlTool().run(query="SELECT 1; SELECT 2")
        assert not result.ok
        assert "one statement" in (result.error or "")

    @pytest.mark.parametrize(
        "query",
        ["DELETE FROM Track", "DROP TABLE Track", "UPDATE Track SET Name='x'"],
    )
    def test_rejects_non_select(self, query: str) -> None:
        assert not ExecuteSqlTool().run(query=query).ok


class TestReadOnlyBoundary:
    """The safety property, tested at the boundary that actually enforces it.

    The previous implementation relied on scanning the SQL string for dangerous
    keywords — trivially bypassed, and worse, it *looked* like protection. These
    tests assert the real guarantee: the connection itself refuses writes,
    however the statement is spelled.
    """

    def test_the_connection_refuses_writes(self) -> None:
        with connect_readonly() as conn:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("DELETE FROM Track")

    def test_it_refuses_writes_that_defeat_string_matching(self) -> None:
        # Casing and comments slip past a keyword scan; mode=ro does not care.
        with connect_readonly() as conn:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("/* comment */ dRoP TaBlE Genre")

    def test_the_database_is_unchanged_afterwards(self) -> None:
        with connect_readonly() as conn:
            count = conn.execute("SELECT COUNT(*) FROM Track").fetchone()[0]
        assert count == 3503


class TestLadder:
    """The ``ITool`` → ``BaseTool`` → concrete ladder holds."""

    @pytest.mark.parametrize(
        "tool", [ListTablesTool(), GetTableSchemaTool(), ExecuteSqlTool()]
    )
    def test_every_tool_satisfies_the_interface(self, tool: object) -> None:
        assert isinstance(tool, ITool)

    @pytest.mark.parametrize(
        "tool", [ListTablesTool(), GetTableSchemaTool(), ExecuteSqlTool()]
    )
    def test_every_tool_publishes_a_manifest_for_the_editor(self, tool) -> None:
        manifest = tool.manifest()
        assert manifest["name"] and manifest["description"]
        # Pydantic is the single source of truth; this schema is what the
        # generated TypeScript is built from.
        assert manifest["args_schema"]["type"] == "object"

    def test_tool_names_are_unique(self) -> None:
        names = [t.name for t in (ListTablesTool(), GetTableSchemaTool(), ExecuteSqlTool())]
        assert len(names) == len(set(names))
