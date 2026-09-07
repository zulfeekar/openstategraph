"""Curation contract: list/read/save, auto-claim, stale badges, provenance."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from openstategraph.api.knowledge_build import run_build
from openstategraph.knowledge_builders import (
    CLAIMED_HASH_COMMENT,
    GENERATED_MARKER,
    claimed_hash,
    marker_hash,
    marker_source,
)


class ScriptedModel:
    def invoke(self, prompt: Any) -> Any:
        class _Msg:
            content = "orders — scripted knowledge doc.\n\nDetails."

        return _Msg()


def _seed_db(root: Path, rel: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE orders (id INTEGER PRIMARY KEY, total REAL);
            INSERT INTO orders VALUES (1, 9.5);
            """
        )
    return path


def _document(database: str) -> dict[str, Any]:
    return {
        "nodes": [{"id": "n1", "type": "tool.sql-query", "data": {"database": database}}],
        "edges": [],
    }


def _client(tmp_path: Path) -> TestClient:
    from openstategraph.api.main import create_app

    return TestClient(create_app(graph_factory=lambda _m: None, workflows_root=tmp_path))


def _save(tmp_path: Path, slug: str, document: dict[str, Any]) -> Path:
    package = tmp_path / slug
    package.mkdir(parents=True, exist_ok=True)
    (package / "workflow.json").write_text(json.dumps({"version": 1, "document": document}))
    return package


def _built_package(tmp_path: Path) -> Path:
    _seed_db(tmp_path, "shop-flow/data/shop.sqlite")
    document = _document("shop-flow/data/shop.sqlite")
    package = _save(tmp_path, "shop-flow", document)
    run_build(package, document, ScriptedModel(), tmp_path, source="sql")
    return package


class TestMarkerHash:
    def test_the_generated_marker_stamps_the_source_hash(self, tmp_path: Path) -> None:
        package = _built_package(tmp_path)
        text = (package / "knowledge" / "orders.md").read_text()
        assert marker_source(text) == "sql"
        stamped = marker_hash(text)
        assert stamped is not None and len(stamped) == 12


class TestProvenanceFooter:
    def test_generated_docs_end_with_a_provenance_footer(self, tmp_path: Path) -> None:
        package = _built_package(tmp_path)
        text = (package / "knowledge" / "orders.md").read_text()
        assert "_Provenance: built from table orders of shop-flow/data/shop.sqlite" in text
        # the footer trails the body — the hint (first line) is untouched
        assert text.strip().endswith("._") or text.strip().endswith("-->")


class TestListEndpoint:
    def test_it_lists_name_hint_and_generated_flag(self, tmp_path: Path) -> None:
        _built_package(tmp_path)
        response = _client(tmp_path).get("/api/workflows/shop-flow/knowledge")
        assert response.status_code == 200
        [row] = response.json()
        assert row["name"] == "orders"
        assert row["hint"] == "orders — scripted knowledge doc."
        assert row["generated"] is True and row["source"] == "sql"
        assert row["stale"] is False

    def test_a_fresh_doc_goes_stale_when_the_source_schema_changes(
        self, tmp_path: Path
    ) -> None:
        _built_package(tmp_path)
        with sqlite3.connect(tmp_path / "shop-flow/data/shop.sqlite") as conn:
            conn.execute("ALTER TABLE orders ADD COLUMN currency TEXT")
        [row] = _client(tmp_path).get("/api/workflows/shop-flow/knowledge").json()
        assert row["stale"] is True

    def test_a_hand_authored_doc_with_no_recorded_hash_is_never_stale(
        self, tmp_path: Path
    ) -> None:
        package = _built_package(tmp_path)
        (package / "knowledge" / "orders.md").write_text("# orders\nhand-written\n")
        [row] = _client(tmp_path).get("/api/workflows/shop-flow/knowledge").json()
        assert row["generated"] is False and row["stale"] is False

    def test_an_unknown_workflow_is_404(self, tmp_path: Path) -> None:
        assert _client(tmp_path).get("/api/workflows/ghost/knowledge").status_code == 404


