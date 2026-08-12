"""`POST /api/runs` honours the thread it declares.

The defect: `RunRequest` has carried `thread_id`, `session_id`, `user_email`
and `workflow_slug` all along, and `run_workflow` built **no `configurable`
block at all** — so none of them reached the run. Observed live on
`chinook-assistant`: three sequential calls on one `thread_id`, and the
follow-up "How did you work that out?" classified `general_knowledge`; the
identical conversation over `/api/runs/stream` classified it `data_query`.

It is ticket 11's defect surviving on a second endpoint — *a client with no
history is always on turn one, so the router has no antecedent* — and a
declared field that reaches nothing is worse than an absent one, because it
looks supported.

Two things the fix needed beyond passing the block, both found by measuring
rather than reading:

1. **This endpoint compiled with no checkpointer.** `thread_id` in
   `configurable` would still have reached nothing: no saver, no persisted
   `messages`, no antecedent. Honouring the field means compiling the way the
   streaming endpoint already does.
2. **An interrupting document returned `200` with `answer: ""`.** Silently —
   the docstring said this endpoint "cannot pause for an approval", and the
   behaviour was a blank success rather than a refusal. The checkpointer is
   what makes `__interrupt__` visible, so the honest report becomes possible
   at the same time.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _echo_doc() -> dict[str, Any]:
    """A document that runs with no model: input straight to output."""
    return {
        "version": 2,
        "name": "Echo",
        "settings": {},
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {"prompt": ""}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }


def _approval_doc() -> dict[str, Any]:
    return {
        "version": 2,
        "name": "Needs a human",
        "settings": {},
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {"prompt": ""}},
            {"id": "ap1", "type": "human.approval", "data": {"message": "OK to send?"}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "ap1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "ap1", "portId": "approved"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


class TestTheThreadIsHonoured:
    def test_the_response_names_the_thread_the_run_used(self, client: TestClient) -> None:
        """A caller cannot continue a conversation it was never told the id of.

        The streaming endpoint learned this in ticket 11 — every terminal frame
        carries `threadId`, because the server mints the id and the client that
        most needs continuity is exactly the one that did not name a thread.
        """
        response = client.post("/api/runs", json={"workflow": _echo_doc(), "question": "hi"})
        assert response.status_code == 200
        assert response.json()["thread_id"]

    def test_a_supplied_thread_is_the_one_reported_back(self, client: TestClient) -> None:
        response = client.post(
            "/api/runs",
            json={"workflow": _echo_doc(), "question": "hi", "thread_id": "t-supplied"},
        )
        assert response.json()["thread_id"] == "t-supplied"

    def test_two_calls_on_one_thread_accumulate_the_conversation(
        self, client: TestClient
    ) -> None:
        """The defect itself, in the smallest form that shows it.

        Turn two must see turn one. Asserted through the checkpointer rather
        than through a model's answer: what broke was the *state*, and a test
        that needed a model to notice would be a test of the model.
        """
        first = client.post(
            "/api/runs",
            json={"workflow": _echo_doc(), "question": "first", "thread_id": "t-shared"},
        )
        assert first.status_code == 200
        client.post(
            "/api/runs",
            json={"workflow": _echo_doc(), "question": "second", "thread_id": "t-shared"},
        )

        thread = client.get("/api/threads/t-shared")
        assert thread.status_code == 200
        # Both questions are in the one thread's history.
        rendered = str(thread.json())
        assert "first" in rendered and "second" in rendered

    def test_two_calls_on_different_threads_do_not(self, client: TestClient) -> None:
        client.post(
            "/api/runs", json={"workflow": _echo_doc(), "question": "alpha", "thread_id": "t-a"}
        )
        client.post(
            "/api/runs", json={"workflow": _echo_doc(), "question": "beta", "thread_id": "t-b"}
        )
        assert "alpha" not in str(client.get("/api/threads/t-b").json())


class TestAnInterruptingRunIsRefused:
    """A blank 200 is the failure this whole ticket is about, one level down."""

    def test_it_reports_the_pause_instead_of_an_empty_answer(self, client: TestClient) -> None:
        response = client.post(
            "/api/runs", json={"workflow": _approval_doc(), "question": "hi"}
        )
        # Before: 200 with answer "". A caller could not tell "finished with
        # nothing to say" from "stopped halfway waiting for a human".
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "/api/runs/stream" in detail, "must name the endpoint that can pause"

    def test_a_document_that_does_not_pause_is_unaffected(self, client: TestClient) -> None:
        response = client.post("/api/runs", json={"workflow": _echo_doc(), "question": "hi"})
        assert response.status_code == 200


class TestTheDeclaredFieldsReachTheRun:
    def test_identity_and_slug_are_passed_not_dropped(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`session_id`, `user_email` and `workflow_slug` were dropped too.

        Not cosmetic: `workflow_slug` scopes the memory Store's namespace and
        `user_email` namespaces long-term memory, so a `save_memory` on this
        endpoint wrote to the wrong place — silently, like everything else here.
        """
        seen: dict[str, Any] = {}
        from openstategraph.compile import workflow_compiler

        original = workflow_compiler.WorkflowCompiler.build

        def spy(self: Any, *args: Any, **kwargs: Any) -> Any:
            graph = original(self, *args, **kwargs)
            invoke = graph.invoke

            def capture(state: Any, config: Any = None, **rest: Any) -> Any:
                seen["config"] = config
                return invoke(state, config, **rest)

            graph.invoke = capture  # type: ignore[method-assign]
            return graph

        monkeypatch.setattr(workflow_compiler.WorkflowCompiler, "build", spy)

        client.post(
            "/api/runs",
            json={
                "workflow": _echo_doc(),
                "question": "hi",
                "thread_id": "t-1",
                "session_id": "s-1",
                "user_email": "Me@Example.com",
                "workflow_slug": "echo",
            },
        )

        configurable = (seen.get("config") or {}).get("configurable") or {}
        assert configurable.get("thread_id") == "t-1"
        assert configurable.get("session_id") == "s-1"
        assert configurable.get("user_email") == "Me@Example.com"
        assert configurable.get("workflow_slug") == "echo"
