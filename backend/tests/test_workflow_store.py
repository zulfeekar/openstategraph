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
    SlugMintingError,
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


class TestCreateMintsAUniqueSlug:
    """Ticket 20 — the collision that silently destroyed work.

    The reproduction, run before anything was changed: `slugify("My
    Workflow")` twice gives `my-workflow` twice, `save` did
    `mkdir(exist_ok=True)` and wrote, and the second workflow's document came
    back for *both* slugs — one directory on disk, the first workflow gone
    with no error. Everything below is that path, closed.
    """

    def test_the_first_workflow_of_a_name_keeps_the_clean_slug(
        self, store: WorkflowStore
    ) -> None:
        assert store.create(name="My Workflow", document={}, saved_at="t") == "my-workflow"

    def test_a_second_workflow_of_the_same_name_cannot_overwrite_the_first(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        first = store.create(
            name="My Workflow", document={"nodes": [{"id": "alice"}]}, saved_at="t1"
        )
        second = store.create(
            name="My Workflow", document={"nodes": [{"id": "bob"}]}, saved_at="t2"
        )

        assert second != first
        assert store.load(first) == {"nodes": [{"id": "alice"}]}
        assert store.load(second) == {"nodes": [{"id": "bob"}]}
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted([first, second])

    def test_the_disambiguator_is_the_name_plus_a_short_suffix(
        self, store: WorkflowStore
    ) -> None:
        store.create(name="My Workflow", document={}, saved_at="t")
        second = store.create(name="My Workflow", document={}, saved_at="t")
        # Readable prefix preserved — the URL still says what it is.
        assert second.startswith("my-workflow-")
        assert len(second) == len("my-workflow-") + 6
        # Round-trips through the store's own slug validation, so it is a
        # legal directory name and a legal URL segment.
        assert second == slugify(second)

    def test_a_hidden_package_still_counts_as_taken(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        # Ticket 21's trap: `list()` omits hidden packages, so minting against
        # a listing would hand out `concierge` on top of the live gateway.
        store.save("concierge", name="Concierge", document={}, saved_at="t")
        (tmp_path / "concierge" / "workflow.json").write_text(
            '{"version": 1, "name": "Concierge", "hidden": true, "document": {}}'
        )
        assert store.list() == []

        assert store.create(name="Concierge", document={"nodes": []}, saved_at="t2") != "concierge"

    def test_a_directory_holding_no_workflow_json_is_still_taken(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        # Somebody's half-written package, or a `tools/` folder made by hand.
        (tmp_path / "my-workflow").mkdir()
        assert store.create(name="My Workflow", document={}, saved_at="t") != "my-workflow"

    def test_a_created_workflow_is_a_draft_with_its_agents_md(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        slug = store.create(name="My Workflow", document={"nodes": []}, saved_at="t")
        assert (tmp_path / slug / "AGENTS.md").is_file()
        summary = store.describe(slug)
        assert summary is not None and summary.published is False

    def test_a_name_longer_than_the_filesystem_allows_is_still_creatable(
        self, store: WorkflowStore
    ) -> None:
        slug = store.create(name="X" * 300, document={}, saved_at="t")
        assert len(slug) <= 60
        assert store.describe(slug) is not None

    def test_it_raises_rather_than_overwriting_when_no_slug_can_be_claimed(
        self, store: WorkflowStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import openstategraph.api.workflow_store as module

        monkeypatch.setattr(module, "_candidate_slugs", lambda name: iter(["taken"]))
        store.save("taken", name="Taken", document={"nodes": [{"id": "keep"}]}, saved_at="t")

        with pytest.raises(SlugMintingError):
            store.create(name="Taken", document={"nodes": []}, saved_at="t2")
        # The point of the exception: the existing workflow is untouched.
        assert store.load("taken") == {"nodes": [{"id": "keep"}]}


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


class TestPublishLifecycle:
    """Ticket 04 (launch-readiness): drafts by default, publish gates /chat.

    The flag lives on the envelope as `"published": bool`, sibling of
    `"hidden"`. An envelope WITHOUT the field counts as published — every
    workflow that existed before the field did stays visible, so nothing
    breaks. `hidden` stays for infrastructure and trumps `published`.
    """

    def _write_envelope(self, root: Path, slug: str, **extra: object) -> None:
        import json

        directory = root / slug
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": slug,
                    "savedAt": "2026-01-01T00:00:00",
                    "document": {"nodes": [], "edges": []},
                    **extra,
                }
            )
        )

    def test_an_envelope_without_the_field_counts_as_published(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        self._write_envelope(tmp_path, "legacy")
        [summary] = store.list()
        assert summary.published is True

    def test_a_newly_saved_workflow_is_a_draft(self, store: WorkflowStore) -> None:
        store.save("fresh", name="Fresh", document={"nodes": [], "edges": []}, saved_at="t")
        [summary] = store.list()
        assert summary.published is False

    def test_resaving_preserves_the_published_flag(self, store: WorkflowStore) -> None:
        store.save("flow", name="Flow", document={"nodes": [], "edges": []}, saved_at="t")
        store.set_published("flow", True)
        store.save("flow", name="Flow v2", document={"nodes": [], "edges": []}, saved_at="t2")
        [summary] = store.list()
        assert summary.published is True

    def test_resaving_preserves_hidden(self, store: WorkflowStore, tmp_path: Path) -> None:
        self._write_envelope(tmp_path, "gateway", hidden=True)
        store.save("gateway", name="Gateway", document={"nodes": [], "edges": []}, saved_at="t")
        import json

        payload = json.loads((tmp_path / "gateway" / "workflow.json").read_text())
        assert payload["hidden"] is True

    def test_resaving_a_legacy_envelope_does_not_invent_the_field(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        # An envelope that predates the field stays implicitly published even
        # through a resave — nothing churns the two seeded examples' files.
        self._write_envelope(tmp_path, "legacy")
        store.save("legacy", name="Legacy", document={"nodes": [], "edges": []}, saved_at="t")
        import json

        payload = json.loads((tmp_path / "legacy" / "workflow.json").read_text())
        assert "published" not in payload

    def test_set_published_round_trips(self, store: WorkflowStore) -> None:
        store.save("flow", name="Flow", document={"nodes": [], "edges": []}, saved_at="t")
        store.set_published("flow", True)
        assert store.list()[0].published is True
        store.set_published("flow", False)
        assert store.list()[0].published is False

    def test_set_published_on_an_unknown_workflow_raises(self, store: WorkflowStore) -> None:
        with pytest.raises(WorkflowNotFoundError):
            store.set_published("nope", True)

    def test_published_only_listing_excludes_drafts(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        self._write_envelope(tmp_path, "live", published=True)
        self._write_envelope(tmp_path, "draft", published=False)
        assert {s.slug for s in store.list()} == {"live", "draft"}
        assert {s.slug for s in store.list(published_only=True)} == {"live"}

    def test_hidden_trumps_published(self, store: WorkflowStore, tmp_path: Path) -> None:
        self._write_envelope(tmp_path, "infra", hidden=True, published=True)
        assert store.list() == []
        assert store.list(published_only=True) == []


class TestDescribeIsExistenceNotVisibility:
    """Ticket 21: `list` answers what a surface advertises; `describe` answers
    whether a package is there.

    The two were one question, and the editor paid for it: `concierge` and
    `workflow-architect` are `hidden: true`, so they are absent from
    `GET /api/workflows` and present on disk — and the file watch, scanning
    that listing for its own slug, announced "This workflow was deleted on
    disk" over a file the backend was serving 200. These tests pin both
    directions, because deleting the warning would trade a false positive for
    a false negative: a stale copy of a genuinely deleted workflow is real.
    """

    def _write_envelope(self, root: Path, slug: str, **extra: object) -> None:
        import json

        directory = root / slug
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": slug,
                    "savedAt": "2026-01-01T00:00:00",
                    "document": {"nodes": [], "edges": []},
                    **extra,
                }
            )
        )

    def test_a_hidden_package_is_absent_from_the_listing_and_present_to_describe(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        self._write_envelope(tmp_path, "gateway", hidden=True)

        assert store.list() == []

        summary = store.describe("gateway")
        assert summary is not None
        assert summary.hidden is True
        assert summary.saved_at == "2026-01-01T00:00:00"

    def test_a_deleted_package_is_none_the_one_answer_that_means_gone(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        self._write_envelope(tmp_path, "gone", hidden=True)
        store.delete("gone")
        assert store.describe("gone") is None

    def test_a_slug_that_never_existed_is_none(self, store: WorkflowStore) -> None:
        assert store.describe("never-was") is None

    def test_a_visible_package_reports_hidden_false(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        self._write_envelope(tmp_path, "visible")
        summary = store.describe("visible")
        assert summary is not None and summary.hidden is False

    def test_an_unreadable_package_is_damaged_not_gone(
        self, store: WorkflowStore, tmp_path: Path
    ) -> None:
        # A file caught mid-write must not read as a deletion — it exists, it
        # is simply not parseable this instant. The row carries `error` and an
        # empty `saved_at`, which is "I cannot tell you when", not "gone".
        (tmp_path / "damaged").mkdir()
        (tmp_path / "damaged" / "workflow.json").write_text("{ not json")
        summary = store.describe("damaged")
        assert summary is not None
        assert summary.error and summary.saved_at == ""

    def test_a_malformed_slug_raises_rather_than_answering_gone(
        self, store: WorkflowStore
    ) -> None:
        # "You asked a malformed question" and "the package is gone" are the
        # two answers this method exists to keep apart.
        with pytest.raises(InvalidSlugError):
            store.describe("../etc")
