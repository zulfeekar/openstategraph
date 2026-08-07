"""Tests at the exact seams the 2026-08-07 findings sweep showed were bare.

Each of these pins a defect that shipped silently because nothing tested the
request contract itself: an extra field 422ing every resume, an envelope
compiling to a zero-node graph, and a slug that was supposed to bind tools
and could never import them.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dyflow.api.main import create_app

REPO = Path(__file__).resolve().parent.parent.parent

MINIMAL_DOCUMENT = {
    "version": 2,
    "name": "seam-test",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "hi"}},
        {"id": "out1", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    ],
}


def _client() -> TestClient:
    return TestClient(create_app(workflows_root=REPO / "workflows"))


class TestResumeAcceptsTheSlug:
    def test_workflow_slug_is_not_rejected_at_validation(self) -> None:
        """The client echoes the slug on resume; `extra="forbid"` on a model
        without the field turned every approval into a 422."""
        response = _client().post(
            "/api/runs/resume",
            json={
                "thread_id": "no-such-thread",
                "workflow": MINIMAL_DOCUMENT,
                "decision": "approve",
                "workflow_slug": "tabular-analytics",
            },
        )
        assert response.status_code != 422, response.text


class TestEnvelopeUnwrapping:
    def test_an_enveloped_document_still_compiles_to_its_nodes(self) -> None:
        """The store saves `{version,name,savedAt,document}`; compiling the
        envelope itself produces a zero-node graph and a 502."""
        response = _client().post(
            "/api/runs",
            json={
                "workflow": {
                    "version": 1,
                    "name": "seam-test",
                    "savedAt": "2026-08-07T00:00:00Z",
                    "document": MINIMAL_DOCUMENT,
                },
                "question": "hello",
                "model": "ollama:unused",
            },
        )
        # A zero-node graph 502s ("Graph must have an entrypoint"); the
        # question flowing through to the answer proves the inner document's
        # nodes were compiled. (`_input` prefers the caller's question over
        # its stored prompt, by documented design.)
        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "hello"

    def test_a_bare_document_keeps_working(self) -> None:
        response = _client().post(
            "/api/runs",
            json={"workflow": MINIMAL_DOCUMENT, "question": "hello", "model": "ollama:unused"},
        )
        assert response.status_code == 200, response.text


class TestSlugToolBinding:
    """`build_tool_registry` is the seam the endpoints share — tested
    directly, because exercising it through `/api/runs` would need a live
    model call the moment an agent node is present."""

    @staticmethod
    def _store():
        from dyflow.api.workflow_store import WorkflowStore

        return WorkflowStore(root=REPO / "workflows")

    def test_the_tabular_slug_layers_its_tools_over_the_defaults(self) -> None:
        from dyflow.api.main import build_tool_registry

        registry = build_tool_registry(self._store(), "tabular-analytics")
        # Workflow tools present…
        assert "tool.tabular-query" in registry
        assert "tool.tabular-sample" in registry
        # …and the defaults kept, so the intent-routed demo's Chinook
        # bindings still resolve from any workflow context.
        assert "tool.chinook-execute-sql" in registry

    def test_no_slug_means_the_default_registry(self) -> None:
        from dyflow.api.main import build_tool_registry

        registry = build_tool_registry(self._store(), None)
        assert "tool.chinook-execute-sql" in registry
        assert "tool.tabular-query" not in registry

    def test_an_unknown_slug_degrades_to_defaults_not_an_error(self) -> None:
        from dyflow.api.main import build_tool_registry

        registry = build_tool_registry(self._store(), "definitely-not-a-workflow")
        assert "tool.chinook-execute-sql" in registry

    def test_a_bound_tabular_tool_resolves_with_no_warning(self) -> None:
        """The end of the chain: a runtime holding the slug registry binds
        `tool.tabular-query` silently — no `unresolved_tools` entry, which is
        the exact signal whose absence meant 'agent answers from memory'."""
        from dyflow.api.main import build_tool_registry
        from dyflow.compile.node_runtime import NodeRuntime

        runtime = NodeRuntime(tools=build_tool_registry(self._store(), "tabular-analytics"))
        runtime._types["t1"] = "tool.tabular-query"
        runtime._nodes["t1"] = {"id": "t1", "type": "tool.tabular-query", "data": {"maxRows": 5}}
        tool = runtime._bound_tool("t1")
        assert tool is not None
        assert tool.row_cap == 5
        assert runtime.unresolved_tools == []
