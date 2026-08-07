"""`NodeRuntime._agent` delegates to the agent family — no inline construction.

Pins the two behaviours the old inline `create_agent(...)` call silently
lacked: a node's authored ``systemPrompt`` reaches the constructor (it used
to be dropped — three nodes in the video-game workflow carried one and none
did anything), and ``tier: "deep"`` selects ``create_deep_agent`` for the
*agent itself* (previously only Router/Grader honoured their tier).
"""

from __future__ import annotations

import dyflow.abc.agent as agent_module
from dyflow.abc.agent import DeepAgentNode, ReactAgentNode
from dyflow.compile.node_runtime import NodeRuntime, RunState
from dyflow.compile.workflow_compiler import CompiledPlan


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
