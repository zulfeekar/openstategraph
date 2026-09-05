"""`route.check` — a computed fork, and the one edge an ask-back could ride.

`osg-agent-experience/42`. The owner's rule is that a question with no date
range is asked back rather than answered on an assumed window, and the fact was
already in the run: `resolve.vocabulary` reports the range as uncovered without
calling anybody. There was no node that could turn that fact into a route to an
output. `guard.check` routes `pass`/`revise`, but `revise` is a `feedback` port
and an `output.formatted` takes `result`; `route.classifier` can name an
`ask_back` branch, but a **model** picks it, and on the first live run
(2026-09-05, *"How much crude did Norway export?"*) it picked `sm_cargoflow` and
never asked.

So this node is `guard.check`'s sibling on the other axis: the same package
function, called the same way, returning a **branch name** instead of a
complaint. Every out-port is `result`-typed, so an output or an agent may hang
off any of them — which is precisely what a grader's `feedback`-typed `revise`
cannot do.

Every test here compiles and runs a real graph with **no model anywhere**.
"""

from __future__ import annotations

from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import (
    ROUTE_CHECK_TYPE,
    WorkflowCompiler,
)

BRANCHES = [
    {"id": "b1", "name": "ask_back"},
    {"id": "b2", "name": "answer"},
]


def _document(check: str = "needs_a_date_range", branches: object = None) -> dict:
    """input -> route.check -> one of two outputs, plus a fallback output."""
    return {
        "version": 2,
        "name": "route-check-test",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "r1",
                "type": ROUTE_CHECK_TYPE,
                "position": {"x": 200, "y": 0},
                "data": {"check": check, "branches": BRANCHES if branches is None else branches},
            },
            {
                "id": "ask",
                "type": "output.formatted",
                "position": {"x": 400, "y": 0},
                "data": {},
            },
            {
                "id": "ans",
                "type": "output.formatted",
                "position": {"x": 400, "y": 120},
                "data": {},
            },
            {
                "id": "fell",
                "type": "output.formatted",
                "position": {"x": 400, "y": 240},
                "data": {},
            },
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "r1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "r1", "portId": "branch:b1"},
                "target": {"nodeId": "ask", "portId": "result"},
            },
            {
                "source": {"nodeId": "r1", "portId": "branch:b2"},
                "target": {"nodeId": "ans", "portId": "result"},
            },
            {
                "source": {"nodeId": "r1", "portId": "fallback"},
                "target": {"nodeId": "fell", "portId": "result"},
            },
        ],
    }


def _needs_a_date_range(text: str) -> str:
    """The owner's rule, as a package function: no window named, ask back."""
    lowered = text.lower()
    if any(token in lowered for token in ("2024", "2025", "last year", "q1")):
        return "answer"
    return "ask_back"


def _run(runtime: NodeRuntime, document: dict, question: str) -> dict:
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": question, "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
    )


class TestADeterministicFork:
    def test_a_missing_date_range_routes_to_an_output_with_no_model(self) -> None:
        """The ticket's own done-when, run end to end."""
        runtime = NodeRuntime(functions={"function.needs_a_date_range": _needs_a_date_range})
        final = _run(runtime, _document(), "How much crude did Norway export?")

        assert final["decisions"]["r1"] == "b1"
        # The output on the `ask_back` branch ran; the other two did not.
        assert "ask" in final["outputs"]
        assert "ans" not in final["outputs"]
        assert "fell" not in final["outputs"]

    def test_the_same_check_takes_the_other_branch_when_the_window_is_named(self) -> None:
        runtime = NodeRuntime(functions={"function.needs_a_date_range": _needs_a_date_range})
        final = _run(runtime, _document(), "How much crude did Norway export in 2024?")

        assert final["decisions"]["r1"] == "b2"
        assert "ans" in final["outputs"]
        assert "ask" not in final["outputs"]

    def test_the_candidate_travels_through_unchanged(self) -> None:
        """A fork forwards; it does not transform. `outputs[node]` is the input."""
        runtime = NodeRuntime(functions={"function.needs_a_date_range": _needs_a_date_range})
        final = _run(runtime, _document(), "How much crude did Norway export?")

        assert final["outputs"]["r1"] == "How much crude did Norway export?"

    def test_no_model_is_resolved_for_this_node_type(self) -> None:
        """`drives_a_model` is what the run doors gate on (`osg-agent-experience/48`).

        A fork that quietly counted as model-driven would make a workflow of
        deterministic nodes refuse to run for want of a credential.
        """
        from openstategraph.compile.node_runtime import drives_a_model

        runtime = NodeRuntime(functions={"function.needs_a_date_range": _needs_a_date_range})
        runtime.factory(_document())
        assert drives_a_model(runtime) is False


