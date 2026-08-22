"""A loop that cannot settle must answer, not raise.

`organisms-first-class` 56, split out of 34. `CLAUDE.md`'s cycles section
already asked for this in as many words — *"Prefer generating a
`RemainingSteps` guard so a runaway loop routes to `END` instead of
crashing"* — and `grep -rn RemainingSteps backend/` returned nothing.

**What a caller got before this, measured at every door.** A revision loop
whose grader never relents, run with a step budget smaller than the laps its
`maxAttempts` buys, raised `langgraph.errors.GraphRecursionError` out of
`ask()`; the HTTP door turned it into a `502` reading
`GraphRecursionError: Recursion limit of 10 reached…`, and the CLI printed
LangGraph's own sentence — *"You can increase the limit by setting the
`recursion_limit` config key"* — which is the advice `13fa2d7`'s pinned copy
exists to contradict.

**Why the guard is not a fifth spelling of "stop".** There were three
(`maxAttempts` per grader, the step budget, `interrupt`), and this adds no
fourth mechanism: `RemainingSteps` is a *managed state key*, and the rule
that reads it lands on the one branch a cycle may close on — the grader's
`revise` — where a budget already decides whether another lap happens. A
starved grader takes the **same wired `pass` path** an exhausted one takes,
so the output node still runs and the caller gets the answer the workflow
actually produced.

**And it says so.** A guard that routed to `END` silently would replace a
loud crash with a quiet wrong answer, which is strictly worse. The stop is
reported on the **silent** channel beside the force-pass it resembles — the
run completed and published, so it is a report about *how* the answer was
reached, and `bc58fc1`'s rule holds: no report-only finding may move an exit
code.

The two things it must not be confused with are pinned as hard as the fix:
an attempt-cap exhaustion (`7d86909`) still fires with its own sentence and
no budget sentence, and a loop that settles pays nothing at all.

**No live model run was possible** — this environment has no provider
credential — so every observation is a scripted model through a real
`WorkflowCompiler` graph.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel
from openstategraph.loader import load_workflow

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"

#: The phrase the budget stop is recognised by, everywhere below.
BUDGET_SENTENCE = "step budget"
#: The attempt-cap sentence, which must never be the one a budget stop writes.
ATTEMPTS_SENTENCE = "ran out of attempts"


class _NeverRelents(RespondingModel):
    """A grader that rejects every candidate, forever. The only model shape
    that can actually exhaust a step budget."""

    def __init__(self) -> None:
        super().__init__(rules=[])
        object.__setattr__(self, "graded", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        context = "\n".join(str(m.content) for m in messages)
        if "You are a grader" not in context:
            return self._reply("a draft of the answer")
        object.__setattr__(self, "graded", self.graded + 1)
        return self._reply("FAIL\nstill not good enough")


class _RelentsAtOnce(RespondingModel):
    """The inverse: a grader that passes the first candidate it sees, so the
    loop settles and the guard must cost it nothing."""

    def __init__(self) -> None:
        super().__init__(rules=[])
        object.__setattr__(self, "graded", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        context = "\n".join(str(m.content) for m in messages)
        if "You are a grader" not in context:
            return self._reply("a draft of the answer")
        object.__setattr__(self, "graded", self.graded + 1)
        return self._reply("PASS")


def _package(tmp_path: Path, name: str, caps: dict[str, int]) -> Path:
    """A shipped example copied out and re-capped, so the test states the
    budget it is talking about rather than depending on the shipped number."""
    destination = tmp_path / name
    shutil.copytree(EXAMPLES / name, destination)
    payload = json.loads((destination / "workflow.json").read_text())
    for node in payload["document"]["nodes"]:
        if node["id"] in caps:
            node["data"]["maxAttempts"] = caps[node["id"]]
    (destination / "workflow.json").write_text(json.dumps(payload))
    return destination


def _budget_lines(result: Any) -> list[str]:
    return [w for w in (result.warnings or []) if BUDGET_SENTENCE in w]


class TestARunawayLoopAnswersInsteadOfRaising:
    """The defect, at the layer a caller stands on: `ask()` with a step budget
    too small for the laps `maxAttempts: 500` buys."""

    @pytest.fixture(scope="class")
    def run(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        package = _package(
            tmp_path_factory.mktemp("runaway"), "evaluator-optimizer", {"grader1": 500}
        )
        model = _NeverRelents()
        workflow = load_workflow(package, model=model)
        return workflow.ask("Describe the export fix.", recursion_limit=10), model

    def test_no_recursion_error_escapes(self, run: Any) -> None:
        """Before this, `GraphRecursionError` came out of `ask()` and the
        caller got no answer, no warnings and no record of the run at all."""
        result, _ = run
        assert str(result).strip()

    def test_the_answer_is_what_the_workflow_produced(self, run: Any) -> None:
        result, _ = run
        assert "a draft of the answer" in str(result)

    def test_the_run_says_the_step_budget_stopped_it(self, run: Any) -> None:
        lines = _budget_lines(run[0])
        assert len(lines) == 1, run[0].warnings
        assert "grader1" in lines[0]

    def test_it_is_not_dressed_as_an_attempt_cap(self, run: Any) -> None:
        """The two exhaustions are different facts with different fixes: a cap
        is a number on a card, a budget is a number on the workflow."""
        result, _ = run
        assert [w for w in (result.warnings or []) if ATTEMPTS_SENTENCE in w] == []

    def test_it_is_a_report_and_not_a_failure(self, run: Any) -> None:
        """`bc58fc1`: no report-only finding may move an exit code. The run
        completed and published along its own wired `pass` edge."""
        result, _ = run
        assert result.failures == []

    def test_the_sentence_uses_the_settled_vocabulary(self, run: Any) -> None:
        """`CLAUDE.md` fixes the words: **step budget**, **supersteps**, never
        "iterations" or "max turns"."""
        sentence = _budget_lines(run[0])[0].lower()
        assert "superstep" in sentence
        assert "iteration" not in sentence
        assert "max turns" not in sentence

    def test_it_does_not_repeat_langgraphs_own_advice(self, run: Any) -> None:
        """LangGraph says *"You can increase the limit"*; `13fa2d7`'s pinned
        copy says a bigger number only lets it run longer."""
        sentence = _budget_lines(run[0])[0].lower()
        assert "increase the limit" not in sentence


class TestALoopThatSettlesPaysNothing:
    """The inverse that is load-bearing. A guard that fired on an ordinary run
    would truncate every workflow with a cycle in it."""

    @pytest.fixture(scope="class")
    def run(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        package = _package(
            tmp_path_factory.mktemp("settles"), "evaluator-optimizer", {"grader1": 3}
        )
        model = _RelentsAtOnce()
        workflow = load_workflow(package, model=model)
        return workflow.ask("Describe the export fix.", recursion_limit=10), model

    def test_the_grader_passed_it(self, run: Any) -> None:
        result, _ = run
        assert result.decisions.get("grader1") == "pass"

    def test_nothing_reports_a_budget_stop(self, run: Any) -> None:
        assert _budget_lines(run[0]) == []

    def test_the_answer_is_untouched(self, run: Any) -> None:
        result, _ = run
        assert "a draft of the answer" in str(result)


class TestAnExhaustedGraderStillReportsItself:
    """`7d86909`'s report must still fire, distinctly. A cap of 2 with a
    generous step budget exhausts on attempts and never goes near the
    budget."""

    @pytest.fixture(scope="class")
    def run(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        package = _package(
            tmp_path_factory.mktemp("capped"), "evaluator-optimizer", {"grader1": 2}
        )
        model = _NeverRelents()
        workflow = load_workflow(package, model=model)
        return workflow.ask("Describe the export fix.", recursion_limit=50), model

    def test_the_cap_stopped_it(self, run: Any) -> None:
        _, model = run
        assert model.graded == 2

    def test_the_attempt_sentence_still_fires(self, run: Any) -> None:
        result, _ = run
        forced = [w for w in (result.warnings or []) if ATTEMPTS_SENTENCE in w]
        assert len(forced) == 1 and "grader1" in forced[0]

    def test_and_no_budget_sentence_rides_along(self, run: Any) -> None:
        assert _budget_lines(run[0]) == []


class TestTheStopIsAHealthSourceLikeEveryOther:
    """`run_health` is the one place a run's health is assembled, and
    `run_health_from_state` reads its sources off the signature — so a new
    source arriving as a parameter named for its state key reaches all three
    doors, and `test_the_streaming_door_cannot_fall_behind_a_health_source`
    fails if the streaming fold forgets it."""

    def test_run_health_reads_the_state_key(self) -> None:
        from openstategraph.compile.workflow_compiler import run_health_from_state

        health = run_health_from_state({"outputs": {}, "budget_stops": {"grader1": 1}})
        assert health.failures == []
        assert any(BUDGET_SENTENCE in line for line in health.silent)

    def test_an_absent_key_reports_nothing(self) -> None:
        from openstategraph.compile.workflow_compiler import run_health_from_state

        assert run_health_from_state({"outputs": {}}).silent == []
