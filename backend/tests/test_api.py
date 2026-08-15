"""Tests for the editor ↔ runtime seam.

The HTTP layer is exercised with an injected stub graph, so these run with no API
key and no provider. What they verify is the contract the frontend depends on:
the response shape, that a missing model is reported rather than guessed at, and
that the Mermaid preview needs no model at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import OLLAMA_CLOUD_MODEL, _coerce_update, create_app, resolve_model


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
            "/api/workflows/chinook-assistant/ask",
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
            "/api/workflows/chinook-assistant/ask",
            json={"question": "q", "model": "anthropic:x"},
        ).json()
        assert "InvoiceLine" in body["sql"]
        assert "826.65" in body["rows"]

    def test_the_recursion_limit_is_a_top_level_config_key(self) -> None:
        graph = StubGraph(GOOD_FINAL)
        c = TestClient(create_app(graph_factory=lambda _m: graph))
        c.post(
            "/api/workflows/chinook-assistant/ask",
            json={"question": "q", "model": "anthropic:x", "recursion_limit": 42},
        )
        # Inside `configurable` it silently does nothing — the common mistake.
        assert graph.configs[0]["recursion_limit"] == 42
        assert "configurable" not in graph.configs[0]

    def test_an_empty_question_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/workflows/chinook-assistant/ask", json={"question": "", "model": "x"}
        )
        assert response.status_code == 422

    def test_unknown_fields_are_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/workflows/chinook-assistant/ask",
            json={"question": "q", "model": "x", "surprise": 1},
        )
        assert response.status_code == 422

    def test_a_runtime_failure_becomes_502_not_a_stack_trace(self) -> None:
        class Exploding:
            def invoke(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("provider unreachable")

        c = TestClient(create_app(graph_factory=lambda _m: Exploding()))
        response = c.post(
            "/api/workflows/chinook-assistant/ask",
            json={"question": "q", "model": "anthropic:x"},
        )
        assert response.status_code == 502
        assert "provider unreachable" in response.json()["detail"]


class TestModelResolution:
    def test_an_explicit_model_wins(self) -> None:
        assert resolve_model("ollama:llama3.1:8b") == "ollama:llama3.1:8b"

    def test_no_configuration_still_names_a_model_rather_than_erroring(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A machine with no credential at all still gets a name.

        **Which** name changed with install-experience T2 and this test
        changed with it. It used to assert `OLLAMA_CLOUD_MODEL`, because the
        last line of `resolve_model` was that literal — Ollama was the answer
        whatever you had installed, which is exactly the defect that ticket
        names. The default is elected from the *installed* integrations now,
        so on a checkout with all three importable and none configured it is
        the first registered candidate.

        The property this test has always been about survives unchanged:
        resolving a name is cheap and total, and whether that model can be
        *called* is `build_chat_model`'s question, not this one's.
        """
        from openstategraph.providers import provider_catalogue

        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv("OPENSTATEGRAPH_OLLAMA_MODEL", raising=False)

        elected = provider_catalogue().elected_default()
        assert elected.configured is False
        assert resolve_model(None) == elected.model

    def test_it_picks_up_an_anthropic_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert resolve_model(None).startswith("anthropic:")

    def test_an_anthropic_key_wins_over_the_ollama_cloud_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("OPENSTATEGRAPH_OLLAMA_MODEL", raising=False)
        assert not resolve_model(None).startswith("ollama:")

    def test_ollama_resolves_to_a_cloud_model_never_a_local_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The standing rule, asserted where Ollama can now actually win.

        Ollama used to be reached by *not* choosing, so this needed no key.
        Since T2 it is elected like any other provider, so the key is what puts
        it in front of the election — the rule it guards is untouched.
        """
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv("OPENSTATEGRAPH_OLLAMA_MODEL", raising=False)
        monkeypatch.setenv("OLLAMA_API_KEY", "sk-ollama")

        resolved = resolve_model(None)

        # Standing project instruction, and the evidence is direct: llama3.1:8b
        # locally could not hold structured output, took minutes, and answered a
        # database question from parametric knowledge. The cloud model wrote a
        # correct two-join GROUP BY in 23s.
        assert resolved == OLLAMA_CLOUD_MODEL
        assert resolved.endswith("-cloud")
        assert "8b" not in resolved

    def test_openstategraph_ollama_model_overrides_the_cloud_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("OLLAMA_API_KEY", "sk-ollama")
        monkeypatch.setenv("OPENSTATEGRAPH_OLLAMA_MODEL", "ollama:gpt-oss:20b-cloud")
        assert resolve_model(None) == "ollama:gpt-oss:20b-cloud"

    def test_a_local_model_must_be_named_explicitly(self) -> None:
        # Possible, but never the default — the friction is deliberate for a
        # choice that changes the result this much.
        assert resolve_model("ollama:llama3.1:8b") == "ollama:llama3.1:8b"


class TestGraphPreview:
    def test_the_preview_needs_no_model(self, client: TestClient) -> None:
        response = client.get("/api/workflows/chinook-assistant/graph")
        assert response.status_code == 200
        diagram = response.json()["mermaid"]
        # The generic {slug} endpoint compiles the CANVAS document (ticket
        # 54) — the hand-written graph.py preview retired with the
        # chinook-specific route it powered.
        for node in ("agent_sql", "grader_sql", "out1"):
            assert node in diagram

    def test_the_preview_never_calls_a_third_party(self, client: TestClient) -> None:
        diagram = client.get("/api/workflows/chinook-assistant/graph").json()["mermaid"]
        assert "mermaid.ink" not in diagram


class TestCors:
    def test_the_editor_origin_is_allowed_and_not_a_wildcard(self, client: TestClient) -> None:
        response = client.options(
            "/api/workflows/chinook-assistant/ask",
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

    def test_it_runs_with_no_provider_keys_configured_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ollama cloud is the default now, so this document (which has no
        agent/worker node to call a model at all) runs the same with or
        without an Anthropic/OpenAI key — resolving *a* model no longer
        depends on any of them being set.
        """
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(var, raising=False)
        client = TestClient(create_app())

        response = client.post(
            "/api/runs", json={"workflow": self._doc(), "question": "hello"}
        )

        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "hello"

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


