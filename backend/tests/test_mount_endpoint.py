"""`GET /api/workflows/{root}/mounts/{path}` over real HTTP — ticket 42.

`test_mount_effective_document` pins the *resolution*; this pins the seam a
client actually meets: the route shape, the status codes, and the fact that a
stale or hand-typed address gets an answer it can act on rather than a shrug.

The status codes are a deliberate pair. A **404** means the address is
well-formed and names something that is not there — a deleted mount, a renamed
node, a bookmark from last week — and the client renders all of those the same
way: "this link is stale." A **422** means the address could not be a request
at all. Collapsing the two would make a broken link and an attack look alike.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.workflows_root import WORKFLOWS_ROOT_ENV


def _document(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": 2, "name": "doc", "nodes": nodes, "edges": []}


def _mount(node_id: str, slug: str, overrides: Any = None) -> dict[str, Any]:
    data: dict[str, Any] = {"workflow": slug}
    if overrides is not None:
        data["overrides"] = overrides
    return {"id": node_id, "type": "workflow.subgraph", "position": {"x": 0, "y": 0}, "data": data}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    root = tmp_path / "workflows"
    packages = {
        "grandchild": _document(
            [{"id": "deep", "type": "agent.llm", "position": {"x": 0, "y": 0}, "data": {}}]
        ),
        "child": _document(
            [
                {
                    "id": "agent-sql",
                    "type": "agent.llm",
                    "position": {"x": 0, "y": 0},
                    "data": {"rules": "package rules"},
                },
                _mount("wf-inner", "grandchild"),
            ]
        ),
        "parent": _document(
            [
                _mount("wf-music", "child", {"agent-sql": {"rules": "this mount only"}}),
                _mount("wf-other", "child"),
            ]
        ),
    }
    for slug, document in packages.items():
        directory = root / slug
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps({"version": 2, "name": slug, "document": document}, indent=2)
        )
    monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(root))
    return TestClient(create_app())


def _rules(document: dict[str, Any]) -> str:
    return next(n for n in document["nodes"] if n["id"] == "agent-sql")["data"]["rules"]


class TestItServesTheInstance:
    def test_a_mount_returns_the_package_with_its_own_overrides(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/workflows/parent/mounts/wf-music")
        assert response.status_code == 200
        body = response.json()
        assert body["root"] == "parent"
        # The **class**, which is what capabilities/knowledge are still asked
        # about — the instance is named by `mount_path`, not by a slug.
        assert body["slug"] == "child"
        assert body["mount_path"] == ["wf-music"]
        assert _rules(body["document"]) == "this mount only"

    def test_two_mounts_of_one_package_are_two_documents(self, client: TestClient) -> None:
        """The property the whole address scheme exists for, over the wire."""
        music = client.get("/api/workflows/parent/mounts/wf-music").json()
        other = client.get("/api/workflows/parent/mounts/wf-other").json()
        assert _rules(music["document"]) == "this mount only"
        assert _rules(other["document"]) == "package rules"
        assert music["slug"] == other["slug"] == "child"

    def test_a_grandchild_is_reachable_through_the_path(self, client: TestClient) -> None:
        """The `:path` converter earning its place — one more segment, one
        more level, no new endpoint."""
        response = client.get("/api/workflows/parent/mounts/wf-music/wf-inner")
        assert response.status_code == 200
        assert response.json()["mount_path"] == ["wf-music", "wf-inner"]
        assert response.json()["slug"] == "grandchild"

    def test_the_class_endpoint_still_answers_the_class(self, client: TestClient) -> None:
        """`?w=chinook-assistant` keeps its meaning; this is its backend half.
        The shared definition must never come back overridden."""
        response = client.get("/api/workflows/child")
        assert response.status_code == 200
        assert _rules(response.json()["document"]) == "package rules"


class TestRefusals:
    def test_an_unknown_root_is_404(self, client: TestClient) -> None:
        assert client.get("/api/workflows/nope/mounts/wf-music").status_code == 404

    def test_a_segment_that_is_not_a_node_names_where_the_walk_stopped(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/workflows/parent/mounts/wf-nope")
        assert response.status_code == 404
        assert "wf-nope" in response.json()["detail"]

    def test_a_node_that_is_not_a_mount_says_which_it_is(self, client: TestClient) -> None:
        """The mistake a hand-typed URL makes, and the one where "not found"
        alone would send someone looking for a missing package."""
        response = client.get("/api/workflows/parent/mounts/wf-music/agent-sql")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "agent-sql" in detail and "not a mount" in detail.lower()

    def test_an_empty_path_never_falls_back_to_the_root_document(
        self, client: TestClient
    ) -> None:
        assert client.get("/api/workflows/parent/mounts/").status_code in (404, 422)

    @pytest.mark.parametrize("attack", ["../secrets", "wf-music/../../etc", "..%2f..%2fetc"])
    def test_traversal_never_reaches_outside_the_workflows_root(
        self, client: TestClient, attack: str
    ) -> None:
        """Every slug on the walk goes through `directory_for`, never through
        string concatenation — so this is refused, not served."""
        response = client.get(f"/api/workflows/parent/mounts/{attack}")
        assert response.status_code in (404, 422)

    def test_a_self_mounting_package_is_refused_rather_than_looping(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "workflows"
        (root / "loop").mkdir(parents=True)
        (root / "loop" / "workflow.json").write_text(
            json.dumps(
                {"version": 2, "name": "loop", "document": _document([_mount("wf-self", "loop")])}
            )
        )
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(root))
        response = TestClient(create_app()).get("/api/workflows/loop/mounts/wf-self/wf-self")
        assert response.status_code == 404
        assert "loop" in response.json()["detail"]


class TestWarningsReachTheClient:
    def test_an_override_naming_an_unknown_node_opens_anyway_and_says_so(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """Loud, not fatal — `docs/decisions/mount-overrides.md`. A typo must
        not make an instance unopenable, but it must not be silent either."""
        path = tmp_path / "workflows" / "parent" / "workflow.json"
        payload = json.loads(path.read_text())
        for node in payload["document"]["nodes"]:
            if node["id"] == "wf-music":
                node["data"]["overrides"] = {"typo-id": {"rules": "x"}}
        path.write_text(json.dumps(payload, indent=2))

        body = client.get("/api/workflows/parent/mounts/wf-music").json()
        assert body["warnings"]
        assert "typo-id" in body["warnings"][0]
        assert _rules(body["document"]) == "package rules"
