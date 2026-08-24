"""`guard.check` — a grader's mechanical sibling (`launch-readiness` 65).

A `function.*` node had exactly the verdict an agent needed
(`function.validate_sql`'s cardinality/time-window/value complaints) and no
way to send it back — the only port that emits `feedback` was a grader's
`revise`, so acting on a decision already made deterministically required
paying for a model call to re-emit it. `guard.check` answers the same
`pass`/`revise` question a grader does, over the identical conditional-edge
shape, by calling a package function instead of a model.

These tests also exercise `launch-readiness` 66 in passing: a guard's `pass`
edge is conditional by construction, so `_discovered_function`'s
`conditional_upstream` fix is what lets a function node sit downstream of a
guard at all and read the right thing.
"""

from __future__ import annotations

from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler


def _document(check: str = "flag_short", max_attempts: int | None = None) -> dict:
    data: dict = {"check": check}
    if max_attempts is not None:
        data["maxAttempts"] = max_attempts
    return {
        "version": 2,
        "name": "guard-test",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "f1", "type": "function.grow", "position": {"x": 200, "y": 0}, "data": {}},
            {"id": "g1", "type": "guard.check", "position": {"x": 400, "y": 0}, "data": data},
            {"id": "out1", "type": "output.formatted", "position": {"x": 600, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "f1", "portId": "candidate"}},
            {"source": {"nodeId": "f1", "portId": "report"}, "target": {"nodeId": "g1", "portId": "candidate"}},
            {"source": {"nodeId": "g1", "portId": "revise"}, "target": {"nodeId": "f1", "portId": "candidate"}},
            {"source": {"nodeId": "g1", "portId": "pass"}, "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


def _flag_short(text: str) -> str:
    """Rejects anything under five characters; the "deterministic check"."""
    return "" if len(text) >= 5 else "too short, need 5+ chars"


def _growing_function():
    """Grows its own output by one char per call, so a loop can converge."""

    calls = {"n": 0}

    def grow(text: str) -> str:
        calls["n"] += 1
        return "x" * calls["n"]

    return grow, calls


class TestPassAndRevise:
    def test_a_satisfied_check_passes_on_the_first_lap(self) -> None:
        document = _document()
        runtime = NodeRuntime(
            functions={"function.grow": lambda text: "already-long-enough", "function.flag_short": _flag_short}
        )
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke(
            {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
        )
        assert final["decisions"]["g1"] == "pass"
        assert final["feedback"] == ""
        assert final["verdicts"]["g1"]["verdict"] == "pass"

    def test_a_failing_check_sends_its_own_message_back_as_feedback_no_model_involved(
        self,
    ) -> None:
        document = _document()
        runtime = NodeRuntime(
            functions={"function.grow": lambda text: "x", "function.flag_short": _flag_short}
        )
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke(
            {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
        )
        # Never converges ("x" every time) so the budget forces a pass, but
        # the verdict trail shows the mechanical rejection actually fired.
        assert final["verdicts"]["g1"]["check"] == "flag_short"

    def test_a_loop_converges_deterministically_and_terminates(self) -> None:
        grow, calls = _growing_function()
        document = _document(max_attempts=6)
        runtime = NodeRuntime(functions={"function.grow": grow, "function.flag_short": _flag_short})
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke(
            {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
        )
        # "xxxxx" (5 chars) is the first candidate that satisfies the check —
        # reached on the fifth call, well inside the six-attempt budget, with
        # no model anywhere in the loop.
        assert final["decisions"]["g1"] == "pass"
        assert final["outputs"]["g1"] == "xxxxx"
        assert calls["n"] == 5

    def test_the_budget_forces_a_pass_rather_than_looping_forever(self) -> None:
        """A guard that always revises would loop forever without this."""
        document = _document(max_attempts=2)
        runtime = NodeRuntime(
            functions={"function.grow": lambda text: "x", "function.flag_short": _flag_short}
        )  # never satisfies
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke(
            {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
        )
        assert final["decisions"]["g1"] == "pass"
        assert final["revisions"]["g1"] == 2

    def test_an_unresolved_check_is_reported_and_the_run_still_finishes(self) -> None:
        document = _document(check="does_not_exist")
        runtime = NodeRuntime(functions={"function.grow": lambda text: "hello"})
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke(
            {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
        )
        assert final["decisions"]["g1"] == "pass"
        assert ("guard.check:does_not_exist",) in runtime.diagnostics.subjects(
            Finding.UNRESOLVED_FUNCTION
        )

    def test_an_unwired_revise_is_reported_the_way_a_graders_is(self) -> None:
        document = _document()
        # Drop the revise edge, exactly like the grader's own UNWIRED_REVISE test.
        document["edges"] = [e for e in document["edges"] if e["source"]["portId"] != "revise"]
        runtime = NodeRuntime(
            functions={"function.grow": lambda text: "hello", "function.flag_short": _flag_short}
        )
        WorkflowCompiler().build(document, RunState, runtime.factory(document))
        assert ("g1",) in runtime.diagnostics.subjects(Finding.UNWIRED_REVISE)


class TestConditionalUpstreamFixTicket66:
    """A function node behind a guard's routed `pass` edge must read it.

    Regression coverage for `launch-readiness` 66: `_discovered_function`
    never resolved `conditional_upstream`, so a `function.*` node placed
    after a grader's (or now a guard's) `pass` port silently fell back to the
    turn's original question instead of the value it was wired to.
    """

    @staticmethod
    def _document_with_function_after_guard() -> dict:
        return {
            "version": 2,
            "name": "guard-then-function",
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "g1", "type": "guard.check", "position": {"x": 200, "y": 0}, "data": {"check": "flag_short"}},
                {"id": "f1", "type": "function.shout", "position": {"x": 400, "y": 0}, "data": {}},
                {"id": "out1", "type": "output.formatted", "position": {"x": 600, "y": 0}, "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "g1", "portId": "candidate"}},
                # No revise edge — a guard with nowhere to send feedback ships
                # a pass, same as an unwired grader.
                {"source": {"nodeId": "g1", "portId": "pass"}, "target": {"nodeId": "f1", "portId": "candidate"}},
                {"source": {"nodeId": "f1", "portId": "report"}, "target": {"nodeId": "out1", "portId": "result"}},
            ],
        }

    def test_the_downstream_function_reads_the_guards_output_not_the_turn_input(self) -> None:
        document = self._document_with_function_after_guard()
        runtime = NodeRuntime(
            functions={
                "function.shout": lambda text: text.upper(),
                # Long enough to satisfy `flag_short` unconditionally, so
                # `g1` always passes its input straight through.
                "function.flag_short": lambda text: "",
            }
        )
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke(
            {
                "question": "the original question, not the wired value",
                "attempts": 0,
                "decisions": {},
                "outputs": {},
                "revisions": {},
            }
        )
        # Long enough to satisfy `flag_short`, so `g1` passes its own input
        # through unchanged, and `f1` must uppercase *that* — not the
        # question — or this proves the bug is back.
        assert final["outputs"]["f1"] == "THE ORIGINAL QUESTION, NOT THE WIRED VALUE".upper()
        assert "QUESTION" in final["answer"]
