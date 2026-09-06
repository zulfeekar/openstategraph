"""Two doors, one verdict on how a run went.

`every-workflow-green` 14 and 16 were the same defect twice: `/api/runs` and
`/api/runs/stream` each assembled their own health report from the same three
sources, and drifted. Once, a silent node inside a mount was reported by one
door and not the other. Once, a grader that gave up was. Both were found by
running the product, not by a test, because there was nothing a test could hold
— the logic existed twice.

`run_health` is that logic once. A test comparing two implementations would
only prove they agree today; one function cannot disagree with itself.
"""

from __future__ import annotations

from openstategraph.compile.workflow_compiler import failure_marker, run_health


class TestWhatItGathers:
    def test_a_clean_run_reports_nothing(self) -> None:
        health = run_health({"a1": "an answer"}, {}, {})
        assert health.failures == []
        assert health.silent == []

    def test_a_failed_node_is_a_failure_not_a_silence(self) -> None:
        """Only failures may reach the CLI's exit code — the split is the point."""
        health = run_health({"a1": failure_marker("a1", "no credential")}, {}, {})
        assert any("a1" in w for w in health.failures)
        assert health.silent == []

    def test_a_node_that_produced_nothing_is_a_silence_not_a_failure(self) -> None:
        health = run_health({"a1": ""}, {}, {})
        assert any("a1" in w for w in health.silent)
        assert health.failures == []

    def test_a_forced_pass_is_a_silence(self) -> None:
        health = run_health({"a1": "ok"}, {}, {"grader1": "too thin"})
        assert any("grader1" in w for w in health.silent)
        assert health.failures == []


class TestInsideAMountCountsTheSame:
    """Ticket 16 — the half that was reported through one door only."""

    def test_a_silent_node_inside_a_mount_is_seen(self) -> None:
        health = run_health({}, {"mount-sql/answer1": ""}, {})
        assert any("mount-sql/answer1" in w for w in health.silent)

    def test_a_failed_node_inside_a_mount_is_seen(self) -> None:
        nested = {"mount-sql/a1": failure_marker("mount-sql/a1", "boom")}
        health = run_health({}, nested, {})
        assert any("mount-sql/a1" in w for w in health.failures)

    def test_flat_and_nested_are_both_reported_together(self) -> None:
        health = run_health({"a1": ""}, {"m/b1": ""}, {})
        assert len(health.silent) == 2


class TestItToleratesMissingInputs:
    """Each door reads these off a different shape; neither may crash."""

    def test_none_is_treated_as_empty(self) -> None:
        health = run_health(None, None, None)
        assert health.failures == [] and health.silent == []
