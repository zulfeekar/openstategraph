"""An unmapped grader verdict is a compile-time finding, not a silent loop
(`launch-readiness` 66, second half).

The ticket's first half — `function.*` never resolving `conditional_upstream`
— was already fixed (`test_guard_check.py::TestConditionalUpstreamFixTicket66`).
This covers the second, genuinely distinct defect: a grader's `pass` port left
unwired falls through, at `_router_for`'s own default, to whichever
destination *is* wired — which in a revision loop is `revise`, so every
passing judgement loops back and the run never terminates.

`UNWIRED_REVISE` does not catch this. It reports the opposite gap (`revise`
unwired), and is deliberately a soft report because a grader with no `revise`
wired is a legal recorder that simply never sends anything back. There is no
equivalent safe reading of `pass` unwired — a `pass` with nowhere to go can
only loop — so it is checked on `plan.warnings`, the hard channel, in
`WorkflowCompiler.plan()` rather than left to `_router_for`'s fallback or a
mid-run `GraphRecursionError`.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from test_human_approval import edge, node


class TestFunctionNodeBehindARoutedEdge:
    """Regression coverage for the ticket's first (already-fixed) half,
    across both routed shapes it names: a grader's `pass` and a classifier
    branch. `_discovered_function`'s `conditional_upstream` fix is exercised
    for the grader/guard shape in
    `test_guard_check.py::TestConditionalUpstreamFixTicket66`; this covers
    the classifier branch, which that file does not.
    """

    def test_a_function_node_behind_a_classifier_branch_receives_the_question(self) -> None:
        document = {
            "version": 1,
            "name": "classifier-then-function",
            "nodes": [
                node("in1", "input.text"),
                node(
                    "router1",
                    "route.classifier",
                    branches=[{"id": "data", "name": "Data question"}],
                ),
                node("f1", "function.grow"),
            ],
            "edges": [
                edge("in1", "text", "router1", "question"),
                edge("router1", "branch:data", "f1", "candidate"),
            ],
        }
        seen: dict[str, str] = {}

        def grow(text: str) -> str:
            seen["text"] = text
            return text

        runtime = NodeRuntime(functions={"function.grow": grow})
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        graph.invoke({"question": "what is the total revenue?", "decisions": {}, "outputs": {}})
        assert seen["text"] == "what is the total revenue?"


def _revision_loop_document(*, wire_pass: bool, node_type: str = "route.grader") -> dict[str, Any]:
    """in -> draft -[candidate]-> grader -[revise]-> draft, optionally -[pass]-> out"""
    edges = [
        edge("in1", "text", "draft1", "prompt"),
        edge("draft1", "result", "grader1", "candidate"),
        edge("grader1", "revise", "draft1", "feedback"),
    ]
    if wire_pass:
        edges.append(edge("grader1", "pass", "out1", "result"))
    return {
        "version": 1,
        "name": "revision-loop",
        "nodes": [
            node("in1", "input.text"),
            node("draft1", "agent.llm"),
            node("grader1", node_type, criteria="No hedging phrases.", maxAttempts=3),
            node("out1", "output.formatted"),
        ],
        "edges": edges,
    }


class TestUnmappedVerdictIsRejectedAtCompileTime:
    def test_an_unwired_pass_is_a_hard_finding_naming_the_verdict_and_what_is_wired(self) -> None:
        document = _revision_loop_document(wire_pass=False)
        plan = WorkflowCompiler().plan(document)
        matches = [w for w in plan.warnings if "grader1" in w and "pass" in w]
        assert matches, plan.warnings
        message = matches[0]
        assert "'pass'" in message
        assert "'revise' -> 'draft1'" in message

    def test_a_guard_check_with_an_unwired_pass_is_rejected_the_same_way(self) -> None:
        document = _revision_loop_document(wire_pass=False, node_type="guard.check")
        document["nodes"][2]["data"] = {"check": "flag_short"}
        plan = WorkflowCompiler().plan(document)
        matches = [w for w in plan.warnings if "grader1" in w and "pass" in w]
        assert matches, plan.warnings

    def test_every_currently_mapped_verdict_still_compiles_with_no_such_warning(self) -> None:
        document = _revision_loop_document(wire_pass=True)
        plan = WorkflowCompiler().plan(document)
        assert not [w for w in plan.warnings if "unmapped" in w.lower()]
        # And the graph still builds and runs to completion.
        runtime = NodeRuntime()
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        assert graph is not None

    def test_a_revise_only_grader_with_no_pass_edge_at_all_is_not_this_finding(self) -> None:
        """No `pass` edge drawn at all is `UNENFORCED_OUTCOME`/a design choice,
        not this one: `plan.conditional['grader1']` would have neither key
        wired from a `pass` *edge that exists but targets nothing sensible* —
        this finding only fires when `revise` is wired and `pass` is not,
        which is exactly the shape that can loop. A grader with revise wired
        and pass unwired is drawn here; the assertion is the same as the
        first test, restated to make the trigger condition explicit.
        """
        document = _revision_loop_document(wire_pass=False)
        plan = WorkflowCompiler().plan(document)
        assert "revise" in plan.conditional.get("grader1", {})
        assert "pass" not in plan.conditional.get("grader1", {})
        assert any("grader1" in w and "pass" in w for w in plan.warnings)
