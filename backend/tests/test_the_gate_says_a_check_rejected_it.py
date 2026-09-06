"""The reviewer at a gate is told when *no model* formed the opinion.

`docs-and-gaps` 15. `production-ready` 92 made a grader row say when its
verdict came from `deterministic_checks` rather than from `self.model.invoke`,
and `_upstream_verdict` carries that marker on to the person at a
`human.approval` gate:

    if row.get("check"):
        found["check"] = str(row["check"])

Deleting those two lines left the entire Python suite green (4272 passed / 1
skipped, byte-identical), measured twice — at `3e6fe07`+14 and again here. The
`update` frame a trace is built from was pinned by 92; the `interrupt` frame a
*reviewer* acts on was not, and neither was the absent-vs-empty rule the
comment at those lines argues for.

**Two layers, because one of them cannot see the mutation.** `_stream_run`
guards the field itself — it emits `check` only when the payload's is truthy —
so a producer that wrote `check: ""` on every verdict would reach the wire
looking correct. That rule therefore has to be pinned where it is decided, on
`_upstream_verdict`; and the marker's *journey* has to be pinned on the frame,
because a fix that stopped at the helper would leave the reviewer no better
informed. Same division `test_the_gate_says_what_the_grader_thought.py` states
for `verdict` and `reason`.

**Absence is the value.** No `check` key means no deterministic check fired,
which covers an ordinary pass *and* a model's own rejection alike — the check
name is an open set, never captioned or looked up (92). A key present-but-empty
would make a client distinguish `""` from absent to learn nothing.
"""

from __future__ import annotations

from openstategraph.api.streaming import FRAME_FIELDS
from openstategraph.compile.state import _upstream_verdict

from test_the_gate_says_what_the_grader_thought import (
    graded_gate_document,
    interrupt_frame,
)

#: A candidate whose first word trips `deterministic_checks` — the grader
#: returns before `self.model.invoke`, so one answer drives the whole run.
TRANSPORTED_ERROR = "Error: connection refused"


class TestTheFrameCarriesTheCheck:
    """At `maxAttempts: 1` a rejection is force-passed straight to the gate.

    Which is the production shape this marker exists for: a person is asked to
    sign off text that was rejected, and whether a model ever read it changes
    what they should do about it.
    """

    def test_a_deterministic_rejection_names_its_check_and_a_judgement_does_not(self) -> None:
        checked = interrupt_frame(
            graded_gate_document(max_attempts=1),
            TRANSPORTED_ERROR,
            thread_id="t-15-error",
            attempts=1,
        )
        judged = interrupt_frame(
            graded_gate_document(max_attempts=1),
            "I'll refund it if appropriate.",
            "FAIL\n'if appropriate' is a hedge and the rubric forbids holding phrases.",
            thread_id="t-15-judged",
            attempts=1,
        )

        assert checked["verdict"] == "revise"
        assert checked["check"] == "error"
        # The measurement that matters to a reader: the two frames differ, so a
        # marker on every row (or on none) is not a passing answer.
        assert "check" not in judged
        assert judged["verdict"] == "revise"

    def test_the_marker_is_the_check_that_fired_not_a_flag(self) -> None:
        """`empty` and `error` are different sentences on the reviewer's card."""
        empty = interrupt_frame(
            graded_gate_document(max_attempts=1),
            "   ",
            thread_id="t-15-empty",
            attempts=1,
        )
        assert empty["check"] == "empty"

    def test_a_gate_with_no_grader_upstream_omits_the_key_too(self) -> None:
        from test_the_gate_says_what_the_grader_thought import ungraded_gate_document

        frame = interrupt_frame(
            ungraded_gate_document(), "A draft nobody judged.", thread_id="t-15-none"
        )
        assert "check" not in frame

    def test_the_frame_contract_declares_the_field(self) -> None:
        assert "check" in FRAME_FIELDS["interrupt"]


class TestAbsentIsNotEmpty:
    """Decided in `_upstream_verdict`, and only visible there.

    `_stream_run` drops a falsy `check` on the way out, so every assertion
    below would stay green at the frame while the producer published `""` on
    every verdict in the system.
    """

    @staticmethod
    def _state(**row: str) -> dict:
        return {"verdicts": {"grader1": {"verdict": "revise", "reason": "no", **row}}}

    def test_a_check_that_fired_is_carried_and_stringified(self) -> None:
        found = _upstream_verdict(self._state(check="error"), ["grader1"])  # type: ignore[arg-type]
        assert found["check"] == "error"

    def test_an_empty_check_produces_no_key_at_all(self) -> None:
        found = _upstream_verdict(self._state(check=""), ["grader1"])  # type: ignore[arg-type]
        assert "check" not in found
        assert found["verdict"] == "revise"

    def test_an_absent_check_produces_no_key_at_all(self) -> None:
        found = _upstream_verdict(self._state(), ["grader1"])  # type: ignore[arg-type]
        assert "check" not in found

    def test_a_non_string_check_is_stringified_rather_than_travelling_raw(self) -> None:
        """The wire is JSON and a client renders this into a sentence."""
        state = {"verdicts": {"grader1": {"verdict": "revise", "reason": "", "check": 7}}}
        found = _upstream_verdict(state, ["grader1"])  # type: ignore[arg-type]
        assert found["check"] == "7"
