"""Regression: `attempts` must survive two nodes writing it in the same superstep.

Found live in the intent-routed demo, not hypothetically: the browser chat
panel surfaced `InvalidUpdateError: At key 'attempts': Can receive only one
value per step` from an `AI Agent` node marked "Failed" after repeated chat
sends. `attempts` is the same shape of hazard already fixed for `answer`
(see `test_answer_channel_concurrency.py`) — `_agent` and `_orchestrator`
each bump it for their own retry/replan budget, and a bare scalar field is
only safe for state exactly one node type can ever produce.

This test reproduces the collision directly at the `StateGraph` level, the
same way the `answer` regression does, so the fix is proven without needing
a live model or the full compiler.
"""

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from openstategraph.compile.node_runtime import keep_max


class BareState(TypedDict, total=False):
    attempts: int


class ReducedState(TypedDict, total=False):
    attempts: Annotated[int, keep_max]


def _fan_out(state: Any) -> list[Send]:
    return [Send("writer_a", {}), Send("writer_b", {})]


def _writer_a(state: Any) -> dict:
    return {"attempts": 1}


def _writer_b(state: Any) -> dict:
    return {"attempts": 2}


def build_colliding_graph(schema: type):
    builder = StateGraph(schema)
    builder.add_node("start", lambda s: {})
    builder.add_node("writer_a", _writer_a)
    builder.add_node("writer_b", _writer_b)
    builder.add_edge(START, "start")
    builder.add_conditional_edges("start", _fan_out, ["writer_a", "writer_b"])
    builder.add_edge("writer_a", END)
    builder.add_edge("writer_b", END)
    return builder.compile()


class TestTheCollisionIsReal:
    def test_a_bare_scalar_field_raises_when_two_nodes_write_it_concurrently(
        self,
    ) -> None:
        """Proves the bug existed, so the fix below is not solving a fiction."""
        import pytest
        from langgraph.errors import InvalidUpdateError

        graph = build_colliding_graph(BareState)
        with pytest.raises(InvalidUpdateError):
            graph.invoke({})


class TestTheFix:
    def test_the_reducer_resolves_two_concurrent_writes_without_raising(self) -> None:
        graph = build_colliding_graph(ReducedState)
        result = graph.invoke({})
        # `max` is the correct resolution regardless of write order, unlike
        # `answer`'s "which one wins is not the point" — a budget counter
        # should only ever grow, so the higher write is always right.
        assert result["attempts"] == 2

    def test_it_keeps_the_higher_count(self) -> None:
        assert keep_max(1, 2) == 2
        assert keep_max(2, 1) == 2

    def test_equal_counts_stay_equal(self) -> None:
        assert keep_max(0, 0) == 0


class TestRunStateDeclaresTheReducer:
    def test_attempts_is_not_a_bare_scalar_field(self) -> None:
        from openstategraph.compile.node_runtime import RunState

        # Guards against a future refactor quietly reverting this to `int`
        # and reintroducing the exact bug this file documents.
        annotation = RunState.__annotations__["attempts"]
        assert "keep_max" in str(annotation) or "Annotated" in str(annotation)
