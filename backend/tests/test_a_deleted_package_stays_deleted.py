"""A stale editor tab cannot resurrect a package it was told is gone.

launch-readiness ticket 147. Reproduced live, twice: tab A deletes workflow
`X`, tab B never refreshes, somebody types **one character**, disk autosave
fires, and `PUT /api/workflows/X` re-creates the directory. What comes back
holds `workflow.json` and `AGENTS.md` and nothing else — `tools/`,
`functions/`, `tests/`, `skills/`, `middlewares/` and `data/` are gone
permanently, and `published` is reset to `False`. No prompt, no toast, no
error: the tab looks like it saved successfully, because it did.

**The obvious fix is the wrong one.** `PUT` creating a package at a free slug
is deliberate and documented — it is how the CLI, a script and a test write a
package they intend to own. The defect is a *client writing to a slug it has
been told is gone*, so the guard is an opt-in the client asks for:
`must_exist`. The editor's `WorkflowFileClient` sets it on every save, because
every save it makes addresses a package it already holds (a create goes
through `POST /api/workflows`, which mints the slug).

The test is at this layer — the real store, the real route, a real directory
with real Python in it — because a unit test over the flag alone would stay
green against a writer that never sets it. So each case here deletes a package
out from under an open writer and then asserts what is on disk.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.api.workflow_store import WorkflowNotFoundError, WorkflowStore


@pytest.fixture()
def root(tmp_path):  # noqa: ANN001, ANN201
    return tmp_path / "workflows"


@pytest.fixture()
def client(root) -> TestClient:  # noqa: ANN001
    return TestClient(create_app(workflows_root=root), raise_server_exceptions=False)


def a_package_with_code(client: TestClient, root) -> str:  # noqa: ANN001
    """Create a package through the API and put the user's own Python in it."""
    created = client.post(
        "/api/workflows",
        json={"name": "Probe", "document": {"name": "Probe", "nodes": [], "edges": []}},
    )
    assert created.status_code == 201, created.text
    slug = created.json()["slug"]
    (root / slug / "tools").mkdir(parents=True, exist_ok=True)
    (root / slug / "tools" / "probe_tool.py").write_text("def probe() -> str:\n    return 'hi'\n")
    return slug


class TestTheEditorsWriterCannotResurrectAPackage:
    """The scenario, end to end: delete it, then let the stale writer write."""

    def test_the_write_is_refused_and_nothing_comes_back(
        self, client: TestClient, root
    ) -> None:  # noqa: ANN001
        slug = a_package_with_code(client, root)
        assert client.delete(f"/api/workflows/{slug}").status_code == 204
        assert not (root / slug).exists()

        # Exactly what disk autosave sends on the next keystroke.
        stale = client.put(
            f"/api/workflows/{slug}",
            json={
                "name": "Probe",
                "document": {"name": "Probe", "nodes": [{"id": "n1", "type": "agent"}]},
                "must_exist": True,
            },
        )

        assert stale.status_code == 404, stale.text
        # The whole harm in one assertion: nothing is re-created, so no hollow
        # package carrying a live workflow's slug is left behind.
        assert not (root / slug).exists()

    def test_the_slug_is_free_again_for_a_workflow_of_the_same_name(
        self, client: TestClient, root
    ) -> None:  # noqa: ANN001
        """The corpse used to squat on the name as well as the identity.

        A re-created directory occupies the slug, so `create` mints
        `probe-k7m3qp` for the next workflow of that name — the deletion looks
        undone *and* the replacement cannot have its own name back.
        """
        slug = a_package_with_code(client, root)
        client.delete(f"/api/workflows/{slug}")
        client.put(
            f"/api/workflows/{slug}",
            json={"name": "Probe", "document": {"name": "Probe"}, "must_exist": True},
        )

        again = client.post(
            "/api/workflows",
            json={"name": "Probe", "document": {"name": "Probe", "nodes": [], "edges": []}},
        )
        assert again.json()["slug"] == slug

    def test_a_live_package_is_still_written(self, client: TestClient, root) -> None:  # noqa: ANN001
        """The guard refuses a *missing* package, never a present one.

        Without this, the fix would be indistinguishable from switching disk
        autosave off — and the `tools/` it protects would be beside a document
        that never records an edit again.
        """
        slug = a_package_with_code(client, root)
        saved = client.put(
            f"/api/workflows/{slug}",
            json={
                "name": "Probe",
                "document": {"name": "Probe", "nodes": [{"id": "n1", "type": "agent"}]},
                "must_exist": True,
            },
        )
        assert saved.status_code == 200, saved.text
        assert (root / slug / "tools" / "probe_tool.py").is_file()
        envelope = json.loads((root / slug / "workflow.json").read_text())
        assert envelope["document"]["nodes"] == [{"id": "n1", "type": "agent"}]


class TestWhatTheGuardDoesNotChange:
    """`PUT` still creates for the callers the behaviour exists for."""

    def test_a_put_without_the_flag_still_creates(self, client: TestClient, root) -> None:  # noqa: ANN001
        made = client.put(
            "/api/workflows/hand-written",
            json={"name": "Hand Written", "document": {"name": "Hand Written"}},
        )
        assert made.status_code == 200, made.text
        assert (root / "hand-written" / "workflow.json").is_file()

    def test_the_flag_defaults_to_off_at_the_store(self, tmp_path) -> None:  # noqa: ANN001
        store = WorkflowStore(tmp_path / "workflows")
        store.save("made-here", name="Made Here", document={}, saved_at="2026-08-28T00:00:00+00:00")
        assert (tmp_path / "workflows" / "made-here" / "workflow.json").is_file()

    def test_the_store_names_the_missing_package_when_the_flag_is_set(self, tmp_path) -> None:  # noqa: ANN001
        """The store answers `WorkflowNotFoundError` — the route's 404 in kind.

        Raised rather than returned so a caller cannot ignore it by accident,
        and reusing the error `load` and `delete` already raise for the same
        condition rather than minting a second word for "there is no such
        package".
        """
        store = WorkflowStore(tmp_path / "workflows")
        with pytest.raises(WorkflowNotFoundError):
            store.save(
                "never-made",
                name="Never Made",
                document={},
                saved_at="2026-08-28T00:00:00+00:00",
                must_exist=True,
            )
        assert not (tmp_path / "workflows" / "never-made").exists()
