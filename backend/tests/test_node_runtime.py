"""Runs a canvas-authored workflow end to end, with no model and no API key.

This is the test that proves "what you drag is what runs": a document in the
exact shape the editor exports, compiled and executed, with the router's decision
actually selecting a branch and the grader's rejection actually driving a retry.

The model is a scripted fake, so what is verified is the **wiring** — which is the
part that breaks silently. Whether a real model writes good SQL is a model
evaluation, not a unit test.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from dyflow.compile.node_runtime import NodeRuntime, RunState
from dyflow.compile.workflow_compiler import WorkflowCompiler


class ScriptedModel(GenericFakeChatModel):
    """Answers from a script, and records every prompt it was given.

    Subclasses langchain's own fake rather than duck-typing a model, because
    `create_agent` legitimately requires a real `BaseChatModel` — it calls
    `.bind()` internally. A hand-rolled stand-in failed on exactly that, which is
    a fair complaint from the library rather than something to work around.
    """

    prompts: list[str] = []

    def __init__(self, *answers: str):
        super().__init__(messages=iter(list(answers) or ["PASS"]))
        # Bypasses pydantic's field machinery for a test-only recorder.
        object.__setattr__(self, "prompts", [])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        self.prompts.append("\n".join(str(m.content) for m in messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


#: A router fanning to two destinations, in the shape the canvas exports.
ROUTED = {
    "version": 1,
    "name": "routed",
    "nodes": [
        node("node:input.text-1", "input.text", prompt=""),
        node(
            "node:route.classifier-1",
            "route.classifier",
            branches="dataquery\noff_topic",
            fallback="off_topic",
            rules="Anything about revenue or genres is a dataquery.",
        ),
        node("node:output.formatted-1", "output.formatted"),
        node("node:output.formatted-2", "output.formatted"),
    ],
    "edges": [
        edge("node:input.text-1", "text", "node:route.classifier-1", "question"),
        edge("node:route.classifier-1", "branch:dataquery", "node:output.formatted-1", "result"),
        edge("node:route.classifier-1", "branch:off_topic", "node:output.formatted-2", "result"),
    ],
}


def run(document: dict[str, Any], question: str, model: Any, **kw: Any) -> dict[str, Any]:
    runtime = NodeRuntime(model=model, **kw)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 40},
    )


class TestRouterDrivesTheBranch:
    def test_the_chosen_branch_decides_which_node_runs(self) -> None:
        model = ScriptedModel("dataquery")
        final = run(ROUTED, "Which genre earns most?", model)

        # The router wrote its decision and the conditional edge dispatched on it.
        assert final["decisions"]["node:route.classifier-1"] == "dataquery"
        assert "node:output.formatted-1" in final["outputs"]
        # The other branch must not have run.
        assert "node:output.formatted-2" not in final["outputs"]

    def test_a_different_answer_takes_a_different_branch(self) -> None:
        final = run(ROUTED, "What is the weather?", ScriptedModel("off_topic"))
        assert final["decisions"]["node:route.classifier-1"] == "off_topic"
        assert "node:output.formatted-2" in final["outputs"]
        assert "node:output.formatted-1" not in final["outputs"]

    def test_an_unusable_answer_falls_back_rather_than_stalling(self) -> None:
        final = run(ROUTED, "???", ScriptedModel("banana"))
        assert final["decisions"]["node:route.classifier-1"] == "off_topic"

    def test_the_developer_rules_reach_the_model(self) -> None:
        model = ScriptedModel("dataquery")
        run(ROUTED, "q", model)
        assert "revenue or genres" in model.prompts[0]


#: Same shape as ROUTED, with the router's `tier` set to "deep" — the same
#: field GraderNode already honors, found not to be read at all for Router.
ROUTED_DEEP = {
    **ROUTED,
    "nodes": [
        node("node:input.text-1", "input.text", prompt=""),
        node(
            "node:route.classifier-1",
            "route.classifier",
            branches="dataquery\noff_topic",
            fallback="off_topic",
            rules="Anything about revenue or genres is a dataquery.",
            tier="deep",
        ),
        node("node:output.formatted-1", "output.formatted"),
        node("node:output.formatted-2", "output.formatted"),
    ],
}


class TestDeepRouter:
    """`tier: "deep"` on a Router card previously did nothing — found by a
    TS-schema-vs-Python-factory diff, not live: `RouterNode.ts` declares the
    same `tier` select `GraderNode.ts` does, but `_router` never read it,
    unlike `_grader`. This is the regression test for the fix: `deep` now
    routes the classification through `create_deep_agent`, the same way it
    already does for the grader.
    """

    def test_deep_tier_routes_the_classification_through_create_deep_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import deepagents
        from langchain_core.messages import AIMessage

        calls: list[dict[str, Any]] = []

        class StubDeepAgent:
            def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                calls.append(payload)
                return {"messages": [AIMessage(content="dataquery")]}

        def fake_create_deep_agent(**kwargs: Any) -> StubDeepAgent:
            calls.append({"construction": kwargs})
            return StubDeepAgent()

        monkeypatch.setattr(deepagents, "create_deep_agent", fake_create_deep_agent)

        final = run(ROUTED_DEEP, "Which genre earns most?", ScriptedModel("off_topic"))

        construction_calls = [c for c in calls if "construction" in c]
        assert construction_calls, "create_deep_agent was never called"
        # The stub, not the ScriptedModel default, decided the branch —
        # proof the deep agent's answer is what actually got read.
        assert final["decisions"]["node:route.classifier-1"] == "dataquery"


#: An agent judged by a grader, with `revise` looping back — the shape the
#: evaluator-optimizer pattern produces on the canvas.
GRADED = {
    "version": 1,
    "name": "graded",
    "nodes": [
        node("node:input.text-1", "input.text"),
        node("node:agent.llm-1", "agent.llm"),
        node("node:route.grader-1", "route.grader", criteria="", maxAttempts=3),
        node("node:output.formatted-1", "output.formatted"),
    ],
    "edges": [
        edge("node:input.text-1", "text", "node:agent.llm-1", "prompt"),
        edge("node:agent.llm-1", "result", "node:route.grader-1", "candidate"),
        edge("node:route.grader-1", "pass", "node:output.formatted-1", "result"),
        edge("node:route.grader-1", "revise", "node:agent.llm-1", "feedback"),
    ],
}


class TestGraderLoop:
    def test_a_passing_answer_goes_straight_through(self) -> None:
        # The agent's own model answer, then the grader's PASS.
        final = run(GRADED, "Which genre earns most?", ScriptedModel("Rock, at 826.65", "PASS"))
        assert final["attempts"] == 1
        assert final["answer"]

    def test_a_rejected_answer_is_retried_and_the_retry_carries_the_reason(self) -> None:
        model = ScriptedModel(
            "Some artist",  # agent, attempt 1
            "FAIL\nName the genre, not the artist.",  # grader rejects
            "Rock, at 826.65",  # agent, attempt 2
            "PASS",  # grader accepts
        )
        final = run(GRADED, "Which genre earns most?", model)

        assert final["attempts"] == 2
        # Without the reason in the retry prompt the agent repeats itself and the
        # loop is pure cost.
        assert any("Name the genre, not the artist." in p for p in model.prompts)

    def test_a_persistently_rejected_answer_still_terminates(self) -> None:
        # Always FAIL. The attempt cap must end the loop rather than spinning to
        # GraphRecursionError.
        final = run(GRADED, "impossible", ScriptedModel(*(["bad", "FAIL\nno"] * 8)))
        assert final["attempts"] <= 3
        assert final["decisions"]["node:route.grader-1"] == "pass"


#: Same shape as `GRADED`, but the grader's tier is `deep`.
GRADED_DEEP = {
    **GRADED,
    "nodes": [
        node("node:input.text-1", "input.text"),
        node("node:agent.llm-1", "agent.llm"),
        node("node:route.grader-1", "route.grader", criteria="", maxAttempts=3, tier="deep"),
        node("node:output.formatted-1", "output.formatted"),
    ],
}


class TestDeepGrader:
    """`tier: "deep"` previously did nothing on the backend — `Grader.grade()`
    always made one bare chat-model call no matter what a developer picked
    on the card. This is the regression test for the fix: `deep` actually
    routes the judgement through `create_deep_agent`.

    `deepagents.create_deep_agent` is monkeypatched rather than exercised for
    real, because its own internal call count/shape is not this project's
    concern to pin — only that the grader's wiring reaches it, with the
    resolved system prompt, and reads its answer back correctly.
    """

    def test_deep_tier_routes_the_judgement_through_create_deep_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import deepagents
        from langchain_core.messages import AIMessage

        calls: list[dict[str, Any]] = []

        class StubDeepAgent:
            def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                calls.append(payload)
                return {"messages": [AIMessage(content="FAIL\nName the genre.")]}

        def fake_create_deep_agent(**kwargs: Any) -> StubDeepAgent:
            calls.append({"construction": kwargs})
            return StubDeepAgent()

        monkeypatch.setattr(deepagents, "create_deep_agent", fake_create_deep_agent)

        # The stub always fails, so the agent (a real `create_agent`, unaffected
        # by the grader's tier) runs once per attempt up to the cap.
        final = run(
            GRADED_DEEP, "Which genre earns most?", ScriptedModel(*(["Some artist"] * 3))
        )

        assert final["attempts"] == 3
        construction_calls = [c for c in calls if "construction" in c]
        assert construction_calls, "create_deep_agent was never called"
        assert construction_calls[0]["construction"]["tools"] == []
        assert "grader" in construction_calls[0]["construction"]["system_prompt"].lower()

    def test_deep_tier_reads_a_pass_back_correctly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import deepagents
        from langchain_core.messages import AIMessage

        class StubDeepAgent:
            def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                return {"messages": [AIMessage(content="PASS")]}

        monkeypatch.setattr(
            deepagents, "create_deep_agent", lambda **kwargs: StubDeepAgent()
        )

        final = run(GRADED_DEEP, "Which genre earns most?", ScriptedModel("Rock, at 826.65"))

        assert final["attempts"] == 1
        assert final["decisions"]["node:route.grader-1"] == "pass"


class TestToolBinding:
    def test_wiring_a_tool_on_the_canvas_is_what_gives_the_agent_that_tool(self) -> None:
        document = {
            "version": 1,
            "name": "tooled",
            "nodes": [
                node("node:input.text-1", "input.text"),
                node("node:agent.llm-1", "agent.llm"),
                node("node:tool.chinook-execute-sql-1", "tool.chinook-execute-sql"),
                node("node:output.formatted-1", "output.formatted"),
            ],
            "edges": [
                edge("node:input.text-1", "text", "node:agent.llm-1", "prompt"),
                edge("node:tool.chinook-execute-sql-1", "tool", "node:agent.llm-1", "tools"),
                edge("node:agent.llm-1", "result", "node:output.formatted-1", "result"),
            ],
        }
        from dyflow.compile.node_runtime import chinook_tool_registry

        runtime = NodeRuntime(model=ScriptedModel("ok"), tools=chinook_tool_registry())
        WorkflowCompiler().build(document, RunState, runtime.factory(document))

        # The binding resolved to a real tool, by the bound node's *type*.
        assert runtime.last_bound_tools == ["chinook_execute_sql"]

    def test_an_unknown_tool_type_degrades_rather_than_crashing(self) -> None:
        document = {
            "version": 1,
            "name": "x",
            "nodes": [
                node("node:agent.llm-1", "agent.llm"),
                node("node:tool.unknown-1", "tool.unknown"),
            ],
            "edges": [edge("node:tool.unknown-1", "tool", "node:agent.llm-1", "tools")],
        }
        runtime = NodeRuntime(model=ScriptedModel("ok"), tools={})
        WorkflowCompiler().build(document, RunState, runtime.factory(document))
        # No tools, but a runnable graph — a degraded run beats a crash.
        assert runtime.last_bound_tools == []
        # ...and the loss is *reported*, because an agent that silently loses its
        # tools answers from parametric knowledge, confidently and wrongly.
        # Observed for real: a Reddit tool node with no Python implementation
        # produced an authoritative answer about global music revenue instead of
        # querying anything.
        assert runtime.unresolved_tools == ["tool.unknown"]

    def test_a_bound_sql_tools_max_rows_field_actually_reaches_the_tool(self) -> None:
        """Found by a TS-schema-vs-Python-factory diff: `ChinookDatabaseNode.ts`'s
        `maxRows` field was fully inert on the backend — every
        `tool.chinook-execute-sql` binding always used the bare class
        default, regardless of what a developer configured on the canvas.
        `_bound_tool` now reads the canvas field and builds a fresh instance
        carrying it as `row_cap`.
        """
        document = {
            "version": 1,
            "name": "tooled",
            "nodes": [
                node("node:input.text-1", "input.text"),
                node("node:agent.llm-1", "agent.llm"),
                node("node:tool.chinook-execute-sql-1", "tool.chinook-execute-sql", maxRows=7),
                node("node:output.formatted-1", "output.formatted"),
            ],
            "edges": [
                edge("node:input.text-1", "text", "node:agent.llm-1", "prompt"),
                edge("node:tool.chinook-execute-sql-1", "tool", "node:agent.llm-1", "tools"),
                edge("node:agent.llm-1", "result", "node:output.formatted-1", "result"),
            ],
        }
        from dyflow.compile.node_runtime import chinook_tool_registry

        runtime = NodeRuntime(model=ScriptedModel("ok"), tools=chinook_tool_registry())
        runtime.factory(document)
        tool = runtime._bound_tool("node:tool.chinook-execute-sql-1")

        assert tool is not None
        assert tool.row_cap == 7
        # A fresh instance, not the shared registry one — mutating the
        # shared object would leak across every other binding of this type
        # in the same document.
        assert tool is not runtime.tools["tool.chinook-execute-sql"]


class TestDegradedInputs:
    def test_no_model_still_produces_a_runnable_graph(self) -> None:
        final = run(ROUTED, "q", None)
        # The router falls back, so a workflow opened without a key is still
        # inspectable rather than exploding.
        assert final["decisions"]["node:route.classifier-1"] == "off_topic"

    def test_the_question_overrides_a_saved_prompt(self) -> None:
        document = {
            **ROUTED,
            "nodes": [
                node("node:input.text-1", "input.text", prompt="stale saved prompt"),
                *ROUTED["nodes"][1:],
            ],
        }
        model = ScriptedModel("dataquery")
        run(document, "the live question", model)
        # A saved workflow must answer *this* run, not replay what was typed
        # when it was saved.
        assert "the live question" in model.prompts[0]
        assert "stale saved prompt" not in model.prompts[0]

    def test_an_unknown_node_type_forwards_instead_of_dead_ending(self) -> None:
        document = {
            "version": 1,
            "name": "x",
            "nodes": [
                node("node:input.text-1", "input.text"),
                node("node:future.thing-1", "future.thing"),
                node("node:output.formatted-1", "output.formatted"),
            ],
            "edges": [
                edge("node:input.text-1", "text", "node:future.thing-1", "in"),
                edge("node:future.thing-1", "result", "node:output.formatted-1", "result"),
            ],
        }
        final = run(document, "hello", None)
        assert final["answer"] == "hello"


class TestPerNodeModelResolution:
    """`_resolve_model` — found by a TS-schema-vs-Python-factory diff, not
    live: `AgentNode.ts`'s per-card `model` field (and the same select on
    Router/Grader) was fully inert on the backend. `NodeRuntime` only ever
    accepted one `model` for the *entire graph*, so the canvas visibly
    letting a developer set three different AI Agent nodes to three
    different models did nothing once a run actually reached the backend —
    every one of them used whichever single model `/api/runs` resolved.

    Tested in isolation against `_resolve_model` directly rather than
    through a full compiled graph, because proving *this* node resolves
    *its own* model needs no graph, no tools, no state — only the one
    method that changed. `init_chat_model` is monkeypatched rather than
    exercised for real, the same reasoning `TestDeepGrader` already applies
    to `create_deep_agent`: which real model class it returns is not this
    project's concern to pin, only that the resolution reaches it correctly.
    """

    def test_a_node_with_no_model_field_uses_the_shared_default(self) -> None:
        default = object()
        runtime = NodeRuntime(model=default)
        assert runtime._resolve_model({}) is default

    def test_a_node_configured_for_mock_falls_back_to_the_shared_default(self) -> None:
        # Mock has no backend equivalent — it is a frontend-only simulator
        # for the local canvas preview, not a real chat model.
        default = object()
        runtime = NodeRuntime(model=default)
        assert runtime._resolve_model({"model": "mock/mock-offline"}) is default

    def test_a_node_with_its_own_selection_gets_its_own_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import langchain.chat_models as chat_models

        calls: list[str] = []
        sentinel = object()

        def fake_init_chat_model(key: str) -> Any:
            calls.append(key)
            return sentinel

        monkeypatch.setattr(chat_models, "init_chat_model", fake_init_chat_model)

        runtime = NodeRuntime(model=object())
        resolved = runtime._resolve_model({"model": "anthropic/claude-haiku-4-5"})

        # The frontend's slash-separated selection becomes the colon-joined
        # key `init_chat_model` expects.
        assert calls == ["anthropic:claude-haiku-4-5"]
        assert resolved is sentinel

    def test_two_nodes_on_different_models_each_resolve_their_own(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import langchain.chat_models as chat_models

        calls: list[str] = []

        def fake_init_chat_model(key: str) -> Any:
            calls.append(key)
            return object()

        monkeypatch.setattr(chat_models, "init_chat_model", fake_init_chat_model)

        runtime = NodeRuntime(model=object())
        first = runtime._resolve_model({"model": "anthropic/claude-haiku-4-5"})
        second = runtime._resolve_model({"model": "openai/gpt-4.1-mini"})

        assert calls == ["anthropic:claude-haiku-4-5", "openai:gpt-4.1-mini"]
        assert first is not second

    def test_repeated_requests_for_the_same_model_are_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import langchain.chat_models as chat_models

        calls: list[str] = []

        def fake_init_chat_model(key: str) -> Any:
            calls.append(key)
            return object()

        monkeypatch.setattr(chat_models, "init_chat_model", fake_init_chat_model)

        runtime = NodeRuntime(model=object())
        first = runtime._resolve_model({"model": "anthropic/claude-haiku-4-5"})
        second = runtime._resolve_model({"model": "anthropic/claude-haiku-4-5"})

        assert calls == ["anthropic:claude-haiku-4-5"], "should only build the client once"
        assert first is second

    def test_an_unresolvable_selection_falls_back_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import langchain.chat_models as chat_models

        def fake_init_chat_model(key: str) -> Any:
            raise ValueError(f"no credentials for {key}")

        monkeypatch.setattr(chat_models, "init_chat_model", fake_init_chat_model)

        default = object()
        runtime = NodeRuntime(model=default)

        # An unconfigured provider (no API key) must not take the whole run
        # down — the run still produces an answer from the shared default.
        assert runtime._resolve_model({"model": "openai/gpt-4.1-mini"}) is default
