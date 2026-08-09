"""The Knowledge atom (ladder + lookup tool) — on-demand, never prompt-stuffed."""

from __future__ import annotations

from pathlib import Path

from openstategraph.knowledge import (
    BaseKnowledge,
    IKnowledge,
    PackageKnowledge,
    UnknownTopicError,
)
from openstategraph.prebuilt_knowledge import KnowledgeLookupTool


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

    def test_topics_are_the_markdown_stems_sorted(self, tmp_path: Path) -> None:
        store = PackageKnowledge(_package(tmp_path))
        assert store.topics() == ["album", "track"]

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
            assert exc.available == ["album", "track"]

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
