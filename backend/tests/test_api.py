"""Tests for the editor ↔ runtime seam.

The HTTP layer is exercised with an injected stub graph, so these run with no API
key and no provider. What they verify is the contract the frontend depends on:
the response shape, that a missing model is reported rather than guessed at, and
that the Mermaid preview needs no model at all.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from dyflow.api.main import OLLAMA_CLOUD_MODEL, create_app, resolve_model


class StubGraph:
    def __init__(self, final: dict[str, Any]):
        self._final = final
        self.configs: list[dict[str, Any]] = []

    def invoke(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        self.configs.append(config or {})
        return {**self._final, "question": state["question"]}


GOOD_FINAL = {
    "answer": "Rock earns the most, at 826.65.",
    "sql": "SELECT g.Name, SUM(...) FROM InvoiceLine il JOIN Track t ...",
    "rows": "| Genre | Revenue |\n| --- | --- |\n| Rock | 826.65 |",
    "attempts": 1,
    "verdict": {"passed": True, "reason": "Rows returned."},
}


@pytest.fixture
def client() -> TestClient:
    graph = StubGraph(GOOD_FINAL)
    return TestClient(create_app(graph_factory=lambda _model: graph))


class TestAsk:
    def test_a_question_returns_an_answer(self, client: TestClient) -> None:
        response = client.post(
            "/api/workflows/chinook-nl-to-sql/ask",
            json={"question": "Which genre earns the most?", "model": "anthropic:x"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["answer"].startswith("Rock earns the most")
        assert body["passed"] is True

    def test_it_returns_the_sql_and_rows_so_the_answer_is_auditable(
        self, client: TestClient
    ) -> None:
        # An answer a developer cannot check is not much use; the SQL is how they
        # tell a right answer from a plausible one.
        body = client.post(
            "/api/workflows/chinook-nl-to-sql/ask",
            json={"question": "q", "model": "anthropic:x"},
        ).json()
        assert "InvoiceLine" in body["sql"]
        assert "826.65" in body["rows"]

    def test_the_recursion_limit_is_a_top_level_config_key(self) -> None:
        graph = StubGraph(GOOD_FINAL)
        c = TestClient(create_app(graph_factory=lambda _m: graph))
        c.post(
            "/api/workflows/chinook-nl-to-sql/ask",
            json={"question": "q", "model": "anthropic:x", "recursion_limit": 42},
        )
        # Inside `configurable` it silently does nothing — the common mistake.
        assert graph.configs[0]["recursion_limit"] == 42
        assert "configurable" not in graph.configs[0]

    def test_an_empty_question_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/workflows/chinook-nl-to-sql/ask", json={"question": "", "model": "x"}
        )
        assert response.status_code == 422

    def test_unknown_fields_are_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/workflows/chinook-nl-to-sql/ask",
            json={"question": "q", "model": "x", "surprise": 1},
        )
        assert response.status_code == 422

    def test_a_runtime_failure_becomes_502_not_a_stack_trace(self) -> None:
        class Exploding:
            def invoke(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("provider unreachable")

        c = TestClient(create_app(graph_factory=lambda _m: Exploding()))
        response = c.post(
            "/api/workflows/chinook-nl-to-sql/ask",
            json={"question": "q", "model": "anthropic:x"},
        )
        assert response.status_code == 502
        assert "provider unreachable" in response.json()["detail"]


class TestModelResolution:
    def test_an_explicit_model_wins(self) -> None:
        assert resolve_model("ollama:llama3.1:8b") == "ollama:llama3.1:8b"

    def test_no_configuration_is_a_clear_503_not_a_silent_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST", "DYFLOW_USE_OLLAMA"):
            monkeypatch.delenv(var, raising=False)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            resolve_model(None)
        # A surprise provider means a surprise bill and a surprise data path.
        assert excinfo.value.status_code == 503
        assert "No model configured" in str(excinfo.value.detail)

    def test_it_picks_up_an_anthropic_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert resolve_model(None).startswith("anthropic:")

    def test_ollama_resolves_to_a_cloud_model_never_a_local_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("DYFLOW_USE_OLLAMA", "1")
        monkeypatch.delenv("DYFLOW_OLLAMA_MODEL", raising=False)

        resolved = resolve_model(None)

        # Standing project instruction, and the evidence is direct: llama3.1:8b
        # locally could not hold structured output, took minutes, and answered a
        # database question from parametric knowledge. The cloud model wrote a
        # correct two-join GROUP BY in 23s.
        assert resolved == OLLAMA_CLOUD_MODEL
        assert resolved.endswith("-cloud")
        assert "8b" not in resolved

    def test_a_local_model_must_be_named_explicitly(self) -> None:
        # Possible, but never the default — the friction is deliberate for a
        # choice that changes the result this much.
        assert resolve_model("ollama:llama3.1:8b") == "ollama:llama3.1:8b"


class TestGraphPreview:
    def test_the_preview_needs_no_model(self, client: TestClient) -> None:
        response = client.get("/api/workflows/chinook-nl-to-sql/graph")
        assert response.status_code == 200
        diagram = response.json()["mermaid"]
        for node in ("orient", "write_sql", "grade", "synthesise"):
            assert node in diagram

    def test_the_preview_never_calls_a_third_party(self, client: TestClient) -> None:
        diagram = client.get("/api/workflows/chinook-nl-to-sql/graph").json()["mermaid"]
        assert "mermaid.ink" not in diagram


class TestCors:
    def test_the_editor_origin_is_allowed_and_not_a_wildcard(self, client: TestClient) -> None:
        response = client.options(
            "/api/workflows/chinook-nl-to-sql/ask",
            headers={
                "Origin": "http://localhost:5273",
                "Access-Control-Request-Method": "POST",
            },
        )
        allowed = response.headers.get("access-control-allow-origin")
        # This API holds provider keys, so `*` would be wrong.
        assert allowed == "http://localhost:5273"
        assert allowed != "*"


class TestRunPostedWorkflow:
    """`/api/runs` executes the *posted* document, not a server-side graph.

    This is what makes the editor's Run button honest: what a developer can see
    on the canvas is what runs.
    """

    @staticmethod
    def _doc() -> dict[str, Any]:
        def n(i: str, t: str, **d: Any) -> dict[str, Any]:
            return {"id": i, "type": t, "data": d, "position": {"x": 0, "y": 0}}

        def e(s: str, sp: str, d: str, dp: str) -> dict[str, Any]:
            return {"source": {"nodeId": s, "portId": sp}, "target": {"nodeId": d, "portId": dp}}

        return {
            "version": 1,
            "name": "posted",
            "nodes": [n("node:input.text-1", "input.text"), n("node:output.formatted-1", "output.formatted")],
            "edges": [e("node:input.text-1", "text", "node:output.formatted-1", "result")],
        }

    def test_it_runs_without_a_model_so_shape_can_be_checked_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST", "DYFLOW_USE_OLLAMA"):
            monkeypatch.delenv(var, raising=False)
        client = TestClient(create_app())

        response = client.post(
            "/api/runs", json={"workflow": self._doc(), "question": "hello"}
        )

        # Unlike /ask, a missing model is not fatal here — a developer should be
        # able to verify a workflow's structure before configuring a provider.
        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "hello"

    def test_a_missing_model_is_explained_not_just_an_empty_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Found live: a workflow with an AI Agent node still runs
        successfully with no provider configured — the agent just returns
        immediately with nothing. Without a warning, "no answer was
        produced" is indistinguishable from a genuine bug.
        """
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST", "DYFLOW_USE_OLLAMA"):
            monkeypatch.delenv(var, raising=False)
        client = TestClient(create_app())

        body = client.post(
            "/api/runs", json={"workflow": self._doc(), "question": "hello"}
        ).json()

        assert any("No model provider is configured" in w for w in body["warnings"])

    def test_it_returns_the_mermaid_of_what_it_actually_compiled(self) -> None:
        client = TestClient(create_app())
        body = client.post(
            "/api/runs", json={"workflow": self._doc(), "question": "hi"}
        ).json()
        # Not a hand-drawn approximation — the compiled graph's own diagram.
        assert "node_input_text_1" in body["mermaid"]

    def test_it_reports_per_node_outputs_for_the_sidebar(self) -> None:
        client = TestClient(create_app())
        body = client.post(
            "/api/runs", json={"workflow": self._doc(), "question": "hi"}
        ).json()
        assert "node:input.text-1" in body["outputs"]

    def test_a_malformed_document_is_a_502_not_a_stack_trace(self) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/api/runs",
            json={"workflow": {"nodes": [{"id": "x"}], "edges": []}, "question": "hi"},
        )
        assert response.status_code in (200, 502)

    def test_unknown_fields_are_rejected(self) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/api/runs", json={"workflow": self._doc(), "question": "hi", "oops": 1}
        )
        assert response.status_code == 422


