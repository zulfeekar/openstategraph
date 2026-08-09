"""The Knowledge atom (ladder + lookup tool) — on-demand, never prompt-stuffed."""

from __future__ import annotations

from pathlib import Path

from openstategraph.knowledge import (
    BaseKnowledge,
    IKnowledge,
    PackageKnowledge,
    TopicIndexEntry,
    UnknownTopicError,
)
from openstategraph.prebuilt_knowledge import KnowledgeLookupTool, ambient_knowledge_tool


def _package(tmp_path: Path) -> Path:
    knowledge = tmp_path / "flow" / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "album.md").write_text("# album\nJoins Artist via ArtistId.")
    (knowledge / "track.md").write_text("# track\nUnitPrice is per-track revenue basis.")
    return tmp_path / "flow"


class TestLadder:
    def test_package_knowledge_satisfies_the_protocol(self, tmp_path: Path) -> None:
        store = PackageKnowledge(_package(tmp_path))
        assert isinstance(store, IKnowledge)
        assert isinstance(store, BaseKnowledge)

    def test_topics_are_the_markdown_stems_sorted_with_index_hints(self, tmp_path: Path) -> None:
        store = PackageKnowledge(_package(tmp_path))
        assert store.topics() == [
            TopicIndexEntry(name="album", hint="album"),
            TopicIndexEntry(name="track", hint="track"),
        ]

    def test_lookup_is_case_insensitive_via_normalization(self, tmp_path: Path) -> None:
        store = PackageKnowledge(_package(tmp_path))
        assert "ArtistId" in store.lookup("Album")

    def test_an_unknown_topic_raises_with_the_available_topics(self, tmp_path: Path) -> None:
        store = PackageKnowledge(_package(tmp_path))
        try:
            store.lookup("invoice")
            raise AssertionError("expected UnknownTopicError")
        except UnknownTopicError as exc:
            assert exc.topic == "invoice"
            assert [entry.name for entry in exc.available] == ["album", "track"]

    def test_a_traversal_shaped_topic_cannot_escape_the_directory(self, tmp_path: Path) -> None:
        package = _package(tmp_path)
        (tmp_path / "secret.md").write_text("outside")
        store = PackageKnowledge(package)
        try:
            store.lookup("../../secret")
            raise AssertionError("expected UnknownTopicError")
        except UnknownTopicError:
            pass

    def test_a_missing_knowledge_directory_means_no_topics(self, tmp_path: Path) -> None:
        (tmp_path / "bare").mkdir()
        assert PackageKnowledge(tmp_path / "bare").topics() == []

    def test_normalize_is_a_stable_slug(self) -> None:
        assert BaseKnowledge.normalize("  Invoice Line ") == "invoice-line"


class TestKnowledgeLookupTool:
    def test_it_answers_from_the_package_knowledge(self, tmp_path: Path) -> None:
        tool = KnowledgeLookupTool(package_dir=_package(tmp_path))
        result = tool.run(topic="album")
        assert result.ok and "ArtistId" in result.content

    def test_an_unknown_topic_lists_the_available_topics(self, tmp_path: Path) -> None:
        tool = KnowledgeLookupTool(package_dir=_package(tmp_path))
        result = tool.run(topic="invoice")
        assert not result.ok
        assert result.error is not None
        assert "album" in result.error and "track" in result.error

    def test_unconfigured_it_refuses_with_instructions(self) -> None:
        result = KnowledgeLookupTool().run(topic="album")
        assert not result.ok
        assert result.error is not None and "workflow" in result.error.lower()

    def test_an_empty_store_points_at_build_second_brain(self, tmp_path: Path) -> None:
        (tmp_path / "bare").mkdir()
        result = KnowledgeLookupTool(package_dir=tmp_path / "bare").run(topic="album")
        assert not result.ok
        assert result.error is not None and "second brain" in result.error.lower()