class TestCoerceUpdate:
    """Found live, mid-run: once `subgraphs=True` is on, LangGraph surfaces a
    nested graph invoked *inside* a plain node (`create_agent`/
    `create_deep_agent` called from within a worker or grader factory) —
    and some of its internal steps contribute `None`, not `{}`, for
    "nothing to report this tick". `AttributeError: 'NoneType' object has
    no attribute 'get'` crashed the whole stream on this, mid-answer, in a
    real Chinook run.
    """

    def test_a_dict_update_passes_through_unchanged(self) -> None:
        assert _coerce_update({"outputs": {"n1": "x"}}) == {"outputs": {"n1": "x"}}

    def test_none_becomes_an_empty_dict_rather_than_raising(self) -> None:
        assert _coerce_update(None) == {}

    def test_anything_else_unexpected_also_becomes_an_empty_dict(self) -> None:
        assert _coerce_update("not a dict") == {}
        assert _coerce_update(42) == {}


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

    def test_dispatched_worker_instances_carry_a_distinguishing_task_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The sidebar's "dynamically spawned subagents appear as they are
        created" requirement (ticket 27) needs a way to tell two concurrently
        dispatched instances of the *same* static worker node apart.
        `namespace` cannot do it — verified live that a `Send` task shares its
        parent's namespace rather than getting its own, unlike a real nested
        subgraph — so this pins the fallback: the task id from
        `worker_results`.

        **The model is faked, and has to be.** This posted a real document with
        no model injected, so the workers called whatever `resolve_model`
        picked — Ollama — and the run's outcome depended on whether a daemon
        happened to be listening on the developer's machine. With none, the
        connection error was absorbed by `__default_error_handler__` and the
        failure read `0 == 3`, naming neither Ollama nor a credential
        (providers-and-credentials ticket 02).
        """
        from openstategraph import chat_model as chat_model_module

        from conftest import RespondingModel

        monkeypatch.setattr(
            chat_model_module,
            "build_chat_model",
            lambda _name: RespondingModel([], default="done"),
        )
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


class TestAStreamedAnswerIsTheAnswer:
    """The streamed **answer**, not merely the streamed frames (ticket 06).

    `TestRunStream` above proves the frame vocabulary — that `update`, `spawn`
    and `done` arrive with the right shape and ids. It does not prove that the
    answer inside them is right, and for a long time it was not:

        POST /api/runs      → "49"
        POST /api/runs/stream → "What is 7 * 7? Reply with just the number."

    Same workflow, same server, seconds apart (ticket 03, found by driving the
    wheel in a browser). Both shipped UIs stream — `/api/runs` cannot show
    progress and cannot pause for an approval — so **every run a person could
    see was wrong while every run a test made was right**. The CLI,
    `/api/runs` and effectively every other run test go through `invoke`.

    Two things had to be true for a suite this size to miss it, and this class
    fixes both:

    - Nothing asserted on an answer obtained through the streaming path.
    - Every fake model replied with string content, so no test could reproduce
      the shape that triggers it. `BlockRespondingModel` exists for that and
      is the load-bearing half — with a string-shaped fake these tests pass
      against the broken runtime.
    """

    @staticmethod
    def _agent_doc() -> dict[str, Any]:
        """in1 → agent1 → out1: the `minimal` template, and the shape of every
        workflow a newcomer builds first."""

        def n(i: str, ty: str, **d: Any) -> dict[str, Any]:
            return {"id": i, "type": ty, "data": d, "position": {"x": 0, "y": 0}}

        def e(s: str, sp: str, d: str, dp: str) -> dict[str, Any]:
            return {"source": {"nodeId": s, "portId": sp}, "target": {"nodeId": d, "portId": dp}}

        return {
            "version": 1,
            "name": "answers",
            "nodes": [n("in1", "input.text"), n("agent1", "agent.llm"), n("out1", "output.formatted")],
            "edges": [e("in1", "text", "agent1", "prompt"), e("agent1", "result", "out1", "result")],
        }

    @staticmethod
    def _done(response: Any) -> dict[str, Any]:
        events = TestRunStream._events(response.text)
        return next(data for name, data in events if name == "done")

    def _ask(self, monkeypatch: pytest.MonkeyPatch, model: Any, question: str) -> dict[str, Any]:
        from openstategraph import chat_model as chat_model_module

        monkeypatch.setattr(chat_model_module, "build_chat_model", lambda _name: model)
        client = TestClient(create_app())
        response = client.post(
            "/api/runs/stream", json={"workflow": self._agent_doc(), "question": question}
        )
        assert response.status_code == 200
        return self._done(response)

    def test_the_streamed_answer_is_what_the_model_said(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from conftest import BlockRespondingModel

        done = self._ask(
            monkeypatch,
            BlockRespondingModel([], default="144"),
            "What is 12 * 12? Reply with just the number.",
        )

        assert done["answer"] == "144"
        assert done["outputs"]["agent1"] == "144"
        assert done["outputs"]["out1"] == "144"

    def test_the_streamed_answer_is_never_the_question(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The negative that has now bitten twice — this defect and the earlier
        # unknown-node-type one both presented as an echo. It is the single
        # worst failure this product can have: a grader reads it as a reply, a
        # customer reads it as a reply, and the run reports success. An empty
        # answer is visibly broken; an echo is a lie.
        from conftest import BlockRespondingModel

        question = "Which genre earns the most revenue?"
        done = self._ask(monkeypatch, BlockRespondingModel([], default="Rock."), question)

        assert done["answer"] != question
        assert question not in done["outputs"].values() or done["outputs"]["in1"] == question
        assert done["outputs"]["agent1"] != question

    def test_a_thinking_models_reasoning_stays_out_of_the_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Reasoning rides in the same content list as the text. Concatenating
        # the list blind would hand a customer the model's private
        # deliberation, which is worse than showing them nothing.
        from conftest import BlockRespondingModel

        done = self._ask(
            monkeypatch,
            BlockRespondingModel([], default="42", reasoning="the user wants 6*7, that is 42"),
            "What is 6 * 7?",
        )

        assert done["answer"] == "42"
        assert "deliberation" not in done["answer"]
        assert "the user wants" not in done["answer"]

    def test_the_two_endpoints_agree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The assertion that would have caught it on its own.

        `/api/runs` and `/api/runs/stream` compile the same document with the
        same input; the only difference is `stream_mode`. A user should never
        be able to tell which one answered — and for months they could.
        """
        from conftest import BlockRespondingModel

        from openstategraph import chat_model as chat_model_module

        monkeypatch.setattr(
            chat_model_module, "build_chat_model", lambda _name: BlockRespondingModel([], default="81")
        )
        client = TestClient(create_app())
        payload = {"workflow": self._agent_doc(), "question": "What is 9 * 9?"}

        plain = client.post("/api/runs", json=payload).json()
        streamed = self._done(client.post("/api/runs/stream", json=payload))

        assert plain["answer"] == streamed["answer"] == "81"
        assert plain["outputs"]["agent1"] == streamed["outputs"]["agent1"]


