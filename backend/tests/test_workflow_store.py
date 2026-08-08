"""File-backed workflow persistence (tickets 10/14/16).

Every test operates on a throwaway `tmp_path` root — never the real
`workflows/` tree, so this suite cannot leave litter behind or collide with
the seeded Chinook workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.api.workflow_store import (
    InvalidSlugError,
    WorkflowNotFoundError,
    WorkflowStore,
    slugify,
)


class TestSlugify:
    def test_lowercases_and_hyphenates(self) -> None:
        assert slugify("Chinook Natural Language to SQL") == "chinook-natural-language-to-sql"

    def test_collapses_punctuation_to_one_hyphen(self) -> None:
        assert slugify("Q&A --- Bot!!") == "q-a-bot"

    def test_an_empty_or_all_punctuation_name_falls_back(self) -> None:
        assert slugify("") == "workflow"
        assert slugify("!!!") == "workflow"


@pytest.fixture
def store(tmp_path: Path) -> WorkflowStore:
    return WorkflowStore(root=tmp_path)


class TestSaveAndLoad:
    def test_a_saved_workflow_loads_back_the_same_document(self, store: WorkflowStore) -> None:
        document = {"version": 1, "name": "x", "nodes": [{"id": "n1"}], "edges": []}
        store.save("my-flow", name="My Flow", document=document, saved_at="2026-01-01T00:00:00")

        assert store.load("my-flow") == document

    def test_it_writes_workflow_json_under_the_slugs_own_directory(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        store.save("my-flow", name="My Flow", document={"nodes": [], "edges": []}, saved_at="t")
        assert (tmp_path / "my-flow" / "workflow.json").is_file()

    def test_a_first_save_generates_agents_md(self, store: WorkflowStore, tmp_path: Path) -> None:
        store.save("my-flow", name="My Flow", document={"nodes": [], "edges": []}, saved_at="t")
        agents = (tmp_path / "my-flow" / "AGENTS.md").read_text()
        assert "My Flow" in agents
        assert "workflow.json" in agents

    def test_a_second_save_does_not_regenerate_agents_md(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        store.save("my-flow", name="My Flow", document={"nodes": [], "edges": []}, saved_at="t1")
        agents_path = tmp_path / "my-flow" / "AGENTS.md"
        agents_path.write_text("hand-edited by the user")
        store.save("my-flow", name="My Flow", document={"nodes": [], "edges": []}, saved_at="t2")
        # A resave must not clobber something the developer wrote by hand.
        assert agents_path.read_text() == "hand-edited by the user"

    def test_renaming_never_creates_a_second_directory(self, store: WorkflowStore, tmp_path: Path) -> None:
        # The slug is frozen at creation; only the name inside the document
        # changes on a later save.
        store.save("my-flow", name="My Flow", document={"nodes": [], "edges": []}, saved_at="t1")
        store.save("my-flow", name="My Flow, Renamed", document={"nodes": [], "edges": []}, saved_at="t2")

        assert [p.name for p in tmp_path.iterdir()] == ["my-flow"]

    def test_loading_an_unknown_slug_raises(self, store: WorkflowStore) -> None:
        with pytest.raises(WorkflowNotFoundError):
            store.load("does-not-exist")

    def test_a_document_saved_without_the_envelope_still_loads(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        # A hand-authored workflow.json (no {"document": ...} envelope) —
        # the seeded Chinook workflow is exactly this shape.
        directory = tmp_path / "hand-authored"
        directory.mkdir()
        (directory / "workflow.json").write_text('{"version": 1, "nodes": [], "edges": []}')

        assert store.load("hand-authored") == {"version": 1, "nodes": [], "edges": []}


class TestList:
    def test_lists_every_saved_workflow_newest_first(self, store: WorkflowStore) -> None:
        store.save("a", name="A", document={"nodes": [1], "edges": []}, saved_at="2026-01-01")
        store.save("b", name="B", document={"nodes": [], "edges": []}, saved_at="2026-06-01")

        summaries = store.list()
        assert [s.slug for s in summaries] == ["b", "a"]
        assert summaries[1].node_count == 1

    def test_an_empty_root_lists_nothing_rather_than_raising(self, tmp_path: Path) -> None:
        assert WorkflowStore(root=tmp_path / "does-not-exist-yet").list() == []

    def test_one_unreadable_workflow_does_not_blank_the_whole_list(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        store.save("good", name="Good", document={"nodes": [], "edges": []}, saved_at="t")
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "workflow.json").write_text("{not valid json")

        assert [s.slug for s in store.list()] == ["good"]


class TestDelete:
    def test_deletes_the_whole_directory(self, store: WorkflowStore, tmp_path: Path) -> None:
        store.save("gone-soon", name="X", document={"nodes": [], "edges": []}, saved_at="t")
        store.delete("gone-soon")
        assert not (tmp_path / "gone-soon").exists()

    def test_deleting_an_unknown_slug_raises(self, store: WorkflowStore) -> None:
        with pytest.raises(WorkflowNotFoundError):
            store.delete("does-not-exist")


class TestSlugSafety:
    """A slug arrives over HTTP, from whoever is calling the API — never
    trusted as a bare path component."""

    @pytest.mark.parametrize("bad_slug", ["../escape", "/etc/passwd", "a/b", "a\\b", "", "Has Spaces"])
    def test_rejects_anything_that_is_not_a_plain_slug(self, store: WorkflowStore, bad_slug: str) -> None:
        with pytest.raises(InvalidSlugError):
            store.save(bad_slug, name="x", document={"nodes": [], "edges": []}, saved_at="t")

    def test_rejects_a_slug_that_resolves_outside_the_root(self, tmp_path: Path) -> None:
        # A root nested one level down, escaped via a slug that is otherwise
        # syntactically plain-looking once combined with `..` segments would
        # be caught by the `/`/`\\` check above; this pins the resolved-path
        # guard as a second, independent layer.
        nested_root = tmp_path / "root"
        nested_root.mkdir()
        store = WorkflowStore(root=nested_root)
        with pytest.raises(InvalidSlugError):
            store.directory_for("..")


class TestPackageValidator:
    """Ticket 49: findings, never exceptions."""

    def test_a_conforming_package_has_no_findings(self, tmp_path) -> None:
        from openstategraph.api.workflow_store import validate_package
        import json
        (tmp_path / "workflow.json").write_text(json.dumps(
            {"document": {"nodes": [], "edges": []}}))
        (tmp_path / "AGENTS.md").write_text("# hi")
        assert [f for f in validate_package(tmp_path) if f.startswith("error")] == []

    def test_a_missing_manifest_is_one_clear_error(self, tmp_path) -> None:
        from openstategraph.api.workflow_store import validate_package
        findings = validate_package(tmp_path)
        assert len(findings) == 1 and findings[0].startswith("error: no workflow.json")

    def test_tools_without_tests_warns(self, tmp_path) -> None:
        from openstategraph.api.workflow_store import validate_package
        import json
        (tmp_path / "workflow.json").write_text(json.dumps({"document": {"nodes": []}}))
        (tmp_path / "AGENTS.md").write_text("# hi")
        tools = tmp_path / "tools"; tools.mkdir()
        (tools / "t.py").write_text("x=1")
        assert any("tools/ without tests/" in f for f in validate_package(tmp_path))
