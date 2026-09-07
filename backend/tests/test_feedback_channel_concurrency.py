"""Regression: `feedback` must survive two nodes writing it in the same superstep.

Found live in the intent-routed demo, not hypothetically: the chat panel
showed two distinct grader verdicts landing together (a "greeting" rejection
alongside what reads like the off-topic grader's own criteria), then
`InvalidUpdateError: At key 'feedback': Can receive only one value per
step` — the identical hazard already fixed for `answer` and `attempts` in
this same file, just not yet hit for this field. This document alone has
four `_grader` instances (one per intent), and every one writes `feedback`
on every step it runs.

This test reproduces the collision directly at the `StateGraph` level, the
same way the `answer` and `attempts` regressions do.
"""

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from openstategraph.compile.node_runtime import keep_latest_nonempty


class BareState(TypedDict, total=False):
    feedback: str


class ReducedState(TypedDict, total=False):
    feedback: Annotated[str, keep_latest_nonempty]


def _fan_out(state: Any) -> list[Send]:
    return [Send("grader_a", {}), Send("grader_b", {})]


def _grader_a(state: Any) -> dict:
    return {"feedback": "Replace the greeting with a direct statement."}


def _grader_b(state: Any) -> dict:
    return {"feedback": "Provide a polite decline instead of elaborating."}


def build_colliding_graph(schema: type):
    builder = StateGraph(schema)
    builder.add_node("start", lambda s: {})
    builder.add_node("grader_a", _grader_a)
    builder.add_node("grader_b", _grader_b)
    builder.add_edge(START, "start")
    builder.add_conditional_edges("start", _fan_out, ["grader_a", "grader_b"])
    builder.add_edge("grader_a", END)
    builder.add_edge("grader_b", END)
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
        # Which one wins is not the point — LangGraph does not guarantee an
        # order between two Sends in one step. That both can legitimately
        # write and the graph still completes is the property being proven.
        assert result["feedback"] in (
            "Replace the greeting with a direct statement.",
            "Provide a polite decline instead of elaborating.",
        )

    def test_it_keeps_a_real_value_over_an_empty_one(self) -> None:
        assert keep_latest_nonempty("first", "") == "first"
        assert keep_latest_nonempty("", "second") == "second"


class TestRunStateDeclaresTheReducer:
    def test_feedback_is_not_a_bare_scalar_field(self) -> None:
        from openstategraph.compile.node_runtime import RunState

        # Guards against a future refactor quietly reverting this to `str`
        # and reintroducing the exact bug this file documents.
        annotation = RunState.__annotations__["feedback"]
        assert "keep_latest_nonempty" in str(annotation) or "Annotated" in str(
            annotation
        )
