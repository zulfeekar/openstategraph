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
    AbstractWorkflowPointerBuilder,
    BaseKnowledgeBuilder,
    Discovery,
    IKnowledgeBuilder,
    KnowledgeTopic,
    ProjectKnowledgeBuilder,
    RootKnowledgeBuilder,
    SqlKnowledgeBuilder,
    marker_source,
    sql_sources_in_document,
)
from openstategraph.knowledge_engines import SqliteEngineAdapter


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


def _sqlite_files(document: dict, workflows_root: Path) -> list[Path]:
    """What the removed `databases_in_document` veneer used to return.

    Inlined here because production never called it: the real path is
    `sql_sources_in_document`, and these tests are about *its* jailing and
    de-duplication, so they should go through it rather than through a
    wrapper kept alive only by this file.
    """
    return [
        workflows_root.resolve() / ref
        for ref, engine in sql_sources_in_document(document, workflows_root)
        if engine == "sqlite"
    ]


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
        found = _sqlite_files(document, tmp_path)
        assert found == [tmp_path / "flow/data/shop.sqlite"]

    def test_chinook_nodes_imply_the_bundled_database(self, tmp_path: Path) -> None:
        _seed_db(tmp_path, "chinook-assistant/data/Chinook_Sqlite.sqlite")
        document = {
            "nodes": [{"id": "a", "type": "tool.chinook-execute-sql", "data": {}}],
            "edges": [],
        }
        found = _sqlite_files(document, tmp_path)
        assert found == [tmp_path / "chinook-assistant/data/Chinook_Sqlite.sqlite"]

    def test_missing_files_and_escaping_paths_are_ignored(self, tmp_path: Path) -> None:
        document = {
            "nodes": [
                {"id": "a", "type": "tool.sql-query", "data": {"database": "nope.sqlite"}},
                {"id": "b", "type": "tool.sql-query", "data": {"database": "../etc/passwd"}},
            ],
            "edges": [],
        }
        assert _sqlite_files(document, tmp_path) == []


class TestTableBrief:
    def test_the_brief_carries_schema_fks_both_directions_and_a_sample(self, tmp_path: Path) -> None:
        db = _seed_db(tmp_path, "flow/data/shop.sqlite")
        brief = SqliteEngineAdapter().table_brief(str(db), "orders")
        assert "customer_id" in brief and "customers" in brief
        assert "9.5" in brief  # data sample
        inbound = SqliteEngineAdapter().table_brief(str(db), "customers")
        assert "orders" in inbound  # referenced-by direction


class TestLivingExample:
    def test_the_chinook_workflow_discovers_its_bundled_tables(self) -> None:
        # The real repo tree, read-only: discovery over the seeded chinook
        # document finds the bundled database's tables, JOIN rules included.
        from openstategraph.api.workflow_store import WorkflowStore

        store = WorkflowStore()
        document = store.load("chinook-assistant")
        discovery = SqlKnowledgeBuilder().discover(
            store.directory_for("chinook-assistant"), document, store.root
        )
        topics = discovery.topics
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


class TestEngineRecognition:
    """Recognition from wiring — a ref's scheme (or barenesss) names its engine."""

    def test_bare_paths_and_sqlite_refs_are_sqlite(self) -> None:
        from openstategraph.knowledge_engines import recognize

        assert recognize("flow/data/shop.sqlite") == "sqlite"
        assert recognize("sqlite://flow/data/shop.sqlite") == "sqlite"

    def test_url_schemes_name_their_engines(self) -> None:
        from openstategraph.knowledge_engines import recognize

        assert recognize("postgres://u:p@host:5432/shop") == "postgres"
        assert recognize("postgresql://host/shop") == "postgres"
        assert recognize("mssql://host/shop") == "mssql"
        assert recognize("sqlserver://host/shop") == "mssql"

    def test_unknown_schemes_and_empty_refs_are_unrecognized(self) -> None:
        from openstategraph.knowledge_engines import recognize

        assert recognize("mongodb://host/db") is None
        assert recognize("   ") is None

    def test_document_sources_carry_ref_and_engine(self, tmp_path: Path) -> None:
        _seed_db(tmp_path, "flow/data/shop.sqlite")
        document = {
            "nodes": [
                {"id": "a", "type": "tool.sql-query", "data": {"database": "flow/data/shop.sqlite"}},
                {"id": "b", "type": "tool.sql-query", "data": {"database": "postgres://h/warehouse"}},
            ],
            "edges": [],
        }
        assert sql_sources_in_document(document, tmp_path) == [
            ("flow/data/shop.sqlite", "sqlite"),
            ("postgres://h/warehouse", "postgres"),
        ]