class TestRegistryWiring:
    def test_the_open_workflows_registry_binds_its_own_knowledge_dir(self, tmp_path: Path) -> None:
        from openstategraph.api.registries import build_tool_registry
        from openstategraph.api.workflow_store import WorkflowStore

        package = tmp_path / "my-flow"
        knowledge = package / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "orders.md").write_text("orders join customers on customer_id")
        (package / "workflow.json").write_text('{"nodes": [], "edges": []}')

        registry = build_tool_registry(WorkflowStore(root=tmp_path), "my-flow")
        tool = registry["tool.knowledge-lookup"]
        result = tool.run(topic="orders")
        assert result.ok and "customer_id" in result.content

    def test_with_no_slug_the_tool_is_registered_but_unbound(self) -> None:
        from openstategraph.api.registries import build_tool_registry
        from openstategraph.api.workflow_store import WorkflowStore

        registry = build_tool_registry(WorkflowStore(), None)
        assert "tool.knowledge-lookup" in registry
        assert not registry["tool.knowledge-lookup"].run(topic="x").ok


class TestIndexHints:
    """The index tier: `topics()` hints are the docs' first meaningful lines."""

    def test_the_hint_is_the_first_line_after_the_generated_marker(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "flow" / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "orders.md").write_text(
            "<!-- generated by build-second-brain source=sql; delete to claim -->\n\n"
            "orders — one row per customer purchase.\n\nMore detail below.\n"
        )
        [entry] = PackageKnowledge(tmp_path / "flow").topics()
        assert entry == TopicIndexEntry(name="orders", hint="orders — one row per customer purchase.")

    def test_a_marker_only_file_yields_an_empty_hint(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "flow" / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "bare.md").write_text("<!-- generated by build-second-brain source=sql -->\n")
        [entry] = PackageKnowledge(tmp_path / "flow").topics()
        assert entry == TopicIndexEntry(name="bare", hint="")

    def test_an_empty_file_yields_an_empty_hint(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "flow" / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "empty.md").write_text("")
        [entry] = PackageKnowledge(tmp_path / "flow").topics()
        assert entry == TopicIndexEntry(name="empty", hint="")

    def test_a_hand_authored_heading_is_stripped_to_its_text(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "flow" / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "billing.md").write_text("## Billing rules\nFiscal year starts April.\n")
        [entry] = PackageKnowledge(tmp_path / "flow").topics()
        assert entry == TopicIndexEntry(name="billing", hint="Billing rules")

    def test_the_lookup_tools_unknown_topic_listing_shows_name_and_hint(
        self, tmp_path: Path
    ) -> None:
        knowledge = tmp_path / "flow" / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "orders.md").write_text("orders — purchases, one row each.\n")
        result = KnowledgeLookupTool(package_dir=tmp_path / "flow").run(topic="nope")
        assert not result.ok
        assert result.error is not None
        assert "- orders — orders — purchases, one row each." in result.error


