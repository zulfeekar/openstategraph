"""`osg-agent-experience/51` — the report join reads both edge tables.

`every-workflow-green/27` gave `function.format_report` a fallback: when no
supervisor fan-out wrote `worker_results`, gather the `outputs` of whatever is
wired into the join. That fallback read `plan.edges`, which carries only
*static* edges.

A guard's `pass`, a grader's `pass` and an approval's `approved` compile to
*conditional* edges — they live in `plan.conditional`, keyed by source. So a
join fed by one of them saw nothing at all, fell through to its `empty` text,
and a wired, drawn, validated graph answered *"No results — nothing was
dispatched to this join"*. That sentence is what the first live run of a real
document produced.

The fix is the one the runtime can keep: gather from conditional sources
exactly as from static ones, through the single reader
`compile/upstream.py:upstream_sources`, which is what `_discovered_function`,
`_output`, `_guard_check` and the resolvers already did by hand. Refusing the
edge in `validate` was the alternative and was rejected — the platform already
lets a guard's `pass` land on `candidate` (the port accepts it, the canvas
draws it, and the same conditional edge feeds every other builder correctly),
so the honest defect is the join's reader, not the document.

Asked of the *node*, not of the plan: `osg-agent-experience/38`'s trap is a
green test one layer above the builder that carries the bug.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import NodeRuntime, RunState, RuntimeServices
from openstategraph.compile.workflow_compiler import CompiledPlan


def _join(plan: CompiledPlan, state: dict) -> str:
    runtime = NodeRuntime(services=RuntimeServices(model=None))
    node = {"id": "join1", "type": "function.format_report", "data": {"reportTitle": "Answer"}}
    run = runtime._format_report_function("join1", node, plan)
    return str((run(RunState(**state)) or {}).get("outputs", {}).get("join1", ""))


EMPTY = "nothing was dispatched to this join"


class TestAGuardsPassReachesTheJoin:
    def test_the_guards_candidate_is_reported(self) -> None:
        plan = CompiledPlan()
        plan.conditional = {"guard1": {"pass": "join1", "revise": "writer1"}}
        report = _join(plan, {"outputs": {"guard1": "The approved paragraph."}})
        assert "The approved paragraph." in report
        assert EMPTY not in report

    def test_a_conditional_and_a_static_source_both_arrive(self) -> None:
        plan = CompiledPlan()
        plan.edges = [("a-policy", "join1")]
        plan.conditional = {"guard1": {"pass": "join1"}}
        report = _join(
            plan,
            {"outputs": {"guard1": "Checked text.", "a-policy": "We review on Tuesdays."}},
        )
        assert "Checked text." in report
        assert "We review on Tuesdays." in report

    def test_a_branch_that_leads_elsewhere_is_not_a_source(self) -> None:
        """Strictness beside the tolerance: only the branch landing *here*."""
        plan = CompiledPlan()
        plan.conditional = {"guard1": {"pass": "somewhere-else", "revise": "writer1"}}
        report = _join(plan, {"outputs": {"guard1": "Not for this join."}})
        assert "Not for this join." not in report
        assert EMPTY in report


class TestTheEarlierBehaviourIsUnchanged:
    def test_worker_results_still_win_over_a_conditional_source(self) -> None:
        plan = CompiledPlan()
        plan.conditional = {"guard1": {"pass": "join1"}}
        report = _join(
            plan,
            {
                "worker_results": {"task-1": "from the worker"},
                "subtasks": {"lead1": [{"id": "task-1"}]},
                "outputs": {"guard1": "from the guard"},
            },
        )
        assert "from the worker" in report
        assert "from the guard" not in report

    def test_a_join_with_nothing_wired_still_says_so(self) -> None:
        assert EMPTY in _join(CompiledPlan(), {"outputs": {"stray": "unwired"}})


class TestTheTwoTablesAreGenuinelyDifferent:
    """The reason the defect existed: a guard's `pass` is not in `plan.edges`."""

    def test_a_guards_pass_edge_compiles_conditional(self) -> None:
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        document = {
            "nodes": [
                {"id": "in1", "type": "io.input", "data": {}},
                {"id": "guard1", "type": "guard.check", "data": {"rules": "Be polite."}},
                {
                    "id": "join1",
                    "type": "function.format_report",
                    "data": {"reportTitle": "Answer"},
                },
                {"id": "out1", "type": "io.output", "data": {}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "guard1", "portId": "candidate"},
                },
                {
                    "id": "e2",
                    "source": {"nodeId": "guard1", "portId": "pass"},
                    "target": {"nodeId": "join1", "portId": "candidate"},
                },
                {
                    "id": "e3",
                    "source": {"nodeId": "join1", "portId": "report"},
                    "target": {"nodeId": "out1", "portId": "result"},
                },
            ],
        }
        plan = WorkflowCompiler().plan(document)
        assert ("guard1", "join1") not in plan.edges
        assert plan.conditional.get("guard1", {}).get("pass") == "join1"
