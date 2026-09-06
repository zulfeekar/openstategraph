"""Regression: `answer` must survive two nodes writing it in the same superstep.

Found live, not hypothetically. A hand-built graph combining a router, an
orchestrator, and two `Send`-dispatched Chinook-tool-bound workers raised
`InvalidUpdateError: At key 'answer': Can receive only one value per step` — a
collision none of the smaller, scripted-model fixtures ever triggered, because
none of them happened to schedule two `answer`-writing nodes in the same tick.
A bare `LastValue` field is only safe for state exactly one node type can ever
produce; `answer` is not that, since `_agent`, `_format_report_function` and
`_output` can each write it depending on the graph's shape.

This test reproduces the collision directly at the `StateGraph` level — two
plain nodes fanned out via `Send`, both writing `answer` in one step — so the
fix is proven without needing a live model, a tool, or the full compiler.
"""

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from openstategraph.compile.node_runtime import keep_latest_nonempty


class BareState(TypedDict, total=False):
    answer: str


class ReducedState(TypedDict, total=False):
    answer: Annotated[str, keep_latest_nonempty]


def _fan_out(state: Any) -> list[Send]:
    return [Send("writer_a", {}), Send("writer_b", {})]


def _writer_a(state: Any) -> dict:
    return {"answer": "from A"}


def _writer_b(state: Any) -> dict:
    return {"answer": "from B"}


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
        # Which one wins is not the point — LangGraph does not guarantee an
        # order between two Sends in one step. That both can legitimately
        # write and the graph still completes is the property being proven.
        assert result["answer"] in ("from A", "from B")

    def test_it_keeps_a_real_value_over_an_empty_one(self) -> None:
        assert keep_latest_nonempty("first", "") == "first"
        assert keep_latest_nonempty("", "second") == "second"

    def test_it_prefers_the_later_write_when_both_are_real(self) -> None:
        # Arbitrary but documented: "later" is whichever write the reducer
        # sees second, not a claim about which node "should" win semantically.
        assert keep_latest_nonempty("first", "second") == "second"

    def test_two_empty_writes_stay_empty_rather_than_raising(self) -> None:
        assert keep_latest_nonempty("", "") == ""


class TestRunStateDeclaresTheReducer:
    def test_answer_is_not_a_bare_scalar_field(self) -> None:
        from openstategraph.compile.node_runtime import RunState

        # Guards against a future refactor quietly reverting this to `str` and
        # reintroducing the exact bug this file documents.
        annotation = RunState.__annotations__["answer"]
        assert "keep_latest_nonempty" in str(annotation) or "Annotated" in str(
            annotation
        )
