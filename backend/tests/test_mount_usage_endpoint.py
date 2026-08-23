"""`GET /api/workflows/{slug}/mount-usage` — production-ready ticket 17.

A person editing a field inside a mount can decide the mistake belongs to the
*package*, not the instance — "push to package". Before that write lands
they must be told two things this endpoint answers: how many mount nodes
across the whole workspace reference this package (every instance that will
pick up the correction), and which of those already carry their own override
for the exact same field (an instance that will keep running its own value
and silently *not* see the fix — the shadowing warning the ticket requires).

Mirrors `test_mount_endpoint.py`'s fixture shape and HTTP-level style.
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
        "child": _document(
            [
                {
                    "id": "agent-sql",
                    "type": "agent.llm",
                    "position": {"x": 0, "y": 0},
                    "data": {"rules": "package rules"},
                }
            ]
        ),
        # Two direct mounts of "child" — one shadows agent-sql.rules, one
        # does not, and one carries an override of a *different* field.
        "parent": _document(
            [
                _mount("wf-music", "child", {"agent-sql": {"rules": "this mount only"}}),
                _mount("wf-other", "child"),
            ]
        ),
        "second-parent": _document(
            [_mount("wf-third", "child", {"agent-sql": {"model": "gpt-4"}})],
        ),
        # Never mounts "child" — must not be counted.
        "unrelated": _document([]),
    }
    for slug, document in packages.items():
        directory = root / slug
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps({"version": 2, "name": slug, "document": document}, indent=2)
        )
    monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(root))
    return TestClient(create_app())


class TestMountUsage:
    def test_counts_every_direct_mount_across_the_workspace(self, client: TestClient) -> None:
        response = client.get(
            "/api/workflows/child/mount-usage",
            params={"child_node_id": "agent-sql", "key": "rules"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 3

    def test_names_only_the_hosts_shadowing_this_exact_field(self, client: TestClient) -> None:
        response = client.get(
            "/api/workflows/child/mount-usage",
            params={"child_node_id": "agent-sql", "key": "rules"},
        )
        body = response.json()
        # "parent" overrides rules on wf-music -> shadowed.
        # "second-parent" overrides a *different* key (model) on wf-third,
        # so it must not appear here even though it is a mount.
        assert body["shadowed_hosts"] == ["parent"]

    def test_a_package_nobody_mounts_reports_zero(self, client: TestClient) -> None:
        response = client.get(
            "/api/workflows/second-parent/mount-usage",
            params={"child_node_id": "wf-third", "key": "rules"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body == {"count": 0, "shadowed_hosts": []}

    def test_unknown_package_is_404(self, client: TestClient) -> None:
        response = client.get(
            "/api/workflows/does-not-exist/mount-usage",
            params={"child_node_id": "x", "key": "y"},
        )
        assert response.status_code == 404
