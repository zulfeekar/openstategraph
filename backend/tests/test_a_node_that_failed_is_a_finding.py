"""A node failure is already sitting in the checkpointer — `kanban-patrol/22`.

The story: an observability platform like LangSmith traces every step and
tags errors as they happen, and it looks like this project would need new
instrumentation to get the same thing. It would not. Every node's result
already lands in `outputs[node_id]`, a real `RunState` channel
(`compile/state.py`), so the checkpointer already persists a failure marker
at the exact step it occurred — `parse_failure_marker` already decodes it,
for `node_failure_warnings`'s own live-run reporting.

This is the offline half: a third finding, reusing every seam `A`/`B`
(`REDUNDANT_TOOL_CALL`/`UNSTABLE_TOOL_RESULT`) already reuse — the same
checkpoint read, the same `RunFinding` shape, the same audience gate — rather
than a new table or new instrumentation on the run path.

**Different threshold from A/B, on purpose.** A repeated tool call is only
interesting the second time; a node failing even *once* is already real
information, so this fires on one occurrence, not two.
"""

from __future__ import annotations

from typing import Any

from openstategraph.api.audience import Audience
from openstategraph.api.schemas import ThreadHistoryResponse, ThreadStep, ThreadSummary
from openstategraph.run_findings import NODE_FAILURE, _node_failures, run_findings
from openstategraph.run_sinks import RunRecord

THREAD = "run-failure-1"


class _Stub:
    """One stored checkpoint, holding whatever channels this test needs."""

    def __init__(self, step: int, channel_values: dict[str, Any]) -> None:
        self.config = {"configurable": {"thread_id": THREAD, "checkpoint_ns": ""}}
        self.checkpoint = {
            "id": f"cp-{step}",
            "ts": f"2026-09-01T16:0{step}:00+00:00",
            "channel_values": channel_values,
            "updated_channels": list(channel_values),
        }
        self.metadata = {"step": step, "source": "loop", "workflow_slug": "stress-deep"}
        self.pending_writes = ()


class _Saver:
    def __init__(self, tuples: list[Any]) -> None:
        self._tuples = list(reversed(tuples))

    def list(self, config: Any, *, limit: int = 200) -> list[Any]:
        return self._tuples[:limit]


def _record(**overrides: Any) -> RunRecord:
    fields: dict[str, Any] = {
        "kind": "run",
        "at": "2026-09-01T16:09:46+02:00",
        "workflow_slug": "stress-deep",
        "thread_id": THREAD,
        "seconds": 1.0,
        "attempts": 1,
    }
    fields.update(overrides)
    return RunRecord(**fields)


def _findings(tuples: list[Any]) -> list[Any]:
    return run_findings(
        [_Saver(tuples)], [_record()], audience=Audience.DEVELOPER
    )


class TestOneFailureIsAlreadyAFinding:
    def test_a_single_node_failure_fires_unlike_a_single_tool_call(self) -> None:
        """The threshold difference, stated as the actual assertion: `A`/`B`
        need two occurrences to mean anything; this needs one."""
        tuples = [
            _Stub(
                0,
                {
                    "messages": [],
                    "outputs": {
                        "checkout": "[checkout failed after retries: no credential — set ANTHROPIC_API_KEY]"
                    },
                },
            ),
        ]

        findings = _findings(tuples)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.name == NODE_FAILURE
        assert finding.tool == "checkout"
        assert "ANTHROPIC_API_KEY" in finding.arguments

    def test_a_node_that_succeeds_is_not_a_finding(self) -> None:
        tuples = [_Stub(0, {"messages": [], "outputs": {"checkout": "42 items shipped"}})]

        assert _findings(tuples) == []

    def test_the_same_node_failing_at_two_steps_is_one_finding_citing_both(self) -> None:
        reason = "[checkout failed after retries: rate limited]"
        tuples = [
            _Stub(0, {"messages": [], "outputs": {"checkout": reason}}),
            _Stub(1, {"messages": [], "outputs": {"checkout": reason}}),
        ]

        findings = _findings(tuples)

        assert len(findings) == 1
        assert findings[0].calls == 2
        assert len(findings[0].checkpoints) == 2

    def test_two_different_nodes_failing_is_two_findings(self) -> None:
        tuples = [
            _Stub(
                0,
                {
                    "messages": [],
                    "outputs": {
                        "checkout": "[checkout failed after retries: rate limited]",
                        "billing": "[billing failed after retries: timeout]",
                    },
                },
            ),
        ]

        findings = _findings(tuples)

        assert {f.tool for f in findings} == {"checkout", "billing"}

    def test_a_truncated_outputs_value_is_skipped_not_crashed_on(self) -> None:
        """`values` renders as capped JSON (`api/threads._cap` truncates a
        very wide `outputs` map mid-object, ending `… (+N chars)`). Tested at
        `_node_failures` directly — the layer that owns the guard — never
        fail to parse, skip, same rule `grouping_key` already follows for a
        call this module cannot group."""
        history = ThreadHistoryResponse(
            thread=ThreadSummary(
                thread_id=THREAD,
                workflow_slug="stress-deep",
                session_id="",
                user_email="",
                updated_at="2026-09-01T16:00:00+00:00",
                steps=1,
                question="",
                answer="",
                status="finished",
            ),
            steps=[
                ThreadStep(
                    checkpoint_id="cp-0",
                    step=0,
                    at="2026-09-01T16:00:00+00:00",
                    source="loop",
                    values={"outputs": '{"checkout": "truncated json… (+4000 chars)'},
                    namespace=[],
                    node="",
                    wrote=[],
                )
            ],
        )

        assert _node_failures(history) == {}