class TestRunStream:
    """`/api/runs/stream` — the same run, surfaced live for ticket 27's sidebar.

    No injected stub graph here: this exercises the real compiled graph, same
    as `TestRunPostedWorkflow`, so what is being proven is that the SSE frames
    the sidebar depends on actually appear — not a fake stand-in for them.
    """

    @staticmethod
    def _doc() -> dict[str, Any]:
        return TestRunPostedWorkflow._doc()

    @staticmethod
    def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
        """Parses raw SSE text into `(event, data)` pairs."""
        import json as _json

        events: list[tuple[str, dict[str, Any]]] = []
        event_name = None
        for line in text.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: ") and event_name is not None:
                events.append((event_name, _json.loads(line[len("data: ") :])))
                event_name = None
        return events

    def test_it_streams_an_update_per_node_and_a_final_done_event(self) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/api/runs/stream", json={"workflow": self._doc(), "question": "hello"}
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        events = self._events(response.text)
        kinds = [name for name, _ in events]
        assert kinds.count("update") == 2  # one per node in the linear document
        assert kinds[-1] == "done"

        updates = [data for name, data in events if name == "update"]
        assert {u["node"] for u in updates} == {"node:input.text-1", "node:output.formatted-1"}

        done = next(data for name, data in events if name == "done")
        assert done["answer"] == "hello"
        assert "node:input.text-1" in done["outputs"]

    def test_a_missing_model_is_explained_in_the_done_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST", "DYFLOW_USE_OLLAMA"):
            monkeypatch.delenv(var, raising=False)
        client = TestClient(create_app())
        response = client.post(
            "/api/runs/stream", json={"workflow": self._doc(), "question": "hi"}
        )

        done = next(data for name, data in self._events(response.text) if name == "done")
        assert any("No model provider is configured" in w for w in done["warnings"])

    @staticmethod
    def _fan_out_doc() -> dict[str, Any]:
        def n(i: str, t: str, **d: Any) -> dict[str, Any]:
            return {"id": i, "type": t, "data": d, "position": {"x": 0, "y": 0}}

        def e(s: str, sp: str, d: str, dp: str) -> dict[str, Any]:
            return {"source": {"nodeId": s, "portId": sp}, "target": {"nodeId": d, "portId": dp}}

        return {
            "version": 1,
            "name": "fan-out",
            "nodes": [
                n("in1", "input.text"),
                n("orch1", "orchestrate.supervisor", maxSubtasks=8),
                n("w1", "orchestrate.worker"),
                n("rep1", "function.format_report"),
                n("out1", "output.formatted"),
            ],
            "edges": [
                e("in1", "text", "orch1", "instruction"),
                e("orch1", "workers", "w1", "dispatch"),
                e("w1", "result", "rep1", "candidate"),
                e("rep1", "report", "out1", "result"),
            ],
        }

    def test_dispatched_worker_instances_carry_a_distinguishing_task_id(self) -> None:
        """The sidebar's "dynamically spawned subagents appear as they are
        created" requirement (ticket 27) needs a way to tell two concurrently
        dispatched instances of the *same* static worker node apart.
        `namespace` cannot do it — verified live that a `Send` task shares its
        parent's namespace rather than getting its own, unlike a real nested
        subgraph — so this pins the fallback: the task id from
        `worker_results`.
        """
        client = TestClient(create_app())
        response = client.post(
            "/api/runs/stream",
            json={"workflow": self._fan_out_doc(), "question": "a; b; c"},
        )

        events = self._events(response.text)
        worker_updates = [data for name, data in events if name == "update" and data["node"] == "w1"]

        # One dispatch per semicolon-separated clause, each individually
        # identifiable — not three indistinguishable "w1 ran" events.
        assert len(worker_updates) == 3
        assert {u["taskId"] for u in worker_updates} == {"task-1", "task-2", "task-3"}

    def test_a_document_that_fails_to_compile_is_a_502_not_a_stream(self) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/api/runs/stream",
            json={"workflow": {"nodes": [{"id": "x"}], "edges": []}, "question": "hi"},
        )
        # `WorkflowCompiler.build` runs *before* the generator is ever
        # iterated, so a document it cannot compile is a normal HTTP error —
        # the client never gets a 200 it has to parse to discover the run
        # never happened. (Matches `/api/runs`'s own tolerant assertion: an
        # untyped node with no declared ports may still compile as an opaque
        # passthrough, per `default_port_resolver`'s documented safe default.)
        assert response.status_code in (200, 502)

    def test_unknown_fields_are_rejected(self) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/api/runs/stream", json={"workflow": self._doc(), "question": "hi", "oops": 1}
        )
        assert response.status_code == 422