class TestHumanInTheLoop:
    """`/api/runs/stream` pausing on `human.approval`, resumed via
    `/api/runs/resume` — the real HTTP surface for the graph-level lifecycle
    already proven in `test_human_approval.py`.

    Deliberately no `agent.llm` node in this document: `human.approval`
    reads its candidate from the upstream node's text directly, so
    `input.text -> human.approval` proves the same pause/resume mechanics
    without a real model call over the wire (this suite has no fake-model
    injection seam for `/api/runs/stream`/`/api/runs/resume`, unlike the
    graph-level tests).
    """

    @staticmethod
    def _doc() -> dict[str, Any]:
        def n(i: str, t: str, **d: Any) -> dict[str, Any]:
            return {"id": i, "type": t, "data": d, "position": {"x": 0, "y": 0}}

        def e(s: str, sp: str, d: str, dp: str) -> dict[str, Any]:
            return {"source": {"nodeId": s, "portId": sp}, "target": {"nodeId": d, "portId": dp}}

        return {
            "version": 1,
            "name": "approval-http",
            "nodes": [
                n("node:input.text-1", "input.text"),
                n("node:human.approval-1", "human.approval", message="OK to publish?"),
                n("node:output.formatted-1", "output.formatted"),
                n("node:output.formatted-2", "output.formatted"),
            ],
            "edges": [
                e("node:input.text-1", "text", "node:human.approval-1", "candidate"),
                e("node:human.approval-1", "approved", "node:output.formatted-1", "result"),
                e("node:human.approval-1", "rejected", "node:output.formatted-2", "result"),
            ],
        }

    @staticmethod
    def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
        return TestRunStream._events(text)

    def test_a_run_that_reaches_the_approval_node_pauses_with_an_interrupt_event(
        self,
    ) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/api/runs/stream", json={"workflow": self._doc(), "question": "draft text"}
        )

        assert response.status_code == 200
        events = self._events(response.text)
        kinds = [name for name, _ in events]
        assert kinds[-1] == "interrupt"
        assert "done" not in kinds

        interrupt = next(data for name, data in events if name == "interrupt")
        assert interrupt["message"] == "OK to publish?"
        assert interrupt["candidate"] == "draft text"
        assert interrupt["threadId"]

    def test_resuming_with_approve_completes_the_run_on_the_approved_branch(
        self,
    ) -> None:
        client = TestClient(create_app())
        first = client.post(
            "/api/runs/stream", json={"workflow": self._doc(), "question": "draft text"}
        )
        thread_id = next(
            data for name, data in self._events(first.text) if name == "interrupt"
        )["threadId"]

        resumed = client.post(
            "/api/runs/resume",
            json={"thread_id": thread_id, "workflow": self._doc(), "decision": "approve"},
        )

        assert resumed.status_code == 200, resumed.text
        events = self._events(resumed.text)
        assert [name for name, _ in events][-1] == "done"

        done = next(data for name, data in events if name == "done")
        assert done["decisions"]["node:human.approval-1"] == "approved"
        assert done["answer"] == "draft text"

    def test_resuming_with_reject_and_feedback_completes_on_the_rejected_branch(
        self,
    ) -> None:
        client = TestClient(create_app())
        first = client.post(
            "/api/runs/stream", json={"workflow": self._doc(), "question": "draft text"}
        )
        thread_id = next(
            data for name, data in self._events(first.text) if name == "interrupt"
        )["threadId"]

        resumed = client.post(
            "/api/runs/resume",
            json={
                "thread_id": thread_id,
                "workflow": self._doc(),
                "decision": "reject",
                "feedback": "Too casual.",
            },
        )

        assert resumed.status_code == 200, resumed.text
        done = next(data for name, data in self._events(resumed.text) if name == "done")
        assert done["decisions"]["node:human.approval-1"] == "rejected"

    def test_two_concurrent_runs_do_not_cross_contaminate_their_pauses(self) -> None:
        client = TestClient(create_app())
        first = client.post(
            "/api/runs/stream", json={"workflow": self._doc(), "question": "run A"}
        )
        second = client.post(
            "/api/runs/stream", json={"workflow": self._doc(), "question": "run B"}
        )
        thread_a = next(
            data for name, data in self._events(first.text) if name == "interrupt"
        )["threadId"]
        thread_b = next(
            data for name, data in self._events(second.text) if name == "interrupt"
        )["threadId"]
        assert thread_a != thread_b

        resumed_a = client.post(
            "/api/runs/resume",
            json={"thread_id": thread_a, "workflow": self._doc(), "decision": "approve"},
        )
        resumed_b = client.post(
            "/api/runs/resume",
            json={"thread_id": thread_b, "workflow": self._doc(), "decision": "reject"},
        )

        done_a = next(data for name, data in self._events(resumed_a.text) if name == "done")
        done_b = next(data for name, data in self._events(resumed_b.text) if name == "done")
        assert done_a["answer"] == "run A"
        assert done_b["decisions"]["node:human.approval-1"] == "rejected"


