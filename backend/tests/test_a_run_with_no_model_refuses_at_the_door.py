"""`osg-agent-experience/48` — a run with no model ran half the graph first.

Measured on the try project on 2026-09-05, with no provider configured: the
run resolved the axis, scored fifteen lenses, routed, and only then died
inside one worker —

    Node failed and produced no result. Provider "ollama" has no credential

— which is honest and late. `/api/health` had known `model_configured: false`
since startup and the runnable starter's note already reads that flag to say
*nothing to run with yet*; the run doors did not.

The cause is one line of `NodeRuntime._base_model`'s own account: an
unconfigured provider comes back as a **stand-in that raises on first use**,
deliberately, so a workflow needing no model still runs. That deferral is
right for a function-only graph and wrong for a graph that will certainly
reach a model — and nothing at the door asked which it was.

So the door asks. One shared function, `model_readiness.unmet_model_requirement`,
answers all three (`POST /api/runs`, `openstategraph run`, MCP
`run_workflow`) with the readiness sentence the starter note and
`openstategraph providers` already quote — `elected_default().reason`, never a
second wording.

**What "model-driven" is read from.** Not a name list here: the compiler's own
`NodeRuntime.drives_a_model`, set where a node actually asks for a model
(`_resolve_model`) and unioned upward across a mount, so a parent of only
mounts is judged by what its children will do.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.providers import provider_catalogue, reset_provider_catalogue

CREDENTIALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")


def _n(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "data": data, "position": {"x": 0, "y": 0}}


def _e(source: str, sp: str, target: str, tp: str) -> dict[str, Any]:
    return {"source": {"nodeId": source, "portId": sp}, "target": {"nodeId": target, "portId": tp}}


AGENT_DOCUMENT = {
    "version": 1,
    "name": "one-agent",
    "nodes": [_n("in1", "input.text"), _n("agent1", "agent.llm"), _n("out1", "output.formatted")],
    "edges": [_e("in1", "text", "agent1", "prompt"), _e("agent1", "result", "out1", "result")],
}

NO_MODEL_DOCUMENT = {
    "version": 1,
    "name": "no-model",
    "nodes": [_n("in1", "input.text"), _n("out1", "output.formatted")],
    "edges": [_e("in1", "text", "out1", "result")],
}


@pytest.fixture
def no_credential(monkeypatch: pytest.MonkeyPatch):
    """Every integration installed, **no key for any of them**.

    Deliberately not the zero-integration state
    `test_no_provider_run_is_legible.py` builds: that one already raised
    `NoProviderInstalled` at the door and was already a 503. This is the state
    the ticket was filed from — a provider elected, importable, and with
    nothing to authenticate with, which is precisely the one that used to get
    through the door and fail at a node.
    """
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    reset_provider_catalogue()
    yield
    reset_provider_catalogue()


def _sentence() -> str:
    return provider_catalogue().elected_default().reason


class TestTheHttpDoor:
    def test_a_model_driven_graph_is_refused_before_a_node_runs(
        self, no_credential: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The trace is empty, asserted rather than described: the one function
        that drives the compiled graph is replaced with a raise."""
        import openstategraph.api.routes.runs as runs_route

        def never(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("a node ran — the door was supposed to refuse")

        monkeypatch.setattr(runs_route, "invoke_run", never)

        response = TestClient(create_app()).post(
            "/api/runs", json={"workflow": AGENT_DOCUMENT, "question": "hi"}
        )

        assert response.status_code == 503, response.text
        assert response.json()["detail"] == _sentence()

    def test_a_graph_with_no_model_in_it_still_runs(self, no_credential: None) -> None:
        response = TestClient(create_app()).post(
            "/api/runs", json={"workflow": NO_MODEL_DOCUMENT, "question": "hi"}
        )
        assert response.status_code == 200, response.text

    def test_a_configured_provider_is_not_refused(
        self, no_credential: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The door refuses *no provider at all*, never a particular model.

        This installation has no `mock` provider to name — `mock` is the
        editor's own deterministic preview selector and `_base_model` records
        that it has no backend equivalent — so the honest form of "a configured
        mock still runs" is this: give the process a credential and the same
        document is not refused. It fails later, on its own merits, which is
        what a run with a provider is entitled to do.
        """
        monkeypatch.setenv("OLLAMA_API_KEY", "not-a-real-key")
        reset_provider_catalogue()

        response = TestClient(create_app()).post(
            "/api/runs", json={"workflow": AGENT_DOCUMENT, "question": "hi"}
        )
        assert response.status_code != 503, response.text


class TestTheMcpDoor:
    def test_the_answer_is_the_same_sentence_shaped_as_findings(
        self, no_credential: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import openstategraph.mcp_server as mcp_server
        from openstategraph.api.services import WorkflowServices

        def never(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("a node ran — the door was supposed to refuse")

        monkeypatch.setattr(mcp_server, "invoke_run", never, raising=False)
        services = WorkflowServices()
        try:
            runs = mcp_server.WorkflowRuns(services)
            answer = runs.run("hi", None, AGENT_DOCUMENT, None, None, None, audience="developer")
        finally:
            services.close()

        assert answer["error"] == _sentence()
        assert answer["findings"] == [_sentence()]


class TestTheCliDoor:
    def test_run_refuses_and_exits_one(
        self, no_credential: None, monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
    ) -> None:
        import json

        from openstategraph import cli
        from openstategraph.loader import CompiledWorkflow

        package = tmp_path / "one-agent"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps(AGENT_DOCUMENT))

        def never(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("a node ran — the door was supposed to refuse")

        monkeypatch.setattr(CompiledWorkflow, "ask", never)

        code = cli.main(["run", str(package), "hi"])

        assert code == 1
        assert _sentence() in capsys.readouterr().err
