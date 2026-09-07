"""A save must not overwrite a `workflow.json` that changed under it.

`osg-agent-experience/45`. A coding agent rewrote
`workflows/<slug>/workflow.json` on disk while the same package was open in
the editor; the editor's autosave posted its in-memory document and four
edges the agent had written were gone, with no error anywhere — the save
genuinely succeeded.

The guard belongs at the seam that has both facts, and only the backend has
them: it is the only process that can see the file. So a client says which
version it is editing (`base_digest`, the digest it was handed when it
loaded), and a save whose base does not match the file's current digest is
**refused with 409** carrying the digest that is actually there. A save that
sends no base is unguarded exactly as before — the CLI and a script write
packages they own outright.

Nothing here asserts *what* the digest is. It is opaque on purpose: the only
promises are that it changes when the file's bytes change, and that the
number a save quotes came from the server rather than from a client's idea
of the content.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.api.workflow_store import (
    WorkflowChangedOnDiskError,
    WorkflowStore,
    package_digest,
)

DOCUMENT = {"name": "Notes", "nodes": [], "edges": []}


def _digest(store: WorkflowStore, slug: str) -> str:
    """What every caller outside the store reads — the row's own digest.

    Through `package_digest` for a slug with no package, because `describe`
    answers `None` there and "" is the honest digest of nothing.
    """
    row = store.describe(slug)
    assert row is None or row.digest == package_digest(store.directory_for(slug) / "workflow.json")
    return row.digest if row is not None else ""


@pytest.fixture
def store(tmp_path: Path) -> WorkflowStore:
    return WorkflowStore(root=tmp_path)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    root = tmp_path / "workflows"
    root.mkdir()
    with TestClient(create_app(workflows_root=root)) as test_client:
        yield test_client


def _rewrite_on_disk(path: Path, *, note: str) -> None:
    """What the coding agent does — edit the file, not the editor."""
    payload = json.loads(path.read_text())
    payload["document"]["nodes"] = [{"id": "n1", "type": "note", "data": {"text": note}}]
    path.write_text(json.dumps(payload, indent=2) + "\n")


class TestTheStoreKnowsWhatIsOnDisk:
    def test_a_digest_moves_when_the_file_does(self, store: WorkflowStore) -> None:
        slug = store.create(name="Notes", document=DOCUMENT, saved_at="t0")
        before = _digest(store, slug)
        assert before != ""

        _rewrite_on_disk(store.directory_for(slug) / "workflow.json", note="from the agent")
        assert _digest(store, slug) != before

    def test_a_slug_with_no_package_has_no_digest(self, store: WorkflowStore) -> None:
        assert _digest(store, "never-existed") == ""

    def test_a_stale_base_is_refused_and_the_file_keeps_the_disk_version(
        self, store: WorkflowStore
    ) -> None:
        slug = store.create(name="Notes", document=DOCUMENT, saved_at="t0")
        loaded = _digest(store, slug)
        path = store.directory_for(slug) / "workflow.json"
        _rewrite_on_disk(path, note="from the agent")

        with pytest.raises(WorkflowChangedOnDiskError) as refusal:
            store.save(
                slug,
                name="Notes",
                document={"name": "Notes", "nodes": [], "edges": []},
                saved_at="t1",
                expected_digest=loaded,
            )

        assert refusal.value.current == _digest(store, slug)
        assert store.load(slug)["nodes"][0]["data"]["text"] == "from the agent"

    def test_the_fresh_base_writes(self, store: WorkflowStore) -> None:
        slug = store.create(name="Notes", document=DOCUMENT, saved_at="t0")
        _rewrite_on_disk(store.directory_for(slug) / "workflow.json", note="from the agent")

        store.save(
            slug,
            name="Notes",
            document={"name": "Notes", "nodes": [], "edges": [], "mine": True},
            saved_at="t1",
            expected_digest=_digest(store, slug),
        )
        assert store.load(slug)["mine"] is True

    def test_no_base_at_all_is_unguarded(self, store: WorkflowStore) -> None:
        """The CLI, a script and a test write packages they own outright."""
        slug = store.create(name="Notes", document=DOCUMENT, saved_at="t0")
        _rewrite_on_disk(store.directory_for(slug) / "workflow.json", note="from the agent")

        store.save(slug, name="Notes", document={"name": "Notes", "mine": True}, saved_at="t1")
        assert store.load(slug)["mine"] is True


class TestTheRouteRefusesWithAConflict:
    def _created(self, client: TestClient) -> tuple[str, str]:
        made = client.post("/api/workflows", json={"name": "Notes", "document": DOCUMENT})
        assert made.status_code == 201
        slug = made.json()["slug"]
        got = client.get(f"/api/workflows/{slug}")
        return slug, got.json()["digest"]

    def test_a_fetched_document_carries_the_digest_it_was_read_at(
        self, client: TestClient
    ) -> None:
        slug, digest = self._created(client)
        assert digest != ""
        assert client.get(f"/api/workflows/{slug}/summary").json()["digest"] == digest

    def test_a_stale_save_is_409_and_the_agents_edit_survives(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        slug, digest = self._created(client)
        path = tmp_path / "workflows" / slug / "workflow.json"
        _rewrite_on_disk(path, note="from the agent")

        refused = client.put(
            f"/api/workflows/{slug}",
            json={
                "name": "Notes",
                "document": {"name": "Notes", "nodes": [], "edges": []},
                "must_exist": True,
                "base_digest": digest,
            },
        )
        assert refused.status_code == 409
        detail = refused.json()["detail"]
        assert detail["digest"] == client.get(f"/api/workflows/{slug}").json()["digest"]
        assert slug in detail["reason"]
        # The whole point: the agent's node is still there.
        assert json.loads(path.read_text())["document"]["nodes"][0]["id"] == "n1"

    def test_consecutive_saves_keep_working_by_adopting_the_returned_digest(
        self, client: TestClient
    ) -> None:
        slug, digest = self._created(client)
        for step in range(3):
            written = client.put(
                f"/api/workflows/{slug}",
                json={
                    "name": "Notes",
                    "document": {"name": "Notes", "nodes": [], "edges": [], "step": step},
                    "must_exist": True,
                    "base_digest": digest,
                },
            )
            assert written.status_code == 200, written.text
            adopted = written.json()["digest"]
            assert adopted != digest
            digest = adopted
        assert client.get(f"/api/workflows/{slug}").json()["document"]["step"] == 2

    def test_a_save_with_no_base_is_still_accepted(self, client: TestClient) -> None:
        slug, _ = self._created(client)
        written = client.put(
            f"/api/workflows/{slug}",
            json={"name": "Notes", "document": DOCUMENT, "must_exist": True},
        )
        assert written.status_code == 200
