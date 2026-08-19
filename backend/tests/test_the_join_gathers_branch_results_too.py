"""The synthesis half of `every-workflow-green` 27.

A classifier in `matchMode: "all"` now runs several desks in parallel — proved
live: `routes: {'router1': ['b-data', 'b-policy']}`, with both `mount-music`
and `a-policy` producing output.

What a user gets is still one answer, and `answer` is `LATEST_NONEMPTY`, so
without a join one branch silently wins and the rest of the work is thrown
away — the same silent loss the ticket exists to end, moved one node along.

`function.format_report` is already the join: `candidate` accepts unlimited
edges and it runs with no model, so gathering is deterministic. It read only
`worker_results`, which orchestrator workers write and classifier branches do
not. It now falls back to its upstream nodes' `outputs`.

Deliberately a fallback, not a merge: an orchestrator fan-out and a classifier
fan-out never share a join in practice, and preferring `worker_results` keeps
every shipped report byte-identical.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import NodeRuntime, RunState, RuntimeServices
from openstategraph.compile.workflow_compiler import CompiledPlan


def _join(upstream: list[str], state: dict) -> str:
    runtime = NodeRuntime(services=RuntimeServices(model=None))
    plan = CompiledPlan()
    plan.edges = [(src, "join1") for src in upstream]
    node = {"id": "join1", "type": "function.format_report", "data": {"reportTitle": "Answer"}}
    run = runtime._format_report_function("join1", node, plan)
    return str((run(RunState(**state)) or {}).get("outputs", {}).get("join1", ""))


class TestWorkerResultsStillWin:
    def test_a_worker_fan_out_reports_exactly_as_before(self) -> None:
        report = _join(
            [],
            {
                "worker_results": {"task-1": "alpha", "task-2": "beta"},
                "subtasks": {"lead1": [{"id": "task-1"}, {"id": "task-2"}]},
            },
        )
        assert "alpha" in report and "beta" in report

    def test_worker_results_are_preferred_when_both_exist(self) -> None:
        """The regression net: a shipped report must not change shape because a
        branch happened to leave something in `outputs`."""
        report = _join(
            ["a-policy"],
            {
                "worker_results": {"task-1": "from the worker"},
                "subtasks": {"lead1": [{"id": "task-1"}]},
                "outputs": {"a-policy": "from a desk"},
            },
        )
        assert "from the worker" in report
        assert "from a desk" not in report


class TestBranchResultsAreGatheredWhenThereAreNoWorkers:
    def test_two_upstream_desks_both_reach_the_report(self) -> None:
        report = _join(
            ["mount-music", "a-policy"],
            {"outputs": {"mount-music": "Rock earns the most.", "a-policy": "We review on Tuesdays."}},
        )
        assert "Rock earns the most." in report
        assert "We review on Tuesdays." in report

    def test_a_desk_that_produced_nothing_is_skipped_not_blank(self) -> None:
        report = _join(
            ["mount-music", "a-policy"],
            {"outputs": {"mount-music": "", "a-policy": "Only this ran."}},
        )
        assert "Only this ran." in report

    def test_one_upstream_still_works(self) -> None:
        report = _join(["a-policy"], {"outputs": {"a-policy": "Just the one."}})
        assert "Just the one." in report

    def test_nothing_anywhere_is_not_a_crash(self) -> None:
        assert isinstance(_join([], {}), str)
