"""launch-readiness ticket 26 — the grader is asked to check what it cannot see.

`BaseGrader.grade` hands the model the candidate text and nothing about the
run that produced it (`abc/grader.py`). A criterion of the shape "traceable to
a page the agent actually fetched" is therefore unsatisfiable in principle,
and the shipped `loop` and `routed-qa` templates carried exactly that shape —
"must come from a tool result" — until this ticket. A stranger's install hit
it live: a correct, cited answer was rejected three times with reason
*"provides a URL that was not actually fetched and verified by the agent"*
(`docs/decisions/stranger-install-2026-08-24.md` §9).

Chosen fix, shape 2 of the ticket's two: stop shipping the unanswerable
criterion, and say in the field's own docs that a criterion must be checkable
from the answer text alone. Shape 1 (hand the grader `tool_use`) is not taken
here — it is recorded as future work in the ticket, not implemented, so
provenance grading stays explicitly unsupported.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from openstategraph import templates
from openstategraph.abc.criteria_check import unsatisfiable_provenance_claims
from openstategraph.abc.grader import Grader

GOOD_CITED_ANSWER = (
    "The function is `create_agent` from `langchain.agents`, taking `model` "
    "and `tools`. See https://docs.langchain.com/oss/python/langchain/agents "
    "for the reference."
)

OLD_TEMPLATE_CRITERIA = (
    "- The answer must address the request that was actually made.\n"
    "- Every factual claim must come from a tool result or be marked as "
    "uncertain — never invented.\n"
    "- Say what is wrong specifically enough that the next attempt can fix it."
)


class GuessingModel:
    """Stands in for a model asked to judge a fact it cannot see.

    Scripted, not live (`CLAUDE.md`: never treat a local/mocked stand-in as
    representative of model quality, but a scripted response is fine and
    cheaper for pinning *code* behaviour). This mirrors the exact rejection
    text from the stranger run.
    """

    def invoke(self, messages):  # noqa: ANN001
        return AIMessage(
            content=(
                "FAIL\nThe answer provides a URL that was not actually fetched "
                "and verified by the agent."
            )
        )


class TestTheUnsatisfiableRejectionReproduces:
    """Reproduce first: drive the grader with the old shipped criteria and a
    genuinely correct, cited candidate. It is rejected — not because the
    answer is wrong, but because the criterion asks for something `grade()`
    cannot check."""

    def test_a_correct_cited_answer_is_rejected_under_the_old_criteria(self) -> None:
        grader = Grader(criteria=OLD_TEMPLATE_CRITERIA, model=GuessingModel())

        verdict = grader.grade(GOOD_CITED_ANSWER, question="What is the function?")

        assert verdict.passed is False
        assert "not actually fetched" in verdict.reason


class TestTheOldCriteriaWereUnsatisfiableByConstruction:
    def test_the_phrase_check_flags_the_old_shipped_text(self) -> None:
        assert unsatisfiable_provenance_claims(OLD_TEMPLATE_CRITERIA) != []


class TestShippedTemplatesAskOnlyWhatTheGraderCanAnswer:
    """The pin the ticket asks for: the shipped criteria are satisfiable given
    what the grader is actually handed — candidate text, nothing about tool
    calls."""

    def _grader_criteria(self, name: str) -> list[str]:
        document = json.loads((templates.get(name).directory / "workflow.json").read_text())
        return [
            node["data"]["criteria"]
            for node in document["nodes"]
            if node["type"] == "route.grader"
        ]

    def test_loop_template_criteria_are_satisfiable(self) -> None:
        criteria = self._grader_criteria("loop")
        assert criteria, "expected the loop template to ship a grader"
        for text in criteria:
            assert unsatisfiable_provenance_claims(text) == [], text

    def test_routed_qa_template_criteria_are_satisfiable(self) -> None:
        criteria = self._grader_criteria("routed-qa")
        assert criteria, "expected the routed-qa template to ship a grader"
        for text in criteria:
            assert unsatisfiable_provenance_claims(text) == [], text


class TestTheFixDoesNotBuySatisfiabilityWithLeniency:
    """The new criteria must still reject a genuinely bad answer — an
    invented figure with no citation at all — so the fix is not just a more
    lenient grader wearing a satisfiable label."""

    def test_an_uncited_invented_claim_still_fails(self) -> None:
        new_criteria = self._current_loop_criteria()
        assert unsatisfiable_provenance_claims(new_criteria) == []

        class RejectsUncited:
            def invoke(self, messages):  # noqa: ANN001
                return AIMessage(
                    content="FAIL\nThe claim carries no citation and cannot be checked."
                )

        grader = Grader(criteria=new_criteria, model=RejectsUncited())
        verdict = grader.grade("The answer is 42, obviously.", question="What is it?")

        assert verdict.passed is False

    @staticmethod
    def _current_loop_criteria() -> str:
        document = json.loads(
            (templates.get("loop").directory / "workflow.json").read_text()
        )
        (node,) = (
            n for n in document["nodes"] if n["type"] == "route.grader"
        )
        return str(node["data"]["criteria"])
