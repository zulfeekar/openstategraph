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

from dyflow.api.main import create_app, resolve_model


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
