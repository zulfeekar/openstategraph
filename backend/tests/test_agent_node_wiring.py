"""`NodeRuntime._agent` delegates to the agent family — no inline construction.

Pins the two behaviours the old inline `create_agent(...)` call silently
lacked: a node's authored ``systemPrompt`` reaches the constructor (it used
to be dropped — three nodes in the video-game workflow carried one and none
did anything), and ``tier: "deep"`` selects ``create_deep_agent`` for the
*agent itself* (previously only Router/Grader honoured their tier).
"""

from __future__ import annotations

import openstategraph.abc.agent as agent_module
from openstategraph.abc.agent import DeepAgentNode, ReactAgentNode
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan


class RecordingNode(ReactAgentNode):
    """A ReactAgentNode whose build records instead of constructing."""

    built: list["RecordingNode"] = []

    def build(self):
        RecordingNode.built.append(self)
        return None  # runtime treats an unbuildable agent as model-missing


class RecordingDeepNode(DeepAgentNode):
    built: list["RecordingDeepNode"] = []

    def build(self):
        RecordingDeepNode.built.append(self)
        return None


def _run_factory(monkeypatch, data: dict) -> None:
    RecordingNode.built.clear()
    RecordingDeepNode.built.clear()
    monkeypatch.setattr(
        agent_module,
        "agent_node_for_tier",
        lambda tier: RecordingDeepNode if tier == "deep" else RecordingNode,
    )
    runtime = NodeRuntime(model=object())
    node = {"id": "a1", "type": "agent.llm", "data": data}
    run = runtime._agent("a1", node, CompiledPlan())
    run(RunState(question="q"))  # type: ignore[typeddict-item]


class TestAgentNodeDelegation:
    def test_the_authored_system_prompt_reaches_the_family(self, monkeypatch) -> None:
        _run_factory(monkeypatch, {"systemPrompt": "You are a data analyst."})
        (built,) = RecordingNode.built
        prompt = built.resolve_prompt()
        assert prompt is not None and "You are a data analyst." in prompt

    def test_tier_deep_selects_the_deep_sibling(self, monkeypatch) -> None:
        _run_factory(monkeypatch, {"tier": "deep"})
        assert len(RecordingDeepNode.built) == 1
        assert not RecordingNode.built

    def test_default_tier_is_react(self, monkeypatch) -> None:
        _run_factory(monkeypatch, {})
        assert len(RecordingNode.built) == 1


class TestSummarizeToggle:
    """The card's `summarize` toggle must actually contribute the
    SummarizationMiddleware slot — long threads stay bounded (memory sweep,
    2026-08-09)."""

    def _built_with(self, monkeypatch, data: dict) -> RecordingNode:
        from langchain_core.language_models import GenericFakeChatModel

        RecordingNode.built.clear()
        monkeypatch.setattr(
            agent_module, "agent_node_for_tier", lambda tier: RecordingNode
        )
        runtime = NodeRuntime(model=GenericFakeChatModel(messages=iter([])))
        node = {"id": "a1", "type": "agent.llm", "data": data}
        run = runtime._agent("a1", node, CompiledPlan())
        run(RunState(question="q"))  # type: ignore[typeddict-item]
        (built,) = RecordingNode.built
        return built

    def test_summarize_true_contributes_the_slot(self, monkeypatch) -> None:
        built = self._built_with(monkeypatch, {"summarize": True})
        assert "summarization" in built._middleware_contributions

    def test_summarize_off_contributes_nothing(self, monkeypatch) -> None:
        built = self._built_with(monkeypatch, {})
        assert "summarization" not in built._middleware_contributions
