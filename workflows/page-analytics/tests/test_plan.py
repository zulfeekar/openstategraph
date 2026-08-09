"""Compile-plan pins for the full-capability reference workflow.

If the compiler ever stops producing this topology — three-worker fan-out,
the approval gate before the dispatcher, the email tool bound to the
dispatcher only — the platform's own comprehensive test is the first thing
that should fail, not the last.
"""

from __future__ import annotations

import json
from pathlib import Path

from openstategraph.compile.workflow_compiler import WorkflowCompiler

ROOT = Path(__file__).resolve().parents[2]


def _plan(slug: str):
    document = json.loads((ROOT / slug / "workflow.json").read_text())["document"]
    return WorkflowCompiler().plan(document)


class TestPageAnalyticsPlan:
    def test_single_entry_single_exit(self) -> None:
        plan = _plan("page-analytics")
        assert plan.entry == ["in1"]
        assert plan.exits == ["out1"]

    def test_supervisor_fans_out_to_three_archetypes(self) -> None:
        plan = _plan("page-analytics")
        assert sorted(plan.fan_out["lead1"]) == ["w-revenue", "w-traffic", "w-trends"]

    def test_email_is_bound_to_the_dispatcher_and_nothing_else(self) -> None:
        plan = _plan("page-analytics")
        holders = [n for n, tools in plan.tool_bindings.items() if "t-email" in tools]
        assert holders == ["dispatcher"]

    def test_every_analyst_shares_the_sql_bus(self) -> None:
        plan = _plan("page-analytics")
        for node in ("w-traffic", "w-revenue", "w-trends", "agent-metric"):
            assert {"t-list", "t-schema", "t-query"} <= set(plan.tool_bindings[node])

    def test_compiles_without_warnings(self) -> None:
        assert _plan("page-analytics").warnings == []

    def test_the_mounted_team_package_compiles_too(self) -> None:
        plan = _plan("chinook-metrics-team")
        assert plan.warnings == []
        assert plan.entry and plan.exits
