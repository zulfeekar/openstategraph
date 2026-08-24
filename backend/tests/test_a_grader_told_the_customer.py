"""A customer is told when the answer they received is one the grader
rejected (`launch-readiness` 25).

The `loop` template's whole promise is *try again rather than publishing it*.
When trying again runs out, it publishes anyway. The CLI says so:

    warning: Grader "grader1" ran out of attempts and published an answer it
    had rejected. Its last reason: …

`POST /api/runs` at the default `audience: "customer"` had no field capable
of carrying that fact at all — `warnings` lives on `DeveloperChannelResponse`
only. `attempts: 3` proved the loop exhausted itself, but nothing said
whether the last attempt had passed or been forced through, so a rejected
answer reached a customer indistinguishable from one that passed first try.

The fix is `RunResponse.published_rejected: bool`, top-level and visible to
both audiences. The grader's *reason* can quote internals and stays on
`developer.warnings`; that the event happened must not be developer-only.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app


def _node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "position": {"x": 0, "y": 0}, "data": data}


def _edge(source: str, source_port: str, target: str, target_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": source, "portId": source_port},
        "target": {"nodeId": target, "portId": target_port},
    }


def loop_document(*, max_attempts: int = 1) -> dict[str, Any]:
    """in -> draft -[candidate]-> grader -[pass]-> out; grader -[revise]-> draft.

    A grader capped at one attempt, so a rejecting verdict on the very first
    candidate exhausts the budget immediately and force-passes it.
    """
    return {
        "version": 1,
        "name": "always-revises",
        "nodes": [
            _node("in1", "input.text"),
            _node("draft1", "agent.llm"),
            _node(
                "grader1",
                "route.grader",
                criteria="Never good enough.",
                maxAttempts=max_attempts,
            ),
            _node("out1", "output.formatted"),
        ],
        "edges": [
            _edge("in1", "text", "draft1", "prompt"),
            _edge("draft1", "result", "grader1", "candidate"),
            _edge("grader1", "pass", "out1", "result"),
            _edge("grader1", "revise", "draft1", "feedback"),
        ],
    }


def passing_document() -> dict[str, Any]:
    """The same shape, but the grader passes on the first candidate."""
    return loop_document(max_attempts=5)


def _client(monkeypatch: pytest.MonkeyPatch, model: Any) -> TestClient:
    from openstategraph import chat_model as chat_model_module

    monkeypatch.setattr(chat_model_module, "build_chat_model", lambda _name: model)
    return TestClient(create_app())


class TestTheCustomerLearnsTheLoopGaveUp:
    def test_a_customer_audience_run_carries_the_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from conftest import RespondingModel

        client = _client(monkeypatch, RespondingModel([], default="FAIL\nnever good enough"))
        response = client.post(
            "/api/runs",
            json={
                "workflow": loop_document(max_attempts=1),
                "question": "draft it",
                "audience": "customer",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["attempts"] == 1
        assert body["published_rejected"] is True
        # The developer-only reason must not leak onto a customer channel —
        # the whole design the ticket insists on.
        assert body["developer"] is None

    def test_a_first_try_pass_does_not_carry_the_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from conftest import RespondingModel

        client = _client(monkeypatch, RespondingModel([], default="PASS\nlooks fine"))
        response = client.post(
            "/api/runs",
            json={
                "workflow": passing_document(),
                "question": "draft it",
                "audience": "customer",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["published_rejected"] is False

    def test_the_developer_channel_still_carries_the_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from conftest import RespondingModel

        client = _client(monkeypatch, RespondingModel([], default="FAIL\nnever good enough"))
        response = client.post(
            "/api/runs",
            json={
                "workflow": loop_document(max_attempts=1),
                "question": "draft it",
                "audience": "developer",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["published_rejected"] is True
        assert any("ran out of attempts" in w for w in body["developer"]["warnings"])

    def test_the_streamed_terminal_frame_agrees(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from conftest import RespondingModel

        client = _client(monkeypatch, RespondingModel([], default="FAIL\nnever good enough"))
        response = client.post(
            "/api/runs/stream",
            json={
                "workflow": loop_document(max_attempts=1),
                "question": "draft it",
                "audience": "customer",
            },
        )
        assert response.status_code == 200, response.text
        events = [
            line.split("data: ", 1)[1]
            for line in response.text.split("\n\n")
            if line.startswith("event: done")
        ]
        import json as _json

        done = _json.loads(events[-1])
        assert done["publishedRejected"] is True
        assert "warnings" not in done