class TestTheReturnIsResolvedStrictly:
    def test_a_name_no_branch_declares_lands_on_fallback(self) -> None:
        """Tolerant in reading, strict in trusting (`CLAUDE.md`)."""
        runtime = NodeRuntime(functions={"function.needs_a_date_range": lambda text: "sm_cargoflow"})
        final = _run(runtime, _document(), "anything")

        assert final["decisions"]["r1"] == "fallback"
        assert "fell" in final["outputs"]
        assert "sm_cargoflow" in final["verdicts"]["r1"]["reason"]

    def test_a_branch_id_is_accepted_as_well_as_its_name(self) -> None:
        """The document's `{id, name}` pair means both spellings are real."""
        runtime = NodeRuntime(functions={"function.needs_a_date_range": lambda text: "b2"})
        final = _run(runtime, _document(), "anything")

        assert final["decisions"]["r1"] == "b2"

    def test_surrounding_whitespace_and_case_do_not_cost_a_branch(self) -> None:
        runtime = NodeRuntime(functions={"function.needs_a_date_range": lambda text: "  Ask_Back\n"})
        final = _run(runtime, _document(), "anything")

        assert final["decisions"]["r1"] == "b1"

    def test_nothing_returned_is_a_fallback_and_says_so(self) -> None:
        runtime = NodeRuntime(functions={"function.needs_a_date_range": lambda text: ""})
        final = _run(runtime, _document(), "anything")

        assert final["decisions"]["r1"] == "fallback"
        assert final["verdicts"]["r1"]["reason"]


class TestFailureIsData:
    def test_an_unresolved_check_is_reported_by_name_and_falls_back(self) -> None:
        runtime = NodeRuntime(functions={})
        document = _document(check="nobody_wrote_this")
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke(
            {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
        )

        assert final["decisions"]["r1"] == "fallback"
        reported = runtime.diagnostics.subjects(Finding.UNRESOLVED_FUNCTION)
        assert any("nobody_wrote_this" in subject for subjects in reported for subject in subjects)

    def test_a_raising_check_becomes_readable_output_rather_than_a_dead_run(self) -> None:
        """The same errors-are-data rule `_discovered_function` applies."""

        def explode(text: str) -> str:
            raise ValueError("no vocabulary loaded")

        runtime = NodeRuntime(functions={"function.needs_a_date_range": explode})
        final = _run(runtime, _document(), "anything")

        assert final["decisions"]["r1"] == "fallback"
        assert "no vocabulary loaded" in final["verdicts"]["r1"]["reason"]


class TestTheGraphShape:
    def test_the_branches_compile_to_one_conditional_destination_each(self) -> None:
        plan = WorkflowCompiler().plan(_document())

        assert plan.conditional["r1"] == {"b1": "ask", "b2": "ans", "fallback": "fell"}

    def test_a_branch_with_nowhere_to_go_is_recorded_rather_than_silent(self) -> None:
        """`_router_for` falls through to the first destination; say so."""
        document = _document()
        document["edges"] = [
            edge
            for edge in document["edges"]
            if edge["source"].get("portId") != "branch:b2"
        ]
        runtime = NodeRuntime(functions={"function.needs_a_date_range": lambda text: "answer"})
        final = _run(runtime, document, "anything")

        assert final["unrouted"]["r1"] == "b2"
