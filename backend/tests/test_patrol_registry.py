"""`PatrolJobRegistry` — kanban-patrol/07's job registry, on its own.

Pure Python, no HTTP: the atomic claim-and-refuse behaviour and the shape of
a snapshot are asserted here; `test_kanban_routes.py` covers the route that
uses this through real requests.
"""

from __future__ import annotations

from openstategraph.api.patrol_registry import PatrolJobRegistry


class TestASingleSlot:
    def test_starts_idle(self) -> None:
        registry = PatrolJobRegistry()

        state = registry.snapshot()

        assert state.status == "idle"
        assert state.started_at == ""
        assert state.error == ""

    def test_try_start_claims_the_slot(self) -> None:
        registry = PatrolJobRegistry()

        claimed = registry.try_start()

        assert claimed is True
        assert registry.snapshot().status == "running"
        assert registry.snapshot().started_at != ""

    def test_a_second_try_start_while_running_is_refused(self) -> None:
        registry = PatrolJobRegistry()
        registry.try_start()

        second = registry.try_start()

        assert second is False
        # Refused, not queued — the state is untouched by the refusal.
        assert registry.snapshot().status == "running"

    def test_a_new_start_is_allowed_once_the_last_one_finished(self) -> None:
        registry = PatrolJobRegistry()
        registry.try_start()
        registry.finished(filed=1, skipped=0, total_findings=1)

        claimed = registry.try_start()

        assert claimed is True


class TestFinishingAndFailing:
    def test_finished_records_the_summary(self) -> None:
        registry = PatrolJobRegistry()
        registry.try_start()

        registry.finished(filed=3, skipped=2, total_findings=5)

        state = registry.snapshot()
        assert state.status == "finished"
        assert state.filed == 3
        assert state.skipped == 2
        assert state.total_findings == 5
        assert state.finished_at != ""
        assert state.error == ""

    def test_failed_records_the_plain_reason(self) -> None:
        """`07`'s own words: 'a patrol that dies silently is worse than one
        that never started.' The reason is reported verbatim, not softened."""
        registry = PatrolJobRegistry()
        registry.try_start()

        registry.failed("sqlite disk I/O error")

        state = registry.snapshot()
        assert state.status == "failed"
        assert state.error == "sqlite disk I/O error"
        assert state.finished_at != ""

    def test_a_failed_run_frees_the_slot_for_the_next_one(self) -> None:
        registry = PatrolJobRegistry()
        registry.try_start()
        registry.failed("boom")

        assert registry.try_start() is True
