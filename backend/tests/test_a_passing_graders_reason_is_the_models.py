"""A pass carries the grader's own sentence, not a tautology (`workflow-gallery` 53).

`BaseGrader.normalise` read `tail` — everything after the keyword — on the
`fail` branch and threw it away on the `pass` branch, returning the string
literal `"Grader passed it"`. So a rejection carried the model's reasoning and
an approval carried a restatement of itself, **and it is the approval a
reviewer is looking at when they decide to send something under their name.**

**These assertions go through the interrupt frame**, not through `normalise`
alone. `normalise` returning the tail is not the defect; *a reviewer at the
gate reading the grader's own sentence* is, and a fix that stopped at the
`Verdict` would leave a helper-level test green with the frame unchanged. The
frame is also where the length question lands: `reason` is model prose on a
customer-adjacent surface, so an approval card that suddenly renders four
hundred words is a regression even though the field is "more informative".

The inverses below are the load-bearing half. `CLAUDE.md`: *"the narrowness is
the safety, and it is the part that regresses"*, and `Grader.normalise` is
named there as the one that got tolerance right first — a grader that raises on
an unexpected shape turns a recoverable judgement into a dead run. So a bare
`PASS`, an unreadable answer, a rejection and a deterministic check must all
still behave exactly as they did.
"""

from __future__ import annotations

from openstategraph.abc.grader import Grader, Verdict

from test_the_gate_says_what_the_grader_thought import (
    graded_gate_document,
    interrupt_frame,
)

DRAFT = "I'm sorry the invoice you received is incorrect; a corrected one follows today."


class TestTheReviewerReadsTheGradersOwnSentence:
    def test_a_pass_with_a_sentence_reaches_the_gate_with_that_sentence(self) -> None:
        frame = interrupt_frame(
            graded_gate_document(),
            DRAFT,
            "PASS\nIt apologises plainly and commits to a date, with no hedging.",
            thread_id="t-53-explained",
        )
        assert frame["verdict"] == "pass"
        assert frame["reason"] == (
            "It apologises plainly and commits to a date, with no hedging."
        )

    def test_the_sentence_survives_on_the_keywords_own_line(self) -> None:
        """`PASS — reason` is as common a reply as putting it on line two."""
        frame = interrupt_frame(
            graded_gate_document(),
            DRAFT,
            "PASS - it apologises plainly and names a date.",
            thread_id="t-53-inline",
        )
        assert frame["reason"] == "it apologises plainly and names a date."

    def test_a_bare_pass_says_so_rather_than_inventing_a_sentence(self) -> None:
        """A bare `PASS` is legitimate and common; a constant is honest there.

        It must be distinguishable from *the grader said why* — which is what
        `"Grader passed it"` was not: it read like a sentence and carried
        nothing.
        """
        frame = interrupt_frame(
            graded_gate_document(), DRAFT, "PASS", thread_id="t-53-bare"
        )
        assert frame["verdict"] == "pass"
        assert frame["reason"] == "No reason given"

    def test_a_paragraph_is_bounded_and_arrives_on_one_line(self) -> None:
        """Model prose of unknown length, on a surface a person reads at speed."""
        essay = "\n".join(f"Point {i}: the draft is acceptable because of this." for i in range(40))
        frame = interrupt_frame(
            graded_gate_document(), DRAFT, f"PASS\n{essay}", thread_id="t-53-essay"
        )
        assert len(frame["reason"]) <= 200
        assert "\n" not in frame["reason"]
        assert frame["reason"].startswith("Point 0: the draft is acceptable")
        assert frame["reason"].endswith("…")


class TestTheNarrownessIsStillThere:
    def test_a_rejection_still_carries_the_models_reasoning(self) -> None:
        assert Grader().normalise("FAIL\n'if appropriate' is a hedge.") == Verdict(
            passed=False,
            reason="'if appropriate' is a hedge.",
            feedback="'if appropriate' is a hedge.",
        )

    def test_a_deterministic_check_composes_its_own_reason_untouched(self) -> None:
        empty = Grader().grade("")
        assert (empty.passed, empty.reason, empty.failed_check) == (
            False,
            "The answer is empty.",
            "empty",
        )
        broken = Grader().grade("Traceback (most recent call last):")
        assert broken.failed_check == "error"
        assert broken.reason.startswith("The step failed: Traceback")

    def test_an_unreadable_answer_still_passes_rather_than_raising(self) -> None:
        """The property `CLAUDE.md` names `normalise` for. Do not lose it."""
        assert Grader().normalise("{}").reason == "Verdict unclear; passing by default"
        assert Grader().normalise("").reason == "Grader gave no answer; passing by default"
        assert Grader().normalise("   \n  ").passed is True

    def test_no_model_and_no_answer_keep_their_own_sentences(self) -> None:
        assert Grader().grade("A fine draft.").reason == "No grading model configured"

    def test_a_keyword_with_nothing_but_punctuation_after_it_is_not_a_reason(self) -> None:
        """Strict in trusting: `PASS.` said no more than `PASS` did."""
        assert Grader().normalise("PASS.").reason == "No reason given"
        assert Grader().normalise("Passed:").reason == "No reason given"
