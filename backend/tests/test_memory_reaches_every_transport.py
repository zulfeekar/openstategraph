"""Every transport compiles against the **memory** store — install-experience 12.

One word means two things in the class every transport goes through:
`WorkflowServices.store` is the filesystem `WorkflowStore` (packages on disk),
`WorkflowServices.memory_store` is LangGraph's `BaseStore` (long-term memory).
The statement `store = services.store` appears verbatim in the compiler and in
the MCP server meaning opposite objects, and `runtime_for` holds both spellings
seventeen lines apart.

The audit found the coverage asymmetric. `test_sdk_injection.py` round-trips a
fact through an injected store and would fail on a swap in `services.py` or
`loader.py` — but `mcp_server.py` and the three `routes/runs.py` call sites had
**no memory coverage at all**, so swapping one for the other there would ship
green, and the failure would surface at run time as an `AttributeError` inside
LangGraph mentioning no code of ours.

This file is that missing half, written *before* the rename that makes the
swap a type error, so the rename is protected rather than trusted. It asserts
identity — the object handed to `compile(store=)` **is** the one
`services.memory_store` returns — because the two classes share exactly one
method name (`delete`, different arity), so nothing weaker would notice.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.store.base import BaseStore

from openstategraph.api.main import create_app
from openstategraph.api.services import WorkflowServices


def _node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "data": data, "position": {"x": 0, "y": 0}}


def _edge(source: str, source_port: str, target: str, target_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": source, "portId": source_port},
        "target": {"nodeId": target, "portId": target_port},
    }


def _document() -> dict[str, Any]:
    """Input straight to output: compiles and runs with no model at all."""
    return {
        "version": 1,
        "name": "echo",
        "nodes": [_node("in1", "input.text"), _node("out1", "output.formatted")],
        "edges": [_edge("in1", "text", "out1", "text")],
    }


@pytest.fixture()
def stores(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Whatever each `WorkflowCompiler.build` was given as its `store`."""
    from openstategraph.compile import workflow_compiler

    seen: list[Any] = []
    original = workflow_compiler.WorkflowCompiler.build

    def spy(self: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("store"))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(workflow_compiler.WorkflowCompiler, "build", spy)
    return seen


class TestTheHttpRunPathsCompileAgainstTheMemoryStore:
    """`routes/runs.py` — run, stream and resume, the three the audit named."""

    @pytest.fixture()
    def app(self, tmp_path: Any) -> Any:
        return create_app(workflows_root=tmp_path)

    @pytest.mark.parametrize("path", ["/api/runs", "/api/runs/stream", "/api/runs/resume"])
    def test_the_store_it_compiles_with_is_the_memory_store(
        self, app: Any, stores: list[Any], path: str
    ) -> None:
        # Captured before the client's lifespan *shutdown*, which closes the
        # services object and clears the cached store so a later use resolves
        # a fresh one (install-experience ticket 11). The identity under test
        # is the one the request saw.
        expected = app.state.services.memory_store
        filesystem = app.state.services.store
        body: dict[str, Any] = {"workflow": _document(), "question": "hi"}
        if path.endswith("resume"):
            # A resume compiles before it can look at the thread, which is all
            # this assertion needs; the thread itself is another test's subject.
            # It takes no `question` — the run it continues asked one.
            body = {"workflow": _document(), "thread_id": "t-1", "decision": "approve"}

        with TestClient(app) as client:
            client.post(path, json=body)

        assert stores, f"{path} never reached WorkflowCompiler.build"
        assert stores[-1] is expected
        assert isinstance(stores[-1], BaseStore)
        # The other meaning of the word, and the one that must never arrive
        # here: a `WorkflowStore` passes the downstream `is not None` guard and
        # binds save_memory/search_memory to every agent.
        assert stores[-1] is not filesystem

    def test_the_compiled_graph_endpoint_does_too(self, app: Any, stores: list[Any]) -> None:
        """`routes/workflows.py`'s Mermaid preview compiles the same way, and
        the same one-token edit is available there."""
        slug = app.state.services.store.create(
            name="echo", document=_document(), saved_at="2026-08-15T00:00:00Z"
        )
        expected = app.state.services.memory_store

        with TestClient(app) as client:
            response = client.get(f"/api/workflows/{slug}/graph")
        assert response.status_code == 200, response.text

        assert stores, "the compiled-graph endpoint never reached WorkflowCompiler.build"
        assert stores[-1] is expected


class TestTheMcpTransportCompilesAgainstTheMemoryStore:
    def test_a_run_gets_the_memory_store(
        self, tmp_path: Any, stores: list[Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.mcp_server import WorkflowRuns

        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(var, raising=False)
        services = WorkflowServices(tmp_path)

        WorkflowRuns(services).run(document=_document(), question="hello")

        assert stores, "the MCP run tool never reached WorkflowCompiler.build"
        assert stores[-1] is services.memory_store
        assert stores[-1] is not services.store
        services.close()


class TestAFactSavedOverHttpLandsInThatStore:
    """The end-to-end half: identity is necessary, a round trip is sufficient.

    `test_sdk_injection.py` proves this for `load_workflow`. The HTTP path had
    no equivalent, which is what made a swap in `routes/runs.py` shippable.
    """

    def test_the_agents_save_memory_tool_writes_where_the_endpoint_said(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from test_sdk_injection import ToolCallingModel
        from openstategraph import chat_model as chat_model_module

        model = ToolCallingModel("save_memory", {"fact": "the invoice run is monthly"})
        monkeypatch.setattr(chat_model_module, "build_chat_model", lambda _name: model)
        # Who a run is for is a *deployment* decision, never a request field
        # (memory ticket 01): the header is trusted only because the operator
        # named it.
        monkeypatch.setenv("OPENSTATEGRAPH_PRINCIPAL_HEADER", "x-user")
        app = create_app(workflows_root=tmp_path)
        store = app.state.services.memory_store

        document = {
            "version": 1,
            "name": "remembers",
            "nodes": [
                _node("in1", "input.text"),
                _node("ag1", "agent.llm"),
                _node("out1", "output.formatted"),
            ],
            "edges": [
                _edge("in1", "text", "ag1", "prompt"),
                _edge("ag1", "result", "out1", "result"),
            ],
        }
        with TestClient(app) as client:
            response = client.post(
                "/api/runs",
                json={"workflow": document, "question": "remember that"},
                headers={"x-user": "ada@example.com"},
            )
        assert response.status_code == 200, response.text

        saved = [item.value["fact"] for item in store.search(("memories", "ada@example_com"))]
        assert saved == ["the invoice run is monthly"]
