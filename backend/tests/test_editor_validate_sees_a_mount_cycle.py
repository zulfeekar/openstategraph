"""`POST /api/workflows/validate` said valid=true for a self-mounting package
(`workflow-gallery` 27, second half).

`openstategraph validate` (the CLI) was fixed in `da44407`: `cmd_validate`
now calls `unresolved_mounts`, which walks the mount chain on disk and
reports a cycle before it ever reaches the compiler. The editor's own
validate endpoint — `POST /api/workflows/validate`, the door
`test_validate_endpoint.py` built so the canvas could check a document before
a run costs anything — was never given the same call. It has a workflows
root (`services.store.root`, already used by `reachable_schema` two routes
up) and calls only `validate_document`, which plans the posted document *in
memory* and has no way to dereference a mount at all.

So the CLI refuses a self-mount and the editor, checking the exact same
document through the exact same package library, still says valid.  That is
the ticket's own "cheap gate says yes" bug, on a second cheap gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _document(*, mounts: str | None = None) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
        {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 9, "y": 0}},
    ]
    edges: list[dict[str, Any]] = []
    if mounts is None:
        edges.append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        )
    else:
        nodes.insert(
            1,
            {
                "id": "mount1",
                "type": "workflow.subgraph",
                "title": "The mount",
                "data": {"workflow": mounts},
                "position": {"x": 5, "y": 0},
            },
        )
        edges += [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "mount1", "portId": "input"},
            },
            {
                "source": {"nodeId": "mount1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ]
    return {"version": 3, "name": "doc", "nodes": nodes, "edges": edges}


def _package(root: Path, slug: str, *, mounts: str | None = None) -> dict[str, Any]:
    directory = root / slug
    directory.mkdir(parents=True)
    document = _document(mounts=mounts)
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": slug, "savedAt": "", "document": document})
    )
    return document


def _client(root: Path) -> TestClient:
    from openstategraph.api.main import create_app

    return TestClient(create_app(workflows_root=root))


def _compile_time_refusal(slug: str, chain: str) -> str:
    return f"Workflow {slug!r} mounts itself ({chain}); a mount cycle can never terminate"


class TestTheEndpoint:
    def test_a_package_that_mounts_itself_is_not_valid(self, tmp_path: Path) -> None:
        document = _package(tmp_path, "selfmount", mounts="selfmount")

        response = _client(tmp_path).post(
            "/api/workflows/validate", json={"workflow": document}
        )

        body = response.json()
        assert body["valid"] is False
        assert any(
            _compile_time_refusal("selfmount", "selfmount -> selfmount") in finding
            for finding in body["findings"]
        )

    def test_a_deep_legal_chain_still_validates(self, tmp_path: Path) -> None:
        _package(tmp_path, "leaf")
        _package(tmp_path, "level3", mounts="leaf")
        _package(tmp_path, "level2", mounts="level3")
        document = _package(tmp_path, "level1", mounts="level2")

        response = _client(tmp_path).post(
            "/api/workflows/validate", json={"workflow": document}
        )

        body = response.json()
        assert body["valid"] is True
        assert body["findings"] == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
