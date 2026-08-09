"""Prompt chaining: agent → agent needs no compiler change (ticket 08).

The editor's `agent.llm.prompt` port now accepts a `result`, so a chain of
agents is drawable. The claim this file pins is the other half: the runtime
*already* seeds a node's prompt from its upstream nodes' outputs, so a
chained agent is nothing but two `StateGraph` nodes and one static edge.

If the compiler ever stopped emitting the agent→agent edge, or `_agent`
stopped reading `outputs`, the second agent would silently fall back to the
original question — the same class of bug ticket found live for conditional
edges — and these tests would fail instead.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState, _upstream_text
from openstategraph.compile.workflow_compiler import CompiledPlan, WorkflowCompiler


def _node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


CHAIN = {
    "version": 1,
    "name": "chain",
    "nodes": [
        _node("in1", "input.text"),
        _node("ag1", "agent.llm"),
        _node("ag2", "agent.llm"),
        _node("out1", "output.formatted"),
    ],
    "edges": [
        _edge("in1", "text", "ag1", "prompt"),
        # The link ticket 08 made drawable.
        _edge("ag1", "result", "ag2", "prompt"),
        _edge("ag2", "result", "out1", "result"),
    ],
}


def _prompt_seed(runtime: NodeRuntime, plan: CompiledPlan, node_id: str, state: RunState) -> str:
    """Mirrors `_agent`'s seed exactly; a drift here should fail loudly."""
    upstream = [src for src, dst in plan.edges if dst == node_id]
    conditional = [
        src
        for src, dests in plan.conditional.items()
        if node_id in dests.values() and runtime._types.get(src) != "route.classifier"
    ]
    return _upstream_text(state, upstream + conditional) or state.get("question", "")


class TestChainedAgents:
    def test_the_chain_compiles_to_a_linear_sequence(self) -> None:
        plan = WorkflowCompiler().plan(CHAIN)
        assert ("ag1", "ag2") in plan.edges
        assert plan.entry == ["in1"]
        assert plan.exits == ["out1"]

    def test_the_second_agents_prompt_is_the_first_agents_output(self) -> None:
        plan = WorkflowCompiler().plan(CHAIN)
        state = RunState(  # type: ignore[typeddict-item]
            question="who bought the most?",
            outputs={"in1": "who bought the most?", "ag1": "FIRST AGENT ANSWER"},
        )
        assert (
            _prompt_seed(NodeRuntime(model=None), plan, "ag2", state) == "FIRST AGENT ANSWER"
        )

    def test_the_first_agent_still_receives_the_question(self) -> None:
        plan = WorkflowCompiler().plan(CHAIN)
        state = RunState(question="who bought the most?", outputs={"in1": "who bought the most?"})  # type: ignore[typeddict-item]
        assert _prompt_seed(NodeRuntime(model=None), plan, "ag1", state) == "who bought the most?"

    def test_an_unrun_first_agent_does_not_poison_the_second(self) -> None:
        """No output yet means fall back to the question, not an empty prompt."""
        plan = WorkflowCompiler().plan(CHAIN)
        state = RunState(question="who bought the most?", outputs={})  # type: ignore[typeddict-item]
        assert _prompt_seed(NodeRuntime(model=None), plan, "ag2", state) == "who bought the most?"