class TestEngineAdapters:
    """The IEngineAdapter seam — SQLite proven for real, pg/mssql pinned."""

    def test_the_sqlite_adapter_satisfies_the_contract_for_real(self, tmp_path: Path) -> None:
        from openstategraph.knowledge_engines import IEngineAdapter, SqliteEngineAdapter

        db = _seed_db(tmp_path, "flow/data/shop.sqlite")
        adapter = SqliteEngineAdapter()
        assert isinstance(adapter, IEngineAdapter)
        assert adapter.available() == (True, None)
        assert adapter.list_tables(str(db)) == ["customers", "orders"]
        schema = adapter.table_schema(str(db), "orders")
        assert "customer_id" in schema and "references customers.id" in schema
        inbound = adapter.table_schema(str(db), "customers")
        assert "referenced by" in inbound and "orders.customer_id" in inbound
        assert "9.5" in adapter.sample(str(db), "orders")
        assert "## Data sample" in adapter.table_brief(str(db), "orders")

    def test_the_postgres_introspection_sql_is_pinned(self) -> None:
        from openstategraph.knowledge_engines import PostgresEngineAdapter

        adapter = PostgresEngineAdapter()
        assert "information_schema.tables" in adapter.LIST_TABLES_SQL
        assert "information_schema.columns" in adapter.COLUMNS_SQL
        assert "pg_constraint" in adapter.FOREIGN_KEYS_SQL
        assert "conrelid" in adapter.FOREIGN_KEYS_SQL and "confrelid" in adapter.FOREIGN_KEYS_SQL

    def test_the_mssql_introspection_sql_is_pinned(self) -> None:
        from openstategraph.knowledge_engines import MssqlEngineAdapter

        adapter = MssqlEngineAdapter()
        assert "INFORMATION_SCHEMA.TABLES" in adapter.LIST_TABLES_SQL
        assert "INFORMATION_SCHEMA.COLUMNS" in adapter.COLUMNS_SQL
        assert "sys.foreign_key_columns" in adapter.FOREIGN_KEYS_SQL
        assert "sys.tables" in adapter.FOREIGN_KEYS_SQL

    def test_a_missing_driver_reports_unavailable_with_a_hint(self, monkeypatch: Any) -> None:
        from openstategraph.knowledge_engines import MssqlEngineAdapter, PostgresEngineAdapter

        for adapter in (PostgresEngineAdapter(), MssqlEngineAdapter()):
            monkeypatch.setattr(type(adapter), "_driver", lambda self: None)
            usable, warning = adapter.available()
            assert usable is False
            assert warning is not None and adapter.engine in warning and "pip install" in warning

    def test_a_recognized_but_unavailable_source_is_a_warning_not_a_crash(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        from openstategraph import knowledge_engines

        monkeypatch.setattr(
            type(knowledge_engines.ENGINE_ADAPTERS["postgres"]), "_driver", lambda self: None
        )
        document = {
            "nodes": [
                {"id": "a", "type": "tool.sql-query", "data": {"database": "postgres://h/warehouse"}}
            ],
            "edges": [],
        }
        discovery = SqlKnowledgeBuilder().discover(tmp_path / "flow", document, tmp_path)
        assert discovery.topics == []
        [warning] = discovery.warnings
        assert "postgres://h/warehouse" in warning
        assert "recognized as postgres" in warning and "unavailable" in warning

    def test_the_warning_reaches_the_run_report(self, tmp_path: Path, monkeypatch: Any) -> None:
        from openstategraph import knowledge_engines

        monkeypatch.setattr(
            type(knowledge_engines.ENGINE_ADAPTERS["postgres"]), "_driver", lambda self: None
        )
        document = {
            "nodes": [
                {"id": "a", "type": "tool.sql-query", "data": {"database": "postgres://h/warehouse"}}
            ],
            "edges": [],
        }
        report = run_build(tmp_path / "flow", document, ScriptedModel(), tmp_path)
        assert report["written"] == [] and report["skipped"] == []
        assert report["warnings"] and "postgres://h/warehouse" in report["warnings"][0]
        assert report["sources"]["sql"]["warnings"] == report["warnings"]


class TestOwnershipAndCollisions:
    """Invariant 5: markers record the owning builder; collisions are refused."""

    def test_the_marker_records_the_owning_builder(self, tmp_path: Path) -> None:
        builder = SqlKnowledgeBuilder()
        topic = KnowledgeTopic(name="orders", brief="b")
        builder.write(tmp_path / "flow", topic, "orders — a doc.")
        text = (tmp_path / "flow" / "knowledge" / "orders.md").read_text()
        assert text.startswith(GENERATED_MARKER)
        assert marker_source(text) == "sql"

    def test_marker_source_distinguishes_hand_authored_and_legacy(self) -> None:
        assert marker_source("# orders\nhand-written") is None
        assert marker_source(f"{GENERATED_MARKER}; regenerate -->\nbody") == ""
        assert marker_source(f"{GENERATED_MARKER} source=root; regenerate -->\nbody") == "root"

    def test_owns_gates_regeneration_by_marker_source(self, tmp_path: Path) -> None:
        builder = SqlKnowledgeBuilder()
        topic = KnowledgeTopic(name="orders", brief="b")
        knowledge = tmp_path / "flow" / "knowledge"
        knowledge.mkdir(parents=True)
        assert builder.owns(tmp_path / "flow", topic)  # absent file
        (knowledge / "orders.md").write_text(f"{GENERATED_MARKER} source=sql -->\nmine")
        assert builder.owns(tmp_path / "flow", topic)
        (knowledge / "orders.md").write_text(f"{GENERATED_MARKER} source=root -->\ntheirs")
        assert not builder.owns(tmp_path / "flow", topic)
        assert builder.collides_with(tmp_path / "flow", topic) == "root"
        (knowledge / "orders.md").write_text("# orders\nhand-authored")
        assert not builder.owns(tmp_path / "flow", topic)
        assert builder.collides_with(tmp_path / "flow", topic) is None

    def test_a_cross_builder_collision_is_refused_and_reported(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        _seed_db(tmp_path, "flow/data/shop.sqlite")

        class OverlappingBuilder(BaseKnowledgeBuilder):
            source_kind = "overlap"

            def discover(self, workflow_dir: Path, document: Any, workflows_root: Path) -> Discovery:
                return Discovery(topics=[KnowledgeTopic(name="orders", brief="also orders")])

        from openstategraph.api import knowledge_build as kb

        monkeypatch.setattr(
            kb, "BUILDERS", [SqlKnowledgeBuilder(), OverlappingBuilder()]
        )
        report = run_build(
            tmp_path / "flow", _document("flow/data/shop.sqlite"), ScriptedModel(), tmp_path
        )
        assert sorted(report["written"]) == ["customers", "orders"]
        [collision] = report["collisions"]
        assert "orders" in collision and "'sql'" in collision and "'overlap'" in collision
        assert report["sources"]["overlap"]["collisions"] == [collision]
        # never last-write-wins: the sql builder's doc survives untouched
        assert marker_source((tmp_path / "flow" / "knowledge" / "orders.md").read_text()) == "sql"


class TestIndexLineDrafting:
    """Generated docs open with their index line right after the marker."""

    def test_the_instruction_demands_a_first_line_summary(self) -> None:
        prompt = SqlKnowledgeBuilder().compose_prompt(KnowledgeTopic(name="orders", brief="b"))
        assert "FIRST line" in prompt and "index" in prompt

    def test_the_written_doc_serves_the_body_first_line_as_its_hint(self, tmp_path: Path) -> None:
        from openstategraph.knowledge import PackageKnowledge

        builder = SqlKnowledgeBuilder()
        builder.write(
            tmp_path / "flow",
            KnowledgeTopic(name="orders", brief="b"),
            "orders — one row per purchase.\n\nDetails.",
        )
        [entry] = PackageKnowledge(tmp_path / "flow").topics()
        assert entry.name == "orders"
        assert entry.hint == "orders — one row per purchase."


class TestRootKnowledgeBuilder:
    """Topics = the children this document MOUNTS; docs route, never copy up.

    Ticket 16 corrected the rule from "every published workflow on the
    platform" after finding both halves of the inversion on disk: the
    concierge carried a routing doc for a workflow it does not mount, and
    none for the hidden child it does. The mount is the routing fact.
    """

    @staticmethod
    def _save_child(
        root: Path, slug: str, *, hidden: bool = False, with_knowledge: bool = False
    ) -> None:
        package = root / slug
        package.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "name": slug.replace("-", " ").title(),
            "savedAt": "2026-01-01T00:00:00Z",
            "document": {
                "nodes": [
                    {"id": "in1", "type": "input.text", "data": {}},
                    {
                        "id": "r1",
                        "type": "route.classifier",
                        "data": {"branches": [{"id": "b1", "name": "sales"}]},
                    },
                ],
                "edges": [],
            },
        }
        if hidden:
            payload["hidden"] = True
        (package / "workflow.json").write_text(json.dumps(payload))
        (package / "AGENTS.md").write_text(f"# {slug}\n\nAnswers {slug} questions.\n")
        if with_knowledge:
            (package / "knowledge").mkdir()
            (package / "knowledge" / "sales.md").write_text("sales — child detail.\n")

    @staticmethod
    def _root_document(*slugs: str, kind: str = "workflow.subgraph") -> dict[str, Any]:
        return {
            "nodes": [
                {"id": f"m{i}", "type": kind, "data": {"workflow": slug}}
                for i, slug in enumerate(slugs or ("shop-child",))
            ],
            "edges": [],
        }

    def test_it_only_fires_on_a_workflow_that_mounts_something(self, tmp_path: Path) -> None:
        builder = RootKnowledgeBuilder()
        leaf = {"nodes": [{"id": "a", "type": "agent.llm", "data": {}}], "edges": []}
        self._save_child(tmp_path, "shop-child")
        assert builder.discover(tmp_path / "leaf-flow", leaf, tmp_path).topics == []
        # The slug is not the gate: a mountless `concierge` routes nowhere, so
        # it has nothing to write a routing doc about.
        assert builder.discover(tmp_path / "concierge", leaf, tmp_path).topics == []
        assert builder.discover(tmp_path / "concierge", self._root_document(), tmp_path).topics

    def test_topics_are_the_mounted_children_not_every_published_workflow(
        self, tmp_path: Path
    ) -> None:
        # The live defect: a gateway must not be taught to route somewhere it
        # has no edge to. `quiet-child` is published and perfectly visible —
        # and unmounted, so it is not this workflow's business.
        self._save_child(tmp_path, "shop-child", with_knowledge=True)
        self._save_child(tmp_path, "quiet-child")
        discovery = RootKnowledgeBuilder().discover(
            tmp_path / "gateway", self._root_document("shop-child"), tmp_path
        )
        assert [t.name for t in discovery.topics] == ["shop-child"]

    def test_a_mounted_child_is_a_topic_however_it_is_mounted(self, tmp_path: Path) -> None:
        self._save_child(tmp_path, "shop-child")
        discovery = RootKnowledgeBuilder().discover(
            tmp_path / "gateway",
            self._root_document("shop-child", kind="team.workflow"),
            tmp_path,
        )
        assert [t.name for t in discovery.topics] == ["shop-child"]

    def test_two_mounts_of_one_child_are_one_topic(self, tmp_path: Path) -> None:
        self._save_child(tmp_path, "shop-child")
        discovery = RootKnowledgeBuilder().discover(
            tmp_path / "gateway", self._root_document("shop-child", "shop-child"), tmp_path
        )
        assert [t.name for t in discovery.topics] == ["shop-child"]

    def test_a_mount_naming_no_package_is_a_warning_not_a_doc(self, tmp_path: Path) -> None:
        # The concierge's own dangling mount, generalised: a routing doc for a
        # package that will not load would send the gateway into a hole.
        self._save_child(tmp_path, "shop-child")
        discovery = RootKnowledgeBuilder().discover(
            tmp_path / "gateway", self._root_document("shop-child", "gone-child"), tmp_path
        )
        assert [t.name for t in discovery.topics] == ["shop-child"]
        assert len(discovery.warnings) == 1
        assert "gone-child: mounted here" in discovery.warnings[0]

    def test_the_root_workflow_never_lists_itself(self, tmp_path: Path) -> None:
        self._save_child(tmp_path, "gateway")  # visible and root-named
        self._save_child(tmp_path, "shop-child")
        discovery = RootKnowledgeBuilder().discover(
            tmp_path / "gateway", self._root_document("gateway", "shop-child"), tmp_path
        )
        assert [t.name for t in discovery.topics] == ["shop-child"]

    def test_the_brief_carries_topology_agents_head_and_drill_flag(self, tmp_path: Path) -> None:
        self._save_child(tmp_path, "shop-child", with_knowledge=True)
        self._save_child(tmp_path, "quiet-child")
        discovery = RootKnowledgeBuilder().discover(
            tmp_path / "gateway", self._root_document("shop-child", "quiet-child"), tmp_path
        )
        briefs = {t.name: t.brief for t in discovery.topics}
        assert "route.classifier" in briefs["shop-child"]
        assert "sales" in briefs["shop-child"]  # router branch
        assert "Answers shop-child questions" in briefs["shop-child"]
        assert "HAS its own knowledge store" in briefs["shop-child"]
        assert "no knowledge store of its own" in briefs["quiet-child"]

    def test_a_child_with_string_branches_does_not_crash_discovery(self, tmp_path: Path) -> None:
        # Found live on the real concierge build: a child node whose
        # data.branches is a string (or otherwise not a list of dicts).
        package = tmp_path / "odd-child"
        package.mkdir(parents=True)
        (package / "workflow.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": "Odd Child",
                    "savedAt": "2026-01-01T00:00:00Z",
                    "document": {
                        "nodes": [{"id": "n1", "type": "agent.llm", "data": {"branches": "oops"}}],
                        "edges": [],
                    },
                }
            )
        )
        discovery = RootKnowledgeBuilder().discover(
            tmp_path / "gateway", self._root_document("odd-child"), tmp_path
        )
        assert [t.name for t in discovery.topics] == ["odd-child"]

    def test_a_scripted_build_writes_one_routing_doc_per_child(self, tmp_path: Path) -> None:
        self._save_child(tmp_path, "shop-child", with_knowledge=True)
        self._save_child(tmp_path, "quiet-child")
        (tmp_path / "gateway").mkdir()
        model = ScriptedModel()
        report = run_build(
            tmp_path / "gateway",
            self._root_document("shop-child", "quiet-child"),
            model,
            tmp_path,
        )
        assert sorted(report["sources"]["root"]["written"]) == ["quiet-child", "shop-child"]
        doc = (tmp_path / "gateway" / "knowledge" / "shop-child.md").read_text()
        assert marker_source(doc) == "root"
        joined = "\n".join(model.prompts)
        assert "drill pointer" in joined and "route there for depth" in joined


