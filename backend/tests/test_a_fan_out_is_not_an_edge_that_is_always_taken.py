"""A `Send` fan-out is a decision, so a replan loop through one compiles.

`the-cost-of-one-more` 07. `always_taken_cycles` built its adjacency from
`plan.edges` **plus** `plan.fan_out`, on the stated premise that
*"`orchestrate.supervisor` chooses how many tasks to dispatch, never whether to
stop dispatching."* The compiler contradicts that six hundred lines down: a
fan-out compiles to `add_conditional_edges` whose path function returns `[]`
when the orchestrator planned no subtasks, and an empty list dispatches
nothing. So the supervisor does choose whether to stop, and the one edge kind
the walk went out of its way to include was the one edge kind that decides.

The cost was a **false rejection** — `plan.warnings` is the hard channel, so a
legitimate supervisor replan loop did not merely warn, it failed validation.
The function's own docstring names that as the worse of the two outcomes.

Written against `WorkflowCompiler.plan` on real documents rather than against
`always_taken_cycles` directly: the ticket's claim is about what the compiler
accepts, and a test of the helper would stay green if the warning were raised
somewhere else.
"""

from __future__ import annotations

from typing import Any

import pytest

from openstategraph.compile.node_runtime import RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler


def _node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0, "y": 0},
        "data": dict(data),
    }


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _plan(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Any:
    return WorkflowCompiler().plan(
        {"version": 3, "name": "t", "nodes": nodes, "edges": edges}
    )


def _loop_warnings(plan: Any) -> list[str]:
    return [w for w in plan.warnings if "form a loop with no conditional step" in w]


REPLAN_NODES = [
    _node("in1", "input.text"),
    _node("sup1", "orchestrate.supervisor"),
    _node("w1", "orchestrate.worker", default=True),
    _node("out1", "output.formatted"),
]
REPLAN_EDGES = [
    _edge("in1", "text", "sup1", "instruction"),
    _edge("sup1", "workers", "w1", "dispatch"),
    # The replan: the worker's result returns to the supervisor, which decides
    # whether to dispatch again.
    _edge("w1", "result", "sup1", "instruction"),
    _edge("sup1", "result", "out1", "result"),
]


class TestTheReplanLoopCompiles:
    """The ticket's probe, as a test."""

    @pytest.fixture(scope="class")
    def plan(self) -> Any:
        return _plan(REPLAN_NODES, REPLAN_EDGES)

    def test_the_document_is_exactly_the_shape_the_ticket_probed(
        self, plan: Any
    ) -> None:
        """`sup1 => w1 -> sup1` with nothing in `plan.conditional`. If a later
        change makes the supervisor emit a conditional branch of its own, this
        test would pass for a reason that has nothing to do with the ticket."""
        assert plan.fan_out == {"sup1": ["w1"]}
        assert ("w1", "sup1") in plan.edges
        assert not plan.conditional

    def test_no_loop_is_reported(self, plan: Any) -> None:
        assert _loop_warnings(plan) == []

    def test_the_document_is_valid(self, plan: Any) -> None:
        """`plan.warnings` is all-or-nothing against validity
        (`test_stress_workload_fixtures.py`), so a warning here is a refusal."""
        assert plan.warnings == []


class TestWhatTheGuardStillCatches:
    """Dropping fan-out from the walk must not cost a real detection."""

    def test_an_all_static_loop_is_still_refused(self) -> None:
        """The rule this guard exists for: two agents handing to each other
        with no verdict on the path can only spend the step budget."""
        plan = _plan(
            [
                _node("in1", "input.text"),
                _node("a1", "agent.llm"),
                _node("a2", "agent.llm"),
                _node("out1", "output.formatted"),
            ],
            [
                _edge("in1", "text", "a1", "prompt"),
                _edge("a1", "result", "a2", "prompt"),
                _edge("a2", "result", "a1", "prompt"),
                _edge("a2", "result", "out1", "result"),
            ],
        )
        assert len(_loop_warnings(plan)) == 1
        assert "'a1' -> 'a2' -> 'a1'" in _loop_warnings(plan)[0]

    def test_a_static_loop_below_a_fan_out_is_still_found(self) -> None:
        """The reachability question, answered rather than assumed.

        A fan-out edge is the *only* way into `w1` here, and `f1 -> f2 -> f1`
        below it is all-static. Removing fan-out edges from the adjacency
        would lose this loop if the walk started from `plan.entry` — it does
        not; it starts from every node that has a successor at all, so a
        doomed loop parked behind a decision is still reported.
        """
        plan = _plan(
            [
                _node("in1", "input.text"),
                _node("sup1", "orchestrate.supervisor"),
                _node("w1", "orchestrate.worker", default=True),
                _node("f1", "function.format_report"),
                _node("f2", "function.format_report"),
                _node("out1", "output.formatted"),
            ],
            [
                _edge("in1", "text", "sup1", "instruction"),
                _edge("sup1", "workers", "w1", "dispatch"),
                _edge("w1", "result", "f1", "in"),
                _edge("f1", "result", "f2", "in"),
                _edge("f2", "result", "f1", "in"),
                _edge("sup1", "result", "out1", "result"),
            ],
        )
        assert len(_loop_warnings(plan)) == 1
        assert "'f1' -> 'f2' -> 'f1'" in _loop_warnings(plan)[0]


class TestThePremiseIsReadFromTheCompilerNotFromProse:
    """The docstring's old premise was a sentence nothing could falsify.

    These two assert the fact the new premise rests on — a fan-out compiles to
    a conditional edge, and its path function returns `[]` when the
    orchestrator planned nothing — so if that ever stops being true, this file
    goes red instead of the argument going quietly stale.
    """

    def test_a_fan_out_compiles_to_a_conditional_edge(self) -> None:
        graph = (
            WorkflowCompiler()
            .build(
                {"version": 3, "name": "t", "nodes": REPLAN_NODES, "edges": REPLAN_EDGES},
                RunState,
                lambda *_: (lambda state: {}),
            )
            .get_graph()
        )
        conditional = {
            (edge.source, edge.target) for edge in graph.edges if edge.conditional
        }
        assert ("sup1", "w1") in conditional

    def test_an_orchestrator_that_plans_nothing_dispatches_nothing(self) -> None:
        route = WorkflowCompiler._fan_out_router("sup1", {}, "w1")
        assert route({"subtasks": {}}) == []
        assert route({"subtasks": {"sup1": []}}) == []
