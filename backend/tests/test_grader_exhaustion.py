"""What a revise loop says when it runs out of attempts with nothing to show.

Found live, in the editor, not hypothetically: `chinook-assistant` routed a
data question to its mounted analyst, the analyst's grader rejected twice and
then hit its `maxAttempts` ceiling, and the chat panel reported

    No answer was produced.
    3 attempts before the grader passed it.

Two sentences that contradict each other. The grader deliberately forces
`pass` at the ceiling so a run finishes instead of spinning — that part is
right — but when the last attempt produced *nothing*, forcing `pass` passes an
empty string down the graph, and the surface is left saying a run both
succeeded and produced no answer.

A user cannot act on that. They cannot tell an exhausted retry loop from a
crash, from a routing mistake, from a model outage. So the ceiling now reports
itself.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import CompiledPlan


class _StubGrader:
    """Always rejects — the only interesting case for a ceiling."""

    def __init__(self, feedback: str = "not good enough") -> None:
        self.feedback = feedback

    def grade(self, candidate: str, question: str = "") -> Any:  # noqa: ARG002
        class _Verdict:
            passed = False
            # `Verdict` declares `reason` beside `feedback` and `_grader`
            # reads it (`workflow-gallery` 32). A double missing a field of
            # the type it stands in for is a Liskov failure in the test, not
            # a reason to make the runtime defensive.
            reason = "the ceiling case"

        verdict = _Verdict()
        verdict.feedback = self.feedback  # type: ignore[attr-defined]
        return verdict


def _grader_run(monkeypatch: Any, *, max_attempts: int = 3) -> Any:
    runtime = NodeRuntime(model=None)
    monkeypatch.setattr(
        "openstategraph.compile.node_runtime.Grader",
        lambda **_kwargs: _StubGrader(),
    )
    node = {
        "id": "grader1",
        "type": "route.grader",
        "data": {"maxAttempts": str(max_attempts)},
    }
    plan = CompiledPlan()
    plan.edges = [("agent1", "grader1")]
    return runtime._grader("grader1", node, plan)


class TestTheCeiling:
    def test_a_rejected_but_non_empty_candidate_still_passes_through_verbatim(
        self, monkeypatch: Any
    ) -> None:
        """Best-effort is a real outcome and must not be editorialised.

        A candidate the grader disliked is still the analyst's answer, and
        rewriting it at the ceiling would replace the user's result with our
        commentary.
        """
        run = _grader_run(monkeypatch)
        state = {
            "question": "Which genre earns the most revenue?",
            "attempts": 3,
            "outputs": {"agent1": "Rock, $826.65."},
        }
        result = run(state)  # type: ignore[arg-type]
        assert result["decisions"]["grader1"] == "pass"
        assert result["outputs"]["grader1"] == "Rock, $826.65."

    def test_an_empty_candidate_at_the_ceiling_says_what_happened(
        self, monkeypatch: Any
    ) -> None:
        """The live failure. Silence here reads as a broken product."""
        run = _grader_run(monkeypatch)
        state = {"question": "Which genre earns the most revenue?", "attempts": 3, "outputs": {}}
        result = run(state)  # type: ignore[arg-type]

        assert result["decisions"]["grader1"] == "pass"
        answer = result["outputs"]["grader1"]
        assert answer, "an exhausted loop with nothing to show must still say so"
        # It has to name the ceiling — that is the actionable part, since the
        # fix is either a better prompt or a higher `maxAttempts`.
        assert "3" in answer
        # And it must carry the grader's last objection, which is the only
        # evidence available about *why* nothing came back.
        assert "not good enough" in answer

    def test_it_never_speaks_before_the_ceiling(self, monkeypatch: Any) -> None:
        """Under the cap an empty candidate means revise, not report."""
        run = _grader_run(monkeypatch)
        state = {"question": "q", "attempts": 1, "outputs": {}}
        result = run(state)  # type: ignore[arg-type]
        assert result["decisions"]["grader1"] == "revise"
        assert result["outputs"]["grader1"] == ""
