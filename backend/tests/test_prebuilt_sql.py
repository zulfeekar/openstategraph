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
        """Refused, **and the table is still there**.

        `error is not None` alone is satisfied by a syntax error from the
        comment prefix just as well as by the write refusal this test is named
        for — so it could pass while the drop succeeded and something else
        complained (reviews-2026-08-14 ticket 09).
        """
        result = SqlQueryTool(database=CHINOOK).run(query="/**/dRoP TABLE Artist")
        assert result.error is not None

        survived = SqlQueryTool(database=CHINOOK).run(query="SELECT COUNT(*) FROM Artist")
        assert survived.error is None, survived.error
        assert survived.content.strip()

    def test_every_spelling_of_a_write_is_refused_and_changes_nothing(self) -> None:
        before = SqlQueryTool(database=CHINOOK).run(query="SELECT COUNT(*) FROM Artist").content

        for query in (
            "DELETE FROM Artist",
            "UPDATE Artist SET Name = 'x'",
            "INSERT INTO Artist (Name) VALUES ('x')",
            "SELECT 1; DROP TABLE Artist",
            "  drop   table   Artist  ",
        ):
            assert SqlQueryTool(database=CHINOOK).run(query=query).error is not None, query

        after = SqlQueryTool(database=CHINOOK).run(query="SELECT COUNT(*) FROM Artist").content
        assert after == before

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
