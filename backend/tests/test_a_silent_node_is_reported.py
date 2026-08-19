"""A node that produced nothing is a finding, not a blank cell.

**Seen on three workflows** while walking them in the editor
(`every-workflow-green` 01): `two-stage-double-loop/draft1`,
`archetype-orchestrator-report/worker-research#task-1`, and
`chinook-assistant/agent-sql`. Each time the run reported **success** and every
surface showed a confident answer.

It survives because `answer` carries the `LATEST_NONEMPTY` reducer, so a node
that produces nothing leaves the previous value standing and everything
downstream reads a **stale** answer as though it were fresh. That reducer is
correct — it is what lets a grader's forced pass have something to hand on — and
is not the bug. The silence is.

This is the same shape `node_failure_warnings` already reports for a node that
*crashed*: the run genuinely completed, other nodes genuinely produced results,
and one step is quietly worse than it looks. A node that returns empty is that
case without the exception, so it belongs in the same channel rather than a new
one.

Developer channel only, like every other entry there — a customer's surface is
governed by `api/audience.py` and never renders these.
"""

from __future__ import annotations

from openstategraph.compile.workflow_compiler import (
    failure_marker,
    node_failure_warnings,
    silent_node_warnings,
)


class TestASilentNodeIsNamed:
    def test_an_empty_output_is_reported(self) -> None:
        warnings = silent_node_warnings({"agent-sql": ""})
        assert len(warnings) == 1
        assert "agent-sql" in warnings[0]

    def test_it_says_the_run_carried_on_with_something_else(self) -> None:
        # The half a developer cannot see: the answer they are reading came
        # from an earlier node, because `answer` keeps the last non-empty value.
        warning = silent_node_warnings({"draft1": ""})[0]
        assert "produced no output" in warning
        assert "previous" in warning.lower() or "earlier" in warning.lower()

    def test_whitespace_only_counts_as_nothing(self) -> None:
        assert silent_node_warnings({"worker-1": "   \n  "})

    def test_every_silent_node_is_named_not_just_the_first(self) -> None:
        warnings = silent_node_warnings({"a": "", "b": "", "c": "fine"})
        assert len(warnings) == 2
        assert {"a", "b"} == {w.split('"')[1] for w in warnings}


class TestItDoesNotDrownTheRealFailures:
    def test_a_crashed_node_still_reports_its_own_message(self) -> None:
        # The existing case, unchanged: a node that raised carries the cause,
        # and must not be reduced to "produced no output".
        marker = failure_marker("t-sql", "no credential — set CHINOOK_DB")
        warnings = node_failure_warnings({"t-sql": marker})
        assert len(warnings) == 1
        assert "no credential" in warnings[0]

    def test_a_node_with_output_is_never_reported(self) -> None:
        assert node_failure_warnings({"agent-sql": "Rock, $826.65"}) == []

    def test_an_empty_output_is_not_a_run_failure(self) -> None:
        # The separation this ticket turns on: `node_failure_warnings` feeds
        # the CLI exit code, and an empty answer alone is not a failed run.
        assert node_failure_warnings({"out1": ""}) == []

    def test_a_missing_key_is_not_a_silent_node(self) -> None:
        # A node that never ran is absent from `outputs` entirely. That is a
        # routing fact, not a silence, and belongs to whoever reports routes.
        assert silent_node_warnings({}) == []
