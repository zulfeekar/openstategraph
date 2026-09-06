"""A grader that ran out of budget says so.

**Seen live** (`every-workflow-green` 09): `chinook-assistant` answered its own
documented question — *"Which genre earns the most revenue?"* — with a raw
`InvoiceLine` table schema. The grader had rejected that candidate three times,
the attempts budget ran out, and the third rejection was force-passed and
published as the answer. No warning on any surface. Reproduced on the CLI and
in the editor, so it is not surface-specific.

**The pass itself is correct and is not changed here.** `_grader` says why:
*"Forcing `pass` at the cap is right — a loop that cannot finish is worse than a
mediocre answer… A candidate the grader merely disliked is still the answer the
workflow produced."* The defect is that "the grader approved this" and "the
grader rejected this and gave up" arrive looking identical.

`decisions` cannot carry the distinction: the compiler routes on that exact
label, so a new value there would change control flow. Hence a separate state
key, and a warning built from it the way `silent_node_warnings` is built from
`outputs`.
"""

from __future__ import annotations

from openstategraph.compile.workflow_compiler import forced_pass_warnings


class TestItNamesTheGraderAndTheReason:
    def test_a_forced_pass_is_reported(self) -> None:
        warnings = forced_pass_warnings({"grader-sql": "Does not name a genre or a figure."})
        assert len(warnings) == 1
        assert "grader-sql" in warnings[0]

    def test_it_carries_the_rejection_the_user_never_saw(self) -> None:
        # The whole value: the grader's own reason, which the state used to
        # discard because `feedback` is cleared on a pass.
        warning = forced_pass_warnings({"g1": "Missing the figure."})[0]
        assert "Missing the figure." in warning

    def test_it_says_the_answer_was_published_anyway(self) -> None:
        # A reader must not think the run was blocked. It was not.
        warning = forced_pass_warnings({"g1": "no good"})[0]
        assert "published" in warning.lower() or "returned" in warning.lower()

    def test_every_exhausted_grader_is_named(self) -> None:
        assert len(forced_pass_warnings({"g1": "a", "g2": "b"})) == 2


class TestItStaysQuietOtherwise:
    def test_no_forced_passes_means_no_warnings(self) -> None:
        assert forced_pass_warnings({}) == []

    def test_a_grader_that_passed_on_merit_is_never_named(self) -> None:
        # Only a force-pass writes the key at all, so an empty reason is still
        # a force-pass — but a grader that genuinely approved never appears.
        assert forced_pass_warnings({}) == []

    def test_a_missing_reason_still_reports_the_grader(self) -> None:
        # The verdict may carry no feedback. The fact of the force-pass is the
        # part that matters and must not be swallowed by a falsy reason.
        warnings = forced_pass_warnings({"g1": ""})
        assert len(warnings) == 1
        assert "g1" in warnings[0]
