"""Three doors onto a run's health, and this is the third one.

`run_health` calls itself *"the one place a run's health is assembled, for
**both** doors"*. There are three: `/api/runs`, `/api/runs/stream`, and
`CompiledWorkflow.ask()` — the seam an adopter embeds and the one
`openstategraph run` prints. The third folded in **node failures only**, so a
grader that ran out of attempts, a node that produced nothing and a grader
whose `revise` verdict reached no edge were all reported over HTTP and silent
from the library and the CLI (`workflow-gallery` 49).

Reproduced live before the fix, against a real model, on a package whose
grader has a self-contradictory rubric:

    HTTP door would say: ['Grader "grader1" ran out of attempts and published
                          an answer it had rejected. …']
    library door says:   []

The defect is not those three sentences. It is that a *fourth* source went
missing the same way three times, once per source added to `run_health`. So
the door does not list sources at all: `run_health_from_state` derives them
from `run_health`'s own signature, and `TestAFifthSourceCannotGoMissing`
below fails if this door stops reading every one of them.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from openstategraph.compile.workflow_compiler import (
    failure_marker,
    run_health,
    run_health_from_state,
)
import pytest

from openstategraph.errors import RunProducedNothing
from openstategraph.loader import CompiledWorkflow


class _RecordingState(dict):
    """A finished state that remembers which keys were read off it."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.read: set[str] = set()

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key: str) -> Any:
        self.read.add(key)
        return super().__getitem__(key)


class _StubGraph:
    def __init__(self, final: Any) -> None:
        self.final = final

    async def ainvoke(self, _state: Any, _config: Any = None, **_kw: Any) -> Any:
        return self.final


def _workflow(
    final: Any,
    warnings: list[str] | None = None,
    failure_warnings: list[str] | None = None,
) -> CompiledWorkflow:
    """`failure_warnings` defaults to all of `warnings`, which is what
    `load_workflow` produced before ticket 89 split the two — so every case
    below keeps asking exactly what it asked. A finding that is only a *report*
    is the new case, and it says so by passing the two lists separately."""
    return CompiledWorkflow(
        graph=_StubGraph(final),
        warnings=list(warnings or []),
        failure_warnings=list(warnings or [] if failure_warnings is None else failure_warnings),
        slug="probe",
        package_dir=Path("."),
        document={},
    )


def _unhealthy_state() -> _RecordingState:
    """One state carrying every source `run_health` knows about."""
    return _RecordingState(
        answer="an answer of a sort",
        attempts=2,
        decisions={},
        outputs={"a1": failure_marker("a1", "no credential"), "a2": ""},
        nested_outputs={"mount-sql/b1": ""},
        forced={"grader1": "too thin"},
        unrouted={"grader2": "revise"},
    )


class TestEverythingTheHttpDoorsReportReachesThisOne:
    def test_all_four_sources_reach_run_result_warnings(self) -> None:
        result = _workflow(_unhealthy_state()).ask("q")
        joined = " | ".join(result.warnings)

        assert "a1" in joined, "a failed node"
        assert "a2" in joined, "a node that produced nothing"
        assert "mount-sql/b1" in joined, "a silent node inside a mount"
        assert "grader1" in joined, "a grader that ran out of attempts"
        assert "grader2" in joined, "a revise verdict with no edge"

    def test_it_says_exactly_what_the_http_doors_say(self) -> None:
        state = _unhealthy_state()
        health = run_health_from_state(state)
        result = _workflow(state).ask("q")

        assert result.warnings == health.failures + health.silent

    def test_compile_findings_still_come_first(self) -> None:
        result = _workflow(_unhealthy_state(), ["compiled with a missing tool"]).ask("q")
        assert result.warnings[0] == "compiled with a missing tool"


class TestOnlyTheFailureHalfIsAClaimThatTheRunFailed:
    """`silent_node_warnings` forbids sharing a channel a script gates on."""

    def test_reports_about_how_the_answer_was_reached_are_not_failures(self) -> None:
        result = _workflow(_unhealthy_state()).ask("q")

        assert any("a1" in w for w in result.failures), "a failed node is a failure"
        for report in ("a2", "mount-sql/b1", "grader1", "grader2"):
            assert not any(report in w for w in result.failures), report

    def test_a_compile_finding_stays_a_failure(self) -> None:
        """Ticket 53 — a mount that could not be loaded leaves no marker.

        The door **raises** here since `launch-readiness/171`: no answer and a
        reason is the one shape that must never come back as a blank string.
        The report it was returning is on the error, and that is what this
        asserts — the raise is the delivery, not a replacement."""
        with pytest.raises(RunProducedNothing) as raised:
            _workflow(_RecordingState(answer="", outputs={}), ["mount missing"]).ask("q")
        assert raised.value.result.failures == ["mount missing"]

    def test_a_report_only_finding_does_not(self) -> None:
        """Ticket 89's other side, at this door: a finding on `warnings` and
        off `failure_warnings` is reported and never blamed."""
        workflow = _workflow(
            _RecordingState(answer="", outputs={}), ["rules say no tools"], failure_warnings=[]
        )
        result = workflow.ask("q")
        assert result.warnings == ["rules say no tools"]
        assert result.failures == []

    def test_an_empty_answer_with_only_reports_still_exits_zero(self) -> None:
        """The case the CLI's short circuit was hiding: a legally empty answer."""
        from openstategraph.cli import EXIT_OK, run_exit_code

        state = _RecordingState(
            answer="", outputs={"a1": ""}, forced={"g1": "thin"}, unrouted={"g2": "revise"}
        )
        result = _workflow(state).ask("q")

        assert result.warnings, "the reports are still printed"
        assert run_exit_code(result) == EXIT_OK

    def test_an_empty_answer_with_a_failed_node_still_exits_one(self) -> None:
        from openstategraph.cli import EXIT_FAILURE, run_exit_code

        state = _RecordingState(answer="", outputs={"a1": failure_marker("a1", "boom")})
        with pytest.raises(RunProducedNothing) as raised:
            _workflow(state).ask("q")
        # The exit code and the raise read one predicate
        # (`results.produced_nothing`), so this pins that they agree.
        assert run_exit_code(raised.value.result) == EXIT_FAILURE


class TestAFifthSourceCannotGoMissing:
    """The actual defect — three sources went missing one at a time.

    A source of run health *is* a parameter of `run_health`, named for the
    state key it is read from. This asserts the door reads every one of them,
    so a fifth is carried by this door the day it is added to the assembly —
    and a door that goes back to listing sources by hand goes red here.
    """

    def _sources(self) -> set[str]:
        return set(inspect.signature(run_health).parameters)

    def test_the_door_reads_every_source_the_assembly_declares(self) -> None:
        state = _unhealthy_state()
        _workflow(state).ask("q")

        missing = self._sources() - state.read
        assert not missing, f"{sorted(missing)} never reached RunResult"

    def test_the_assembly_reads_every_source_off_one_state(self) -> None:
        state = _RecordingState()
        run_health_from_state(state)

        assert self._sources() <= state.read
