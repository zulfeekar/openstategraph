"""The prebuilt SQL Explorer (ticket 66) — jailed, read-only, FK-aware."""

from __future__ import annotations

from openstategraph.prebuilt_sql import SqlGetSchemaTool, SqlListTablesTool, SqlQueryTool

CHINOOK = "chinook-assistant/data/Chinook_Sqlite.sqlite"


class TestJail:
    def test_a_path_outside_workflows_is_refused(self) -> None:
        tool = SqlQueryTool(database="../backend/pyproject.toml")
        result = tool.run(query="SELECT 1")
        assert result.error is not None and "database" in result.error

    def test_an_unset_database_refuses_with_instructions(self) -> None:
        result = SqlListTablesTool().run()
        assert result.error is not None and "database" in result.error


class TestAgainstARealDatabase:
    def test_lists_tables_with_row_counts(self) -> None:
        result = SqlListTablesTool(database=CHINOOK).run()
        assert result.error is None
        assert "Track" in result.content and "Rows" in result.content

    def test_schema_includes_the_join_rules(self) -> None:
        result = SqlGetSchemaTool(database=CHINOOK).run(table="Track")
        assert result.error is None
        assert "JOIN rules" in result.content and "Album.AlbumId" in result.content

    def test_the_driver_refuses_writes_regardless_of_spelling(self) -> None:
        result = SqlQueryTool(database=CHINOOK).run(query="/**/dRoP TABLE Artist")
        assert result.error is not None

    def test_a_join_query_works_and_truncates_honestly(self) -> None:
        tool = SqlQueryTool(database=CHINOOK, row_cap=3)
        result = tool.run(query=(
            "SELECT ar.Name, COUNT(al.AlbumId) n FROM Artist ar "
            "JOIN Album al ON ar.ArtistId = al.ArtistId GROUP BY ar.Name ORDER BY n DESC"))
        assert result.error is None
        assert "truncated at 3 rows" in result.content

    def test_configure_carries_per_node_database_and_cap(self) -> None:
        configured = SqlQueryTool().configure({"database": CHINOOK, "maxRows": "5"})
        assert configured.database == CHINOOK and configured.row_cap == 5