class TestAmbientSeeking:
    """Knowledge-seeking is ambient, not opt-in (knowledge-architecture.md):
    a non-empty knowledge/ auto-binds the lookup tool to every agent."""

    @staticmethod
    def _package(tmp_path: Path, *, with_docs: bool) -> Path:
        package = tmp_path / "flow"
        (package / "knowledge").mkdir(parents=True, exist_ok=True)
        if with_docs:
            (package / "knowledge" / "orders.md").write_text("orders — purchases.\n")
        return package

    def test_the_helper_yields_a_tool_only_for_a_non_empty_knowledge_dir(
        self, tmp_path: Path
    ) -> None:
        assert ambient_knowledge_tool(None) is None
        assert ambient_knowledge_tool(self._package(tmp_path, with_docs=False)) is None
        tool = ambient_knowledge_tool(self._package(tmp_path, with_docs=True))
        assert tool is not None and tool.run(topic="orders").ok

    def test_an_agent_gets_the_tool_with_no_knowledge_atom_wired(self, tmp_path: Path) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime
        from openstategraph.compile.workflow_compiler import CompiledPlan

        runtime = NodeRuntime(
            model=None, knowledge_package_dir=self._package(tmp_path, with_docs=True)
        )
        node = {"id": "a1", "type": "agent.llm", "data": {}}
        runtime.factory({"nodes": [node], "edges": []})("a1", node, CompiledPlan())
        assert "knowledge_lookup" in runtime.last_bound_tools

    def test_a_workflow_without_knowledge_docs_binds_no_tool(self, tmp_path: Path) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime
        from openstategraph.compile.workflow_compiler import CompiledPlan

        runtime = NodeRuntime(
            model=None, knowledge_package_dir=self._package(tmp_path, with_docs=False)
        )
        node = {"id": "a1", "type": "agent.llm", "data": {}}
        runtime.factory({"nodes": [node], "edges": []})("a1", node, CompiledPlan())
        assert "knowledge_lookup" not in runtime.last_bound_tools

    def test_an_explicit_atom_plus_the_ambient_rule_is_one_tool_not_two(
        self, tmp_path: Path
    ) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime
        from openstategraph.compile.workflow_compiler import CompiledPlan
        from openstategraph.prebuilt_knowledge import knowledge_lookup_for

        package = self._package(tmp_path, with_docs=True)
        runtime = NodeRuntime(
            model=None,
            tools=knowledge_lookup_for(package),
            knowledge_package_dir=package,
        )
        agent = {"id": "a1", "type": "agent.llm", "data": {}}
        atom = {"id": "k1", "type": "tool.knowledge-lookup", "data": {}}
        plan = CompiledPlan()
        plan.tool_bindings = {"a1": ["k1"]}
        factory = runtime.factory({"nodes": [agent, atom], "edges": []})
        factory("k1", atom, plan)
        factory("a1", agent, plan)
        assert runtime.last_bound_tools.count("knowledge_lookup") == 1

    def test_a_child_subgraph_seeks_its_own_knowledge_not_the_parents(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        from openstategraph.compile import node_runtime as module
        from openstategraph.compile.node_runtime import NodeRuntime, PackageAssets

        parent_pkg = tmp_path / "parent"
        (parent_pkg / "knowledge").mkdir(parents=True)
        (parent_pkg / "knowledge" / "routing.md").write_text("routing — parent doc.\n")
        child_pkg = tmp_path / "child"
        (child_pkg / "knowledge").mkdir(parents=True)
        (child_pkg / "knowledge" / "orders.md").write_text("orders — child doc.\n")

        captured: dict[str, object] = {}
        real = module.NodeRuntime

        class Spy(real):  # type: ignore[misc, valid-type]
            def __init__(self, **kwargs: object) -> None:
                services = kwargs.get("services")
                if services is not None:
                    captured["knowledge"] = services.knowledge_package_dir  # type: ignore[attr-defined]
                super().__init__(**kwargs)

        monkeypatch.setattr(module, "NodeRuntime", Spy)  # type: ignore[attr-defined]

        child_doc = {
            "nodes": [
                {"id": "cin", "type": "input.text", "data": {}},
                {"id": "cout", "type": "output.formatted", "data": {}},
            ],
            "edges": [
                {
                    "source": {"nodeId": "cin", "portId": "text"},
                    "target": {"nodeId": "cout", "portId": "result"},
                }
            ],
        }
        runtime = NodeRuntime(
            document_loader=lambda slug: child_doc,
            package_loader=lambda slug: PackageAssets(
                tools={}, functions={}, knowledge_dir=child_pkg
            ),
            knowledge_package_dir=parent_pkg,
        )
        sub = {"id": "sub1", "type": "workflow.subgraph", "data": {"workflow": "child"}}
        from openstategraph.compile.workflow_compiler import CompiledPlan

        runtime.factory({"nodes": [sub], "edges": []})("sub1", sub, CompiledPlan())
        assert captured["knowledge"] == child_pkg
