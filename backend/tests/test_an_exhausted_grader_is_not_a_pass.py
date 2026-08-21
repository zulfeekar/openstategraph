"""An exhausted revision loop and a satisfied one must not read alike.

`workflow-gallery` 22, and it arrives with most of its fix already shipped.
`_grader` forces the `pass` branch at the step budget so a loop that cannot
succeed still finishes — that decision is right and is not changed — and
`every-workflow-green` 09 added the `forced` state key and
`forced_pass_warnings` so the forced pass reports itself. What was missing is
the thing that would have caught a regression: every existing test of that
machinery calls `forced_pass_warnings` directly, so **all of them would stay
green if `_grader` stopped writing `forced` at all**, and none of them proves
the sentence reaches a door.

This file asks the question a caller asks, at the layer a caller stands on: a
real compiled graph over the shipped `budget-exhaustion` document, a scripted
grader, and `RunResult`.

**Why `attempts` is not the answer.** It is tempting to say a caller can infer
exhaustion by comparing `attempts` against `maxAttempts`. They cannot, for two
separate reasons, and the second is pinned below: `RunResult` carries no
`maxAttempts` at all, so the comparison needs the document; and even holding
the document, a grader that genuinely passed on the **last available lap**
produces `attempts: 2`, `decisions: {"grader1": "pass"}` — byte-identical to
the exhausted run. The counter reaching the ceiling and the rubric never being
satisfied are different facts, and only one of them is what a reader wants.

**And the sentence must not overclaim.** An exhausted loop means the answer
never satisfied its rubric. It does not mean the answer is wrong, and the
reader is often a customer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel
from openstategraph.loader import load_workflow

PACKAGE = Path(__file__).resolve().parent.parent / "openstategraph" / "examples" / "budget-exhaustion"

#: The seven-word answer the live 2026-08-15 run actually shipped, so the
#: scripted candidate is the one the example documents rather than a stand-in.
CANDIDATE = "Tracks changes, enables collaboration, prevents data loss."
REJECTION = "Add a reasoning explanation of at least forty words."


def _is_grader(context: str) -> bool:
    return "You are a grader" in context


class _GraderThatRelentsOnLap(RespondingModel):
    """Rejects until `relent_on`, then passes.

    `relent_on=None` never passes — the example's own self-contradictory
    rubric, scripted. `relent_on=2` is the case most likely to be misreported:
    a genuine pass that happens to land on the last lap the budget allows, so
    `exhausted` is true at the moment the verdict is read.
    """

    relent_on: int | None = None
    seen: int = 0

    def __init__(self, relent_on: int | None = None) -> None:
        super().__init__(rules=[])
        object.__setattr__(self, "relent_on", relent_on)
        object.__setattr__(self, "seen", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        context = "\n".join(str(m.content) for m in messages)
        if _is_grader(context):
            object.__setattr__(self, "seen", self.seen + 1)
            relents = self.relent_on is not None and self.seen >= self.relent_on
            return self._reply("PASS" if relents else f"FAIL\n{REJECTION}")
        return self._reply(CANDIDATE)


def _run(model: Any) -> Any:
    workflow = load_workflow(PACKAGE, model=model)
    return workflow.ask("Answer in exactly seven words: why is version control useful?")


@pytest.fixture(scope="module")
def exhausted() -> Any:
    return _run(_GraderThatRelentsOnLap(relent_on=None))


@pytest.fixture(scope="module")
def satisfied_at_once() -> Any:
    return _run(_GraderThatRelentsOnLap(relent_on=1))


@pytest.fixture(scope="module")
def satisfied_on_the_last_lap() -> Any:
    return _run(_GraderThatRelentsOnLap(relent_on=2))


class TestTheRunSaysWhichOfTheTwoHappened:
    def test_an_exhausted_grader_is_named_in_warnings(self, exhausted: Any) -> None:
        assert any("grader1" in line for line in exhausted.warnings)

    def test_it_carries_the_rejection_nothing_else_publishes(self, exhausted: Any) -> None:
        """`feedback` is cleared on a pass, so without `forced` this reason is
        discarded. Its survival in the live run was an accident of
        `LATEST_NONEMPTY`; here it is on the channel on purpose."""
        assert any(REJECTION in line for line in exhausted.warnings)

    def test_the_answer_is_still_published_unchanged(self, exhausted: Any) -> None:
        """The forced pass is correct. A candidate the grader merely disliked
        is still what the workflow produced, and nothing here rewrites it."""
        assert str(exhausted) == CANDIDATE
        assert exhausted.decisions == {"grader1": "pass"}

    def test_it_is_a_report_and_not_a_failed_run(self, exhausted: Any) -> None:
        """`.failures` is the half a script gates on (`workflow-gallery` 49),
        and `cli.run_exit_code` reads it. A workflow that answered did not
        fail, so an exhausted loop must never move an exit code."""
        from openstategraph.cli import run_exit_code

        assert exhausted.failures == []
        assert run_exit_code(exhausted) == 0

    def test_the_cli_prints_it_as_a_warning(self, exhausted: Any) -> None:
        """The door the ticket names: stderr, on the shipped smoke run."""
        from openstategraph.cli import run_report_lines

        lines = run_report_lines(exhausted)
        assert [line for line in lines if line.startswith("warning:") and "grader1" in line]
        assert not [line for line in lines if line.startswith("error:")]

    def test_it_does_not_say_the_answer_is_wrong(self, exhausted: Any) -> None:
        """"Never satisfied its rubric" is a weaker claim than "wrong", and the
        reader is often a customer. The sentence may say the grader rejected
        the candidate; it may not pronounce on the candidate itself."""
        report = " ".join(exhausted.warnings).lower()
        for overclaim in ("incorrect", "is wrong", "invalid answer", "failed"):
            assert overclaim not in report


class TestAGenuinePassStaysSilent:
    def test_a_grader_that_passed_at_once_reports_nothing(
        self, satisfied_at_once: Any
    ) -> None:
        assert satisfied_at_once.warnings == []

    def test_a_genuine_pass_on_the_last_available_lap_reports_nothing(
        self, satisfied_on_the_last_lap: Any
    ) -> None:
        """The inverse that matters. `exhausted` is true here — the counter has
        reached the cap — and the verdict is still the grader's own. Reporting
        this would cry wolf on every loop that used its whole budget well."""
        assert satisfied_on_the_last_lap.warnings == []
        assert satisfied_on_the_last_lap.decisions == {"grader1": "pass"}

    def test_the_two_last_lap_runs_are_otherwise_identical(
        self, exhausted: Any, satisfied_on_the_last_lap: Any
    ) -> None:
        """Why the counter cannot carry the distinction, stated as an
        assertion rather than as a paragraph: same answer, same decision, same
        `attempts`. Everything a caller could read before this warning existed
        agrees, and only the report tells them apart."""
        assert exhausted.attempts == satisfied_on_the_last_lap.attempts == 2
        assert str(exhausted) == str(satisfied_on_the_last_lap)
        assert exhausted.decisions == satisfied_on_the_last_lap.decisions
        assert exhausted.warnings != satisfied_on_the_last_lap.warnings