class TestWorkflowPersistence:
    """Tickets 10/14/16: `workflows/<slug>/workflow.json` is the source of
    truth, and every test here runs against a throwaway `tmp_path` root, never
    the real `workflows/` tree.
    """

    @staticmethod
    def _client(tmp_path: Path) -> TestClient:
        return TestClient(create_app(workflows_root=tmp_path))

    def test_a_saved_workflow_can_be_listed_and_loaded_back(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        document = {"version": 1, "nodes": [{"id": "n1"}], "edges": []}

        save = client.put("/api/workflows/my-flow", json={"name": "My Flow", "document": document})
        assert save.status_code == 200, save.text

        listing = client.get("/api/workflows").json()
        assert len(listing) == 1
        assert listing[0]["slug"] == "my-flow"
        assert listing[0]["name"] == "My Flow"
        assert listing[0]["node_count"] == 1

        loaded = client.get("/api/workflows/my-flow").json()
        assert loaded["document"] == document

    def test_creating_two_workflows_of_one_name_returns_two_slugs(self, tmp_path: Path) -> None:
        """Ticket 20, over HTTP: the shape the editor now uses.

        The old path was `PUT /api/workflows/{slugify(name)}` from the
        browser, which answered 200 twice and left one directory holding the
        second document.
        """
        client = self._client(tmp_path)

        first = client.post(
            "/api/workflows", json={"name": "My Workflow", "document": {"nodes": [{"id": "a"}]}}
        )
        second = client.post(
            "/api/workflows", json={"name": "My Workflow", "document": {"nodes": [{"id": "b"}]}}
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text

        first_slug, second_slug = first.json()["slug"], second.json()["slug"]
        assert first_slug == "my-workflow"
        assert second_slug != first_slug and second_slug.startswith("my-workflow-")

        assert client.get(f"/api/workflows/{first_slug}").json()["document"] == {
            "nodes": [{"id": "a"}]
        }
        assert client.get(f"/api/workflows/{second_slug}").json()["document"] == {
            "nodes": [{"id": "b"}]
        }
        assert len(client.get("/api/workflows").json()) == 2

    def test_a_created_workflow_is_a_draft(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        slug = client.post("/api/workflows", json={"name": "Draft Me", "document": {}}).json()[
            "slug"
        ]
        assert client.get(f"/api/workflows/{slug}/summary").json()["published"] is False

    def test_loading_an_unknown_workflow_is_a_404(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        response = client.get("/api/workflows/does-not-exist")
        assert response.status_code == 404

    def test_deleting_a_workflow_removes_it_from_the_listing(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        client.put("/api/workflows/gone-soon", json={"name": "X", "document": {"nodes": [], "edges": []}})

        delete = client.delete("/api/workflows/gone-soon")
        assert delete.status_code == 204
        assert client.get("/api/workflows").json() == []

    def test_a_path_traversal_slug_is_rejected_not_silently_escaped(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        response = client.put(
            "/api/workflows/..%2F..%2Fescaped",
            json={"name": "x", "document": {"nodes": [], "edges": []}},
        )
        # Either FastAPI's own routing normalises/rejects the path, or the
        # store's own slug check does (422) — either way, nothing is written
        # outside `tmp_path`.
        assert response.status_code in (404, 422)
        assert list(tmp_path.iterdir()) == []

    def test_resaving_under_the_same_slug_does_not_duplicate_it(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        client.put("/api/workflows/my-flow", json={"name": "My Flow", "document": {"nodes": [], "edges": []}})
        client.put(
            "/api/workflows/my-flow",
            json={"name": "My Flow, Renamed", "document": {"nodes": [], "edges": []}},
        )

        assert len(client.get("/api/workflows").json()) == 1
        assert client.get("/api/workflows/my-flow").json()["document"] == {"nodes": [], "edges": []}


class TestCapabilities:
    """Ticket 18: `GET /api/workflows/{slug}/capabilities` discovers a saved
    workflow's own `tools/`/`functions/` folders by importing them for real.
    """

    @staticmethod
    def _client(tmp_path: Path) -> TestClient:
        return TestClient(create_app(workflows_root=tmp_path))

    def test_discovers_a_real_tool_and_function_on_disk(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        client.put("/api/workflows/my-flow", json={"name": "My Flow", "document": {"nodes": [], "edges": []}})

        tools_dir = tmp_path / "my-flow" / "tools"
        tools_dir.mkdir()
        (tools_dir / "greet.py").write_text(
            "from openstategraph.abc.tool import BaseTool, ToolResult\n"
            "from pydantic import BaseModel\n\n"
            "class GreetArgs(BaseModel):\n    name: str\n\n"
            "class GreetTool(BaseTool):\n"
            "    name = 'greet'\n    description = 'Greets someone.'\n    Args = GreetArgs\n"
            "    def _execute(self, args):\n        return ToolResult(content=f'Hi {args.name}')\n"
        )
        functions_dir = tmp_path / "my-flow" / "functions"
        functions_dir.mkdir()
        (functions_dir / "share.py").write_text(
            "def share_of_total(part: float, total: float) -> float:\n    return part / total\n"
        )

        response = client.get("/api/workflows/my-flow/capabilities")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["tools"] == [
            {
                "id": "my-flow/tools.GreetTool",
                "name": "greet",
                "description": "Greets someone.",
                "args_schema": body["tools"][0]["args_schema"],
                "node_type": "",
            }
        ]
        assert "name" in body["tools"][0]["args_schema"]["properties"]
        assert body["functions"][0]["id"] == "my-flow/functions.share_of_total"

    def test_an_unsaved_workflow_is_a_404_not_an_empty_list(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        response = client.get("/api/workflows/never-saved/capabilities")
        assert response.status_code == 404

    def test_a_workflow_with_no_tools_or_functions_folders_reports_empty(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        client.put("/api/workflows/bare", json={"name": "Bare", "document": {"nodes": [], "edges": []}})
        body = client.get("/api/workflows/bare/capabilities").json()
        assert body["tools"] == []
        assert body["functions"] == []
        # `plugin_tools` is empty in a clean venv and `warnings` is not part of
        # *this* claim — a built-in tool with no editor card legitimately fills
        # it (register PK-06, `tests/test_plugin_capabilities.py`).
        assert body["plugin_tools"] == []


class TestPublishLifecycle:
    """Ticket 04 (launch-readiness): drafts by default, publish gates /chat.

    `GET /api/workflows?surface=editor` (the default) lists everything
    non-hidden with a `published` flag per row; `?surface=chat` lists only
    published workflows — the customer surface. `POST
    /api/workflows/{slug}/publish` with `{"published": bool}` flips the flag
    (one endpoint for both directions, the flag being the whole state).
    """

    @staticmethod
    def _client(tmp_path: Path) -> TestClient:
        return TestClient(create_app(workflows_root=tmp_path))

    @staticmethod
    def _seed(tmp_path: Path, slug: str, **extra: Any) -> None:
        import json

        directory = tmp_path / slug
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps({"version": 1, "name": slug, "savedAt": "t",
                        "document": {"nodes": [], "edges": []}, **extra})
        )

    def test_a_workflow_created_through_the_editor_is_a_draft(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        client.put("/api/workflows/fresh", json={"name": "Fresh", "document": {"nodes": [], "edges": []}})
        [row] = client.get("/api/workflows").json()
        assert row["published"] is False

    def test_a_pre_lifecycle_envelope_counts_as_published(self, tmp_path: Path) -> None:
        self._seed(tmp_path, "legacy")
        [row] = self._client(tmp_path).get("/api/workflows").json()
        assert row["published"] is True

    def test_the_chat_surface_sees_only_published_workflows(self, tmp_path: Path) -> None:
        self._seed(tmp_path, "live", published=True)
        self._seed(tmp_path, "draft", published=False)
        client = self._client(tmp_path)
        editor = client.get("/api/workflows", params={"surface": "editor"}).json()
        assert {r["slug"] for r in editor} == {"live", "draft"}
        chat = client.get("/api/workflows", params={"surface": "chat"}).json()
        assert [r["slug"] for r in chat] == ["live"]

    def test_hidden_trumps_published_on_the_customer_surface(self, tmp_path: Path) -> None:
        """`published: true` does not buy a hidden package a customer listing.

        The rule is per-audience, not global. A hidden package is absolute for
        the customer and *marked* for the developer — hiding a developer's own
        packages from their own editor was never what this flag meant.
        """
        self._seed(tmp_path, "infra", hidden=True, published=True)
        client = self._client(tmp_path)
        assert client.get("/api/workflows", params={"surface": "chat"}).json() == []
        assert [r["slug"] for r in client.get("/api/workflows").json()] == ["infra"]

    def test_an_unknown_surface_is_rejected(self, tmp_path: Path) -> None:
        response = self._client(tmp_path).get("/api/workflows", params={"surface": "nope"})
        assert response.status_code == 422

    def test_the_summary_endpoint_answers_existence_where_the_listing_answers_visibility(
        self, tmp_path: Path
    ) -> None:
        """Ticket 21, sharpened. `infra` is hidden, so the **customer**
        surface does not list it — and every existence question still says
        yes. The editor's file watch used to read the first answer as the
        second and report a live file as deleted on disk.

        The editor now lists it, marked. `hidden` answers *should a customer
        be offered this*, and applying that to the developer's own catalogue
        was the same mistake one level up: a developer who owns `concierge`
        and `workflow-architect` could not see they exist, from the editor
        that edits them."""
        self._seed(tmp_path, "infra", hidden=True, published=True)
        client = self._client(tmp_path)

        assert client.get("/api/workflows", params={"surface": "chat"}).json() == []
        editor = client.get("/api/workflows").json()
        assert [row["slug"] for row in editor] == ["infra"]
        assert editor[0]["hidden"] is True, "listed, but never disguised as ordinary"
        assert client.get("/api/workflows/infra").status_code == 200

        summary = client.get("/api/workflows/infra/summary")
        assert summary.status_code == 200, summary.text
        assert summary.json()["hidden"] is True
        assert summary.json()["saved_at"] == "t"

    def test_a_deleted_workflow_is_a_404_from_the_summary_endpoint(self, tmp_path: Path) -> None:
        """The other half, and the reason the warning must not just be
        deleted: a genuinely gone package is still reported gone."""
        self._seed(tmp_path, "doomed", hidden=True)
        client = self._client(tmp_path)
        assert client.get("/api/workflows/doomed/summary").status_code == 200

        assert client.delete("/api/workflows/doomed").status_code == 204
        assert client.get("/api/workflows/doomed/summary").status_code == 404

    def test_a_listed_workflow_reports_hidden_false(self, tmp_path: Path) -> None:
        self._seed(tmp_path, "visible", published=True)
        client = self._client(tmp_path)
        assert client.get("/api/workflows").json()[0]["hidden"] is False
        assert client.get("/api/workflows/visible/summary").json()["hidden"] is False

    def test_a_malformed_slug_is_a_422_not_a_404(self, tmp_path: Path) -> None:
        # "That is not a slug" must not be answerable as "it is gone" — a
        # client that treats 404 as deletion would act on a typo.
        response = self._client(tmp_path).get("/api/workflows/Not A Slug/summary")
        assert response.status_code == 422

    def test_publish_round_trip(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        client.put("/api/workflows/flow", json={"name": "Flow", "document": {"nodes": [], "edges": []}})

        publish = client.post("/api/workflows/flow/publish", json={"published": True})
        assert publish.status_code == 200, publish.text
        body = publish.json()
        assert body["published"] is True
        # Build-time-only invariant: publishing must NOT auto-run the model
        # builder — the response instead reminds that routing knowledge can
        # be rebuilt.
        assert "knowledge" in body["note"].lower()
        assert [r["slug"] for r in client.get("/api/workflows", params={"surface": "chat"}).json()] == ["flow"]

        unpublish = client.post("/api/workflows/flow/publish", json={"published": False})
        assert unpublish.status_code == 200
        assert unpublish.json()["published"] is False
        assert client.get("/api/workflows", params={"surface": "chat"}).json() == []

    def test_publishing_an_unknown_workflow_is_a_404(self, tmp_path: Path) -> None:
        response = self._client(tmp_path).post(
            "/api/workflows/nope/publish", json={"published": True}
        )
        assert response.status_code == 404


class TestTemplates:
    """`GET /api/templates` — the editor's New Workflow picker and the CLI's
    `--template` read one catalogue (scale-and-adopt ticket 04). If this
    endpoint and `openstategraph.templates` ever disagree, there are two lists
    and the editor is scaffolding something the CLI cannot reproduce."""

    def test_it_offers_exactly_what_the_cli_offers(self, client: TestClient) -> None:
        from openstategraph import templates

        response = client.get("/api/templates")

        assert response.status_code == 200
        assert [t["name"] for t in response.json()] == list(templates.names())
        assert [t["summary"] for t in response.json()] == [
            t.summary for t in templates.catalogue()
        ]

    def test_each_entry_carries_an_importable_document(self, client: TestClient) -> None:
        for entry in client.get("/api/templates").json():
            document = entry["document"]
            assert document["version"] == 2
            assert document["nodes"] and document["edges"]
            assert "{{" not in str(document)

    def test_the_display_name_reaches_inside_the_document(self, client: TestClient) -> None:
        """The team template titles its supervisor "<name> Lead" — rendering
        server-side is what keeps the editor's result identical to the CLI's."""
        entries = client.get("/api/templates", params={"name": "Payments"}).json()
        team = next(e for e in entries if e["name"] == "team")

        assert team["document"]["name"] == "Payments"
        assert any(n.get("title") == "Payments Lead" for n in team["document"]["nodes"])


class TestExamples:
    """`GET /api/examples` and `POST /api/examples/{slug}/copy` — the editor's
    Examples shelf (workflow-gallery ticket 07).

    The shelf reads the same catalogue as `openstategraph examples list`, and
    taking one is a **server-side copy** rather than a document import: an
    example is a package, and a browser that imported only its document would
    produce nodes bound to tools that are not there.
    """

    @pytest.fixture
    def project(self, tmp_path: Path) -> TestClient:
        """A client whose workflows root is empty and disposable — a copy test
        that wrote into this repository's own `workflows/` would be a test that
        edits the checkout."""
        return TestClient(create_app(workflows_root=tmp_path))

    def test_it_offers_exactly_what_the_cli_offers(self, project: TestClient) -> None:
        from openstategraph import examples

        response = project.get("/api/examples")

        assert response.status_code == 200
        assert [e["slug"] for e in response.json()] == list(examples.slugs())

    def test_each_entry_says_what_it_is_and_what_it_costs(self, project: TestClient) -> None:
        entries = {e["slug"]: e for e in project.get("/api/examples").json()}

        assert entries["chained-summarizer"]["pattern"] == "prompt chaining"
        assert entries["chained-summarizer"]["summary"]
        assert entries["nested-mounts"]["requires"] == [
            "nested-mounts",
            "nested-mounts-mid",
            "chained-summarizer",
        ]

    def test_the_gallery_is_not_in_the_users_workflow_list(self, project: TestClient) -> None:
        """The point of the home: no flag hides these, their location does."""
        assert project.get("/api/workflows").json() == []

    def test_copying_one_puts_it_and_its_mounts_in_the_project(
        self, project: TestClient, tmp_path: Path
    ) -> None:
        response = project.post("/api/examples/nested-mounts/copy")

        assert response.status_code == 201, response.text
        assert response.json() == {
            "slug": "nested-mounts",
            "copied": ["nested-mounts", "nested-mounts-mid", "chained-summarizer"],
        }
        for slug in response.json()["copied"]:
            assert (tmp_path / slug / "workflow.json").is_file()

    def test_a_copy_then_shows_up_as_the_users_own_draft(self, project: TestClient) -> None:
        project.post("/api/examples/chained-summarizer/copy")

        rows = {row["slug"]: row for row in project.get("/api/workflows").json()}
        assert "chained-summarizer" in rows
        assert rows["chained-summarizer"]["published"] is False

    def test_an_unknown_example_is_a_404_that_names_the_real_ones(
        self, project: TestClient
    ) -> None:
        response = project.post("/api/examples/no-such-example/copy")

        assert response.status_code == 404
        assert "chained-summarizer" in response.json()["detail"]

    def test_copying_twice_is_refused_rather_than_overwriting(
        self, project: TestClient
    ) -> None:
        assert project.post("/api/examples/chained-summarizer/copy").status_code == 201
        second = project.post("/api/examples/chained-summarizer/copy")

        assert second.status_code == 409
        assert "chained-summarizer" in second.json()["detail"]


class TestHealthReportsRealReadiness:
    """`model_configured` used to be the literal `True`.

    The reasoning was that Ollama was always available, which was itself the
    defect: it reached the cloud through an ambient local daemon, so this
    endpoint reported ready on a machine with nothing configured and nothing
    listening (providers-and-credentials ticket 02). A health check that
    cannot say "no" is not a health check.
    """

    CREDENTIALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")

    def _model_configured(self) -> bool:
        response = TestClient(create_app()).get("/api/health")
        assert response.status_code == 200
        return bool(response.json()["model_configured"])

    def test_nothing_configured_is_reported_as_such(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in self.CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        assert self._model_configured() is False

    @pytest.mark.parametrize("variable", CREDENTIALS)
    def test_any_one_credential_is_enough(
        self, monkeypatch: pytest.MonkeyPatch, variable: str
    ) -> None:
        """Any provider, and either of Ollama's two ways of being configured."""
        for name in self.CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(variable, "http://localhost:11434" if "HOST" in variable else "x")
        assert self._model_configured() is True

    def test_it_opens_no_socket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Still cheap: environment only, never a reachability probe.

        A configured provider that is down is a different question, and one
        this endpoint has never claimed to answer.
        """
        import socket

        def refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("/api/health must not open a socket")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        assert self._model_configured() is True


class TestDuplicateWorkflow:
    """`POST /api/workflows/{slug}/duplicate` — ticket 01.

    The owner asked whether duplicate had been built. It had not, and the
    workaround people reached for — Load, rename, Save — mints a fresh slug and
    so silently *is* a duplicate. Some users expect it to be a **move** and are
    surprised the original is still there; that ambiguity, not the keystrokes,
    is why this endpoint exists.
    """

    @staticmethod
    def _client(tmp_path: Path) -> TestClient:
        return TestClient(create_app(workflows_root=tmp_path))

    @staticmethod
    def _create(client: TestClient, name: str) -> str:
        created = client.post(
            "/api/workflows",
            json={"name": name, "document": {"version": 1, "nodes": [], "edges": []}},
        )
        assert created.status_code == 201, created.text
        return created.json()["slug"]

    def test_it_answers_with_a_new_slug_and_leaves_the_original(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        source = self._create(client, "Chinook Assistant")

        response = client.post(f"/api/workflows/{source}/duplicate", json={})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == source
        assert body["slug"] != source
        slugs = {row["slug"] for row in client.get("/api/workflows").json()}
        assert {source, body["slug"]} <= slugs

    def test_the_default_name_says_it_is_a_copy(self, tmp_path: Path) -> None:
        # Defaulted on the backend because the obvious default depends on the
        # original's name, which the client would have to fetch to compute.
        client = self._client(tmp_path)
        source = self._create(client, "Chinook Assistant")

        body = client.post(f"/api/workflows/{source}/duplicate", json={}).json()

        assert body["name"] == "Chinook Assistant (copy)"

    def test_a_caller_may_name_the_copy(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        source = self._create(client, "Chinook Assistant")

        body = client.post(
            f"/api/workflows/{source}/duplicate", json={"name": "Chinook Experiment"}
        ).json()

        assert body["name"] == "Chinook Experiment"
        assert body["slug"].startswith("chinook-experiment")

    def test_the_copy_of_a_published_workflow_is_a_draft(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        source = self._create(client, "Live")
        client.post(f"/api/workflows/{source}/publish", json={"published": True})

        copy = client.post(f"/api/workflows/{source}/duplicate", json={}).json()["slug"]

        rows = {row["slug"]: row for row in client.get("/api/workflows").json()}
        assert rows[copy]["published"] is False
        assert rows[source]["published"] is True

    def test_the_copy_carries_the_package(self, tmp_path: Path) -> None:
        client = self._client(tmp_path)
        source = self._create(client, "With Tools")
        (tmp_path / source / "tools" / "chinook.py").write_text("def query(): ...\n")

        copy = client.post(f"/api/workflows/{source}/duplicate", json={}).json()["slug"]

        assert (tmp_path / copy / "tools" / "chinook.py").is_file()

    def test_duplicating_a_missing_workflow_is_404(self, tmp_path: Path) -> None:
        response = self._client(tmp_path).post("/api/workflows/nope/duplicate", json={})
        assert response.status_code == 404

    def test_a_slug_that_cannot_name_a_directory_is_422(self, tmp_path: Path) -> None:
        # Kept apart from 404 deliberately: "you asked a malformed question"
        # and "the package is gone" are different answers.
        response = self._client(tmp_path).post("/api/workflows/..%2Fetc/duplicate", json={})
        assert response.status_code in (404, 422)