class TestRootBuilderReachability:
    """The mount is the routing fact — not `published`, not `hidden`.

    Ticket 04 gated routing docs on `published_only`, reasoning that "a draft
    is invisible to /chat, so a routing doc pointing at it would route
    customers to a workflow they cannot reach". Right question, wrong
    destination: a mounted child is reached by *compiling it as a subgraph*,
    and `document_loader` consults neither flag. Applying the /chat-surface
    rule to a mount left the concierge with no routing doc for the hidden
    `workflow-architect` it actually mounts — found on disk, not argued.
    """

    def test_a_mounted_draft_child_still_gets_its_routing_doc(self, tmp_path: Path) -> None:
        TestRootKnowledgeBuilder._save_child(tmp_path, "draft-child")
        manifest = tmp_path / "draft-child" / "workflow.json"
        payload = json.loads(manifest.read_text())
        payload["published"] = False
        manifest.write_text(json.dumps(payload))

        discovery = RootKnowledgeBuilder().discover(
            tmp_path / "gateway",
            TestRootKnowledgeBuilder._root_document("draft-child"),
            tmp_path,
        )
        assert [t.name for t in discovery.topics] == ["draft-child"]

    def test_a_mounted_hidden_child_still_gets_its_routing_doc(self, tmp_path: Path) -> None:
        TestRootKnowledgeBuilder._save_child(tmp_path, "ghost-child", hidden=True)
        discovery = RootKnowledgeBuilder().discover(
            tmp_path / "gateway",
            TestRootKnowledgeBuilder._root_document("ghost-child"),
            tmp_path,
        )
        assert [t.name for t in discovery.topics] == ["ghost-child"]
        # Titled by slug: a hidden package is absent from the envelope listing
        # that carries display names, and the slug is what the mount names.
        assert "slug: ghost-child" in discovery.topics[0].brief


