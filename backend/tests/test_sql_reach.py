"""What the SQL tools can actually reach — the schema, read from the database.

The defect this covers: `tool.chinook-get-schema` shipped a hardcoded table
listbox that the runtime never read (the tool takes `table` as a *model*
argument and declares no `configure()`), so the card told a reader "this node
fetches Artist's schema" while the agent picked whatever table it liked. The
control is gone; this is the replacement — one read that answers, from the
real file, which tables the wired tools can reach and what is in them.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from openstategraph.sql_reach import TABLE_CAP, reachable_schema


def _seed_db(root: Path, rel: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id),
                total REAL
            );
            INSERT INTO customers VALUES (1, 'Ada');
            INSERT INTO orders VALUES (10, 1, 9.5);
            """
        )
    return path


def _document(database: str) -> dict[str, Any]:
    return {
        "nodes": [{"id": "n1", "type": "tool.sql-get-schema", "data": {"database": database}}],
        "edges": [],
    }


def _save(root: Path, slug: str, document: dict[str, Any]) -> None:
    package = root / slug
    package.mkdir(parents=True, exist_ok=True)
    (package / "workflow.json").write_text(json.dumps({"version": 1, "document": document}))


class TestReachableSchema:
    def test_every_table_of_a_wired_source_is_reported_with_its_columns(
        self, tmp_path: Path
    ) -> None:
        _seed_db(tmp_path, "shop-flow/data/shop.sqlite")
        sources = reachable_schema(_document("shop-flow/data/shop.sqlite"), tmp_path)

        assert len(sources) == 1
        source = sources[0]
        assert source.engine == "sqlite"
        assert source.database == "shop-flow/data/shop.sqlite"
        assert [t.name for t in source.tables] == ["customers", "orders"]
        # The JOIN rules are the point: a schema without foreign keys is the
        # single biggest cause of wrong generated SQL.
        orders = next(t for t in source.tables if t.name == "orders")
        assert "customer_id" in orders.detail
        assert "customers.id" in orders.detail

    def test_a_chinook_node_implies_the_bundled_database_without_configuration(
        self, tmp_path: Path
    ) -> None:
        _seed_db(tmp_path, "chinook-assistant/data/Chinook_Sqlite.sqlite")
        document = {
            "nodes": [{"id": "a", "type": "tool.chinook-get-schema", "data": {}}],
            "edges": [],
        }
        sources = reachable_schema(document, tmp_path)
        assert [t.name for t in sources[0].tables] == ["customers", "orders"]

    def test_a_missing_or_unreadable_database_is_silence_not_a_crash(
        self, tmp_path: Path
    ) -> None:
        # Nothing on disk at all.
        assert reachable_schema(_document("shop-flow/data/shop.sqlite"), tmp_path) == []
        # Present but not a database.
        broken = tmp_path / "shop-flow" / "data" / "shop.sqlite"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text("this is not a database")
        sources = reachable_schema(_document("shop-flow/data/shop.sqlite"), tmp_path)
        assert len(sources) == 1
        assert sources[0].tables == []
        assert sources[0].warning

    def test_a_document_with_no_sql_source_reaches_nothing(self, tmp_path: Path) -> None:
        document = {"nodes": [{"id": "a", "type": "agent.llm", "data": {}}], "edges": []}
        assert reachable_schema(document, tmp_path) == []

    def test_a_wide_database_is_capped_and_says_so(self, tmp_path: Path) -> None:
        path = tmp_path / "wide-flow" / "data" / "wide.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            for i in range(TABLE_CAP + 3):
                conn.execute(f"CREATE TABLE t{i:03d} (id INTEGER PRIMARY KEY)")
        sources = reachable_schema(_document("wide-flow/data/wide.sqlite"), tmp_path)
        assert len(sources[0].tables) == TABLE_CAP
        assert str(TABLE_CAP + 3) in sources[0].warning


class TestEndpoint:
    def _client(self, tmp_path: Path) -> TestClient:
        from openstategraph.api.main import create_app

        return TestClient(create_app(graph_factory=lambda _m: None, workflows_root=tmp_path))

    def test_the_endpoint_serves_the_tables_and_their_schemas(self, tmp_path: Path) -> None:
        _seed_db(tmp_path, "shop-flow/data/shop.sqlite")
        _save(tmp_path, "shop-flow", _document("shop-flow/data/shop.sqlite"))

        response = self._client(tmp_path).get("/api/workflows/shop-flow/sql-schema")
        assert response.status_code == 200, response.text
        body = response.json()
        assert [t["name"] for t in body["sources"][0]["tables"]] == ["customers", "orders"]

    def test_a_workflow_with_no_database_serves_an_empty_list(self, tmp_path: Path) -> None:
        _save(tmp_path, "dry-flow", {"nodes": [], "edges": []})
        response = self._client(tmp_path).get("/api/workflows/dry-flow/sql-schema")
        assert response.status_code == 200
        assert response.json() == {"sources": []}

    def test_an_unknown_workflow_is_404(self, tmp_path: Path) -> None:
        assert self._client(tmp_path).get("/api/workflows/ghost/sql-schema").status_code == 404