class TestReadEndpoint:
    def test_it_returns_the_raw_body(self, tmp_path: Path) -> None:
        _built_package(tmp_path)
        response = _client(tmp_path).get("/api/workflows/shop-flow/knowledge/orders")
        assert response.status_code == 200
        payload = response.json()
        assert payload["body"].startswith(GENERATED_MARKER)
        assert payload["generated"] is True and payload["source"] == "sql"

    def test_a_missing_topic_is_404_and_a_traversal_topic_is_422(self, tmp_path: Path) -> None:
        _built_package(tmp_path)
        client = _client(tmp_path)
        assert client.get("/api/workflows/shop-flow/knowledge/ghost").status_code == 404
        # a slash-carrying topic never even routes (starlette 404s it) …
        assert client.get("/api/workflows/shop-flow/knowledge/..%2Fevil").status_code == 404
        # … and the module-level jail refuses it independently of routing
        import pytest

        from openstategraph.api.knowledge_curation import UnknownTopicPathError, read_topic

        with pytest.raises(UnknownTopicPathError):
            read_topic(tmp_path / "shop-flow", "../evil")


class TestAutoClaim:
    def test_saving_strips_the_marker_and_records_the_claim_hash(self, tmp_path: Path) -> None:
        package = _built_package(tmp_path)
        original = (package / "knowledge" / "orders.md").read_text()
        stamped = marker_hash(original)
        response = _client(tmp_path).put(
            "/api/workflows/shop-flow/knowledge/orders",
            json={"body": original.replace("scripted", "curated")},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["generated"] is False and payload["source"] == ""
        text = (package / "knowledge" / "orders.md").read_text()
        assert GENERATED_MARKER not in text
        assert "curated" in text
        assert claimed_hash(text) == stamped  # the claim-time hash is recorded

    def test_a_claimed_doc_is_skipped_by_the_next_build(self, tmp_path: Path) -> None:
        package = _built_package(tmp_path)
        client = _client(tmp_path)
        original = (package / "knowledge" / "orders.md").read_text()
        client.put(
            "/api/workflows/shop-flow/knowledge/orders", json={"body": "orders — my words.\n"}
        )
        report = run_build(
            package, _document("shop-flow/data/shop.sqlite"), ScriptedModel(), tmp_path, source="sql"
        )
        assert report["skipped"] == ["orders"]
        assert "my words" in (package / "knowledge" / "orders.md").read_text()
        del original

    def test_a_claimed_doc_goes_stale_when_the_source_changes(self, tmp_path: Path) -> None:
        _built_package(tmp_path)
        client = _client(tmp_path)
        client.put(
            "/api/workflows/shop-flow/knowledge/orders", json={"body": "orders — my words.\n"}
        )
        [row] = client.get("/api/workflows/shop-flow/knowledge").json()
        assert row["stale"] is False
        with sqlite3.connect(tmp_path / "shop-flow/data/shop.sqlite") as conn:
            conn.execute("ALTER TABLE orders ADD COLUMN currency TEXT")
        [row] = client.get("/api/workflows/shop-flow/knowledge").json()
        assert row["generated"] is False and row["stale"] is True

    def test_saving_twice_keeps_exactly_one_claim_comment(self, tmp_path: Path) -> None:
        package = _built_package(tmp_path)
        client = _client(tmp_path)
        client.put("/api/workflows/shop-flow/knowledge/orders", json={"body": "orders — v1.\n"})
        first = (package / "knowledge" / "orders.md").read_text()
        client.put("/api/workflows/shop-flow/knowledge/orders", json={"body": first + "\nmore"})
        text = (package / "knowledge" / "orders.md").read_text()
        assert text.count(CLAIMED_HASH_COMMENT) == 1

    def test_a_traversal_topic_cannot_be_saved(self, tmp_path: Path) -> None:
        _built_package(tmp_path)
        response = _client(tmp_path).put(
            "/api/workflows/shop-flow/knowledge/..%2Fevil", json={"body": "x"}
        )
        assert response.status_code == 404  # starlette refuses the path shape
        import pytest

        from openstategraph.api.knowledge_curation import UnknownTopicPathError, save_topic

        with pytest.raises(UnknownTopicPathError):
            save_topic(
                tmp_path / "shop-flow",
                "../evil",
                "x",
                _document("shop-flow/data/shop.sqlite"),
                tmp_path,
            )
        assert not (tmp_path / "evil.md").exists()