class TestProjectKnowledgeBuilder:
    """The project is a **source**, not a scope — recognised from the wiring.

    Ticket 14. There is no project-level store: a store is only worth writing
    where an agent is bound to read it, and binding is per package. So a
    workflow that wires a platform tool has *the project* as a source, its
    catalogue docs land in its own `knowledge/`, and the project's second
    brain is the union of the per-package ones. Pointers, not copies.
    """

    _save = staticmethod(TestRootKnowledgeBuilder._save_child)

    @staticmethod
    def _seer(*mounts: str) -> dict[str, Any]:
        """A document that can see the project, optionally mounting children."""
        nodes: list[dict[str, Any]] = [
            {"id": "t-list", "type": "tool.platform-list-workflows", "data": {}},
            {"id": "a1", "type": "agent.llm", "data": {}},
        ]
        nodes += [
            {"id": f"m{i}", "type": "workflow.subgraph", "data": {"workflow": slug}}
            for i, slug in enumerate(mounts)
        ]
        return {"nodes": nodes, "edges": []}

    @staticmethod
    def _set_flag(root: Path, slug: str, key: str, value: Any) -> None:
        manifest = root / slug / "workflow.json"
        payload = json.loads(manifest.read_text())
        payload[key] = value
        manifest.write_text(json.dumps(payload))

    def test_it_is_a_registered_pointer_builder(self) -> None:
        builder = ProjectKnowledgeBuilder()
        assert isinstance(builder, IKnowledgeBuilder)
        assert isinstance(builder, AbstractWorkflowPointerBuilder)
        assert builder.source_kind == "project"
        assert any(isinstance(b, ProjectKnowledgeBuilder) for b in BUILDERS)

    def test_the_wiring_is_the_recognition_nothing_else(self, tmp_path: Path) -> None:
        # No platform tool: the project is not a source here, however many
        # packages exist beside it. Same shape as a SQL builder on a workflow
        # with no database — recognition reads the canvas, never guesses.
        self._save(tmp_path, "shop-child")
        blind = {"nodes": [{"id": "a", "type": "agent.llm", "data": {}}], "edges": []}
        assert ProjectKnowledgeBuilder().discover(tmp_path / "gw", blind, tmp_path).topics == []
        assert ProjectKnowledgeBuilder().discover(tmp_path / "gw", self._seer(), tmp_path).topics

    def test_describe_alone_also_counts_as_seeing_the_project(self, tmp_path: Path) -> None:
        self._save(tmp_path, "shop-child")
        document = {
            "nodes": [{"id": "t", "type": "tool.platform-describe-workflow", "data": {}}],
            "edges": [],
        }
        discovery = ProjectKnowledgeBuilder().discover(tmp_path / "gw", document, tmp_path)
        assert [t.name for t in discovery.topics] == ["shop-child"]

    def test_topics_are_the_packages_the_platform_tools_would_show(self, tmp_path: Path) -> None:
        # The gate is read off `visible_to_platform_tools`, not restated: a
        # catalogue entry must never name a package the same agent's own
        # `platform_describe_workflow` would then refuse to describe.
        self._save(tmp_path, "shop-child")
        self._save(tmp_path, "ghost-child", hidden=True)
        self._save(tmp_path, "draft-child")
        self._set_flag(tmp_path, "draft-child", "published", False)
        discovery = ProjectKnowledgeBuilder().discover(tmp_path / "gw", self._seer(), tmp_path)
        assert [t.name for t in discovery.topics] == ["shop-child"]

    def test_the_gate_inverts_the_root_builders_on_purpose(self, tmp_path: Path) -> None:
        # Ticket 16's rule — the gate belongs to the mechanism that reaches
        # the destination — with its two opposite answers side by side, on the
        # same hidden package: a mount compiles it (doc), a platform tool
        # refuses it (no doc).
        self._save(tmp_path, "ghost-child", hidden=True)
        mounting = self._seer("ghost-child")
        assert [t.name for t in RootKnowledgeBuilder().discover(
            tmp_path / "gw", mounting, tmp_path
        ).topics] == ["ghost-child"]
        assert ProjectKnowledgeBuilder().discover(tmp_path / "gw", mounting, tmp_path).topics == []

    def test_a_mounted_child_is_the_root_builders_and_is_not_catalogued(
        self, tmp_path: Path
    ) -> None:
        # The two topic sets are partitioned by construction, so invariant 5's
        # collision machinery stays a backstop instead of firing on every
        # build of a gateway. A mount earns the better, routing-shaped doc.
        self._save(tmp_path, "shop-child")
        self._save(tmp_path, "quiet-child")
        document = self._seer("shop-child")
        assert [t.name for t in ProjectKnowledgeBuilder().discover(
            tmp_path / "gw", document, tmp_path
        ).topics] == ["quiet-child"]

    def test_a_workflow_never_catalogues_itself(self, tmp_path: Path) -> None:
        self._save(tmp_path, "gw")
        self._save(tmp_path, "shop-child")
        discovery = ProjectKnowledgeBuilder().discover(tmp_path / "gw", self._seer(), tmp_path)
        assert [t.name for t in discovery.topics] == ["shop-child"]

    def test_an_unreadable_package_is_a_warning_not_a_crash(self, tmp_path: Path) -> None:
        self._save(tmp_path, "shop-child")
        broken = tmp_path / "broken-child"
        broken.mkdir()
        (broken / "workflow.json").write_text("{not json")
        discovery = ProjectKnowledgeBuilder().discover(tmp_path / "gw", self._seer(), tmp_path)
        assert [t.name for t in discovery.topics] == ["shop-child"]
        assert len(discovery.warnings) == 1
        assert "broken-child" in discovery.warnings[0]

    def test_the_brief_is_a_pointer_never_a_copy(self, tmp_path: Path) -> None:
        self._save(tmp_path, "shop-child", with_knowledge=True)
        discovery = ProjectKnowledgeBuilder().discover(tmp_path / "gw", self._seer(), tmp_path)
        brief = discovery.topics[0].brief
        assert "route.classifier" in brief and "sales" in brief
        assert "Answers shop-child questions" in brief
        assert "HAS its own knowledge store" in brief
        # The child's own topic content stays in the child's store.
        assert "child detail" not in brief

    def test_a_scripted_build_writes_catalogue_docs_beside_routing_ones(
        self, tmp_path: Path
    ) -> None:
        self._save(tmp_path, "shop-child", with_knowledge=True)
        self._save(tmp_path, "quiet-child")
        (tmp_path / "gw").mkdir()
        model = ScriptedModel()
        report = run_build(tmp_path / "gw", self._seer("shop-child"), model, tmp_path)
        assert report["sources"]["root"]["written"] == ["shop-child"]
        assert report["sources"]["project"]["written"] == ["quiet-child"]
        assert report["collisions"] == []
        assert marker_source((tmp_path / "gw" / "knowledge" / "quiet-child.md").read_text()) == (
            "project"
        )
        catalogue = ProjectKnowledgeBuilder.INSTRUCTION
        assert "WHEN IT IS THE WRONG ANSWER" in catalogue
        # A catalogue doc is not a routing doc: it must not teach the reader to
        # send a question into a workflow this document has no edge to.
        assert "never tell the reader to route a question into it" in catalogue
        assert "open it for depth" in "\n".join(model.prompts)

    def test_project_topics_get_stale_badges_like_every_mechanical_source(
        self, tmp_path: Path
    ) -> None:
        # `current_source_hashes` used to name two builders literally, so a
        # third mechanical builder's docs could never be badged stale. It now
        # reads the registry and filters on `mechanical`.
        from openstategraph.api.knowledge_curation import current_source_hashes

        self._save(tmp_path, "quiet-child")
        (tmp_path / "gw").mkdir()
        hashes = current_source_hashes(tmp_path / "gw", self._seer(), tmp_path)
        assert "quiet-child" in hashes
        assert ProjectKnowledgeBuilder().mechanical is True
