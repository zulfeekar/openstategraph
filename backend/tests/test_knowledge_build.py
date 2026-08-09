"""'Build second brain' — the one-button knowledge indexer, pluggable per source."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from openstategraph.api.knowledge_build import run_build
from openstategraph.knowledge_builders import (
    BUILDERS,
    GENERATED_MARKER,
    BaseKnowledgeBuilder,
    IKnowledgeBuilder,
    SqlKnowledgeBuilder,
    databases_in_document,
    table_brief,
)


class ScriptedModel:
    """Stands in for a chat model: records prompts, answers deterministically."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def invoke(self, prompt: Any) -> Any:
        self.prompts.append(str(prompt))

        class _Msg:
            content = "Business meaning: scripted knowledge doc."

        return _Msg()


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
            INSERT INTO customers VALUES (1, 'Ada'), (2, 'Lin');
            INSERT INTO orders VALUES (10, 1, 9.5);
            """
        )
    return path


def _document(database: str) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "n1", "type": "tool.sql-query", "data": {"database": database}},
            {"id": "n2", "type": "agent.llm", "data": {}},
        ],
        "edges": [],
    }


class TestBuilderLadder:
    def test_the_sql_builder_satisfies_the_protocol(self) -> None:
        builder = SqlKnowledgeBuilder()
        assert isinstance(builder, IKnowledgeBuilder)
        assert isinstance(builder, BaseKnowledgeBuilder)
        assert builder.source_kind == "sql"

    def test_the_registry_is_the_extension_point(self) -> None:
        assert any(isinstance(b, SqlKnowledgeBuilder) for b in BUILDERS)


class TestDatabaseDiscovery:
    def test_sql_tool_database_fields_are_found_and_deduped(self, tmp_path: Path) -> None:
        _seed_db(tmp_path, "flow/data/shop.sqlite")
        document = {
            "nodes": [
                {"id": "a", "type": "tool.sql-query", "data": {"database": "flow/data/shop.sqlite"}},
                {"id": "b", "type": "tool.sql-list-tables", "data": {"database": "flow/data/shop.sqlite"}},
            ],
            "edges": [],
        }
        found = databases_in_document(document, tmp_path)
        assert found == [tmp_path / "flow/data/shop.sqlite"]

    def test_chinook_nodes_imply_the_bundled_database(self, tmp_path: Path) -> None:
        _seed_db(tmp_path, "chinook-nl-to-sql/data/Chinook_Sqlite.sqlite")
        document = {
            "nodes": [{"id": "a", "type": "tool.chinook-execute-sql", "data": {}}],
            "edges": [],
        }
        found = databases_in_document(document, tmp_path)
        assert found == [tmp_path / "chinook-nl-to-sql/data/Chinook_Sqlite.sqlite"]

    def test_missing_files_and_escaping_paths_are_ignored(self, tmp_path: Path) -> None:
        document = {
            "nodes": [
                {"id": "a", "type": "tool.sql-query", "data": {"database": "nope.sqlite"}},
                {"id": "b", "type": "tool.sql-query", "data": {"database": "../etc/passwd"}},
            ],
            "edges": [],
        }
        assert databases_in_document(document, tmp_path) == []


class TestTableBrief:
    def test_the_brief_carries_schema_fks_both_directions_and_a_sample(self, tmp_path: Path) -> None:
        db = _seed_db(tmp_path, "flow/data/shop.sqlite")
        brief = table_brief(db, "orders")
        assert "customer_id" in brief and "customers" in brief
        assert "9.5" in brief  # data sample
        inbound = table_brief(db, "customers")
        assert "orders" in inbound  # referenced-by direction


class TestLivingExample:
    def test_the_chinook_workflow_discovers_its_bundled_tables(self) -> None:
        # The real repo tree, read-only: discovery over the seeded chinook
        # document finds the bundled database's tables, JOIN rules included.
        from openstategraph.api.workflow_store import WorkflowStore

        store = WorkflowStore()
        document = store.load("chinook-nl-to-sql")
        topics = SqlKnowledgeBuilder().discover(
            store.directory_for("chinook-nl-to-sql"), document, store.root
        )
        names = {t.name for t in topics}
        assert {"Album", "Track", "InvoiceLine"} <= names
        album = next(t for t in topics if t.name == "Album")
        assert "Artist" in album.brief and "references" in album.brief


class TestRunBuild:
    def test_it_writes_one_generated_doc_per_table(self, tmp_path: Path) -> None:
        _seed_db(tmp_path, "flow/data/shop.sqlite")
        package = tmp_path / "flow"
        report = run_build(package, _document("flow/data/shop.sqlite"), ScriptedModel(), tmp_path)
        assert sorted(report["written"]) == ["customers", "orders"]
        assert report["skipped"] == []
        doc = (package / "knowledge" / "orders.md").read_text()
        assert doc.startswith(GENERATED_MARKER)
        assert "scripted knowledge doc" in doc

    def test_the_report_groups_results_per_builder(self, tmp_path: Path) -> None:
        _seed_db(tmp_path, "flow/data/shop.sqlite")
        report = run_build(
            tmp_path / "flow", _document("flow/data/shop.sqlite"), ScriptedModel(), tmp_path
        )
        assert sorted(report["sources"]["sql"]["written"]) == ["customers", "orders"]

    def test_the_prompt_gives_the_model_schema_and_sample(self, tmp_path: Path) -> None:
        _seed_db(tmp_path, "flow/data/shop.sqlite")
        model = ScriptedModel()
        run_build(tmp_path / "flow", _document("flow/data/shop.sqlite"), model, tmp_path)
        joined = "\n".join(model.prompts)
        assert "customer_id" in joined and "JOIN" in joined

    def test_a_generated_doc_is_regenerated_but_a_hand_authored_one_is_kept(
        self, tmp_path: Path
    ) -> None:
        _seed_db(tmp_path, "flow/data/shop.sqlite")
        package = tmp_path / "flow"
        knowledge = package / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "orders.md").write_text(f"{GENERATED_MARKER}\nstale generated text\n")
        (knowledge / "customers.md").write_text("# customers\nHand-written wisdom.\n")

        report = run_build(package, _document("flow/data/shop.sqlite"), ScriptedModel(), tmp_path)
        assert report["written"] == ["orders"]
        assert report["skipped"] == ["customers"]
        assert "scripted knowledge doc" in (knowledge / "orders.md").read_text()
        assert "Hand-written wisdom" in (knowledge / "customers.md").read_text()

    def test_no_database_in_the_document_reports_nothing(self, tmp_path: Path) -> None:
        report = run_build(tmp_path / "flow", {"nodes": [], "edges": []}, ScriptedModel(), tmp_path)
        assert report["written"] == [] and report["skipped"] == []

    def test_an_explicit_source_runs_only_that_builder(self, tmp_path: Path) -> None:
        _seed_db(tmp_path, "flow/data/shop.sqlite")
        report = run_build(
            tmp_path / "flow",
            _document("flow/data/shop.sqlite"),
            ScriptedModel(),
            tmp_path,
            source="sql",
        )
        assert sorted(report["written"]) == ["customers", "orders"]


class TestEndpoint:
    def _client(self, tmp_path: Path, monkeypatch: Any) -> TestClient:
        from openstategraph.api import knowledge_build
        from openstategraph.api.main import create_app

        monkeypatch.setattr(
            knowledge_build, "resolve_build_model", lambda *_a, **_k: ScriptedModel()
        )
        return TestClient(create_app(graph_factory=lambda _m: None, workflows_root=tmp_path))

    def _save(self, tmp_path: Path, slug: str, document: dict[str, Any]) -> None:
        package = tmp_path / slug
        package.mkdir(parents=True, exist_ok=True)
        (package / "workflow.json").write_text(json.dumps({"version": 1, "document": document}))

    def test_build_writes_docs_and_reports_them(self, tmp_path: Path, monkeypatch: Any) -> None:
        _seed_db(tmp_path, "shop-flow/data/shop.sqlite")
        self._save(tmp_path, "shop-flow", _document("shop-flow/data/shop.sqlite"))
        client = self._client(tmp_path, monkeypatch)

        response = client.post("/api/workflows/shop-flow/knowledge/build", json={})
        assert response.status_code == 200, response.text
        body = response.json()
        assert sorted(body["written"]) == ["customers", "orders"]
        assert "sql" in body["sources"]
        assert (tmp_path / "shop-flow" / "knowledge" / "customers.md").is_file()

    def test_an_unknown_workflow_is_404(self, tmp_path: Path, monkeypatch: Any) -> None:
        client = self._client(tmp_path, monkeypatch)
        response = client.post("/api/workflows/ghost/knowledge/build", json={})
        assert response.status_code == 404

    def test_a_workflow_with_no_source_material_is_422(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        self._save(tmp_path, "dry-flow", {"nodes": [], "edges": []})
        client = self._client(tmp_path, monkeypatch)
        response = client.post("/api/workflows/dry-flow/knowledge/build", json={})
        assert response.status_code == 422

    def test_an_unknown_source_is_422(self, tmp_path: Path, monkeypatch: Any) -> None:
        _seed_db(tmp_path, "shop-flow/data/shop.sqlite")
        self._save(tmp_path, "shop-flow", _document("shop-flow/data/shop.sqlite"))
        client = self._client(tmp_path, monkeypatch)
        response = client.post(
            "/api/workflows/shop-flow/knowledge/build", json={"source": "carrier-pigeon"}
        )
        assert response.status_code == 422
