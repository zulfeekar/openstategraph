"""A loop with no conditional step on it is a compile-time finding
(`launch-readiness` 177).

`CLAUDE.md` states the rule as settled fact — *"A cycle must contain at least
one conditional edge — an all-static cycle can never terminate"* — and until
this test nothing in the backend enforced it. `validate_document` answered
`(True, [])` and `openstategraph validate` printed `VALID` beside `Routes:
none`, which is the compiler saying in its own summary that the graph has no
conditional edge, next to the word that says it is fine.

**Where the rule lives, and why here.** The editor has `acyclicRule`, which
refuses to *draw* any cycle that does not close through a `feedback` port, and
`capacityRule`, which refuses the second producer such a cycle needs. Both are
draw-time gates in TypeScript, and a hand-written document, an
`openstategraph new` scaffold, an exported package, an MCP `compile_workflow`
call and the workflow-architect agent all reach the compiler without passing
either. `workflow.json` runs anywhere Python runs; this is the layer that set
is defined by.

It is deliberately **not** a mirror of `acyclicRule`. That rule is strictly
stronger — it refuses every non-feedback cycle, including one a router could
leave — because at drawing time the safe move is to refuse a gesture the user
can repeat differently. This check refuses only what is provably
non-terminating: a cycle every one of whose edges is always taken. The
backend's flagged set is a subset of the editor's, so the two can never
contradict each other, and neither restates the other's sentence.

**Reported, not raised**, on `plan.warnings` — the same channel and the same
argument as the unmapped-`pass` finding beside it (`launch-readiness` 66): a
document defect knowable from the topology alone, on the hard channel so
`validate` exits non-zero, rather than a refusal that would break any document
already carrying one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.validation import validate_document

from test_human_approval import edge, node

REPO = Path(__file__).resolve().parent.parent.parent
EXAMPLES = REPO / "backend" / "openstategraph" / "examples"
TEMPLATES = REPO / "backend" / "openstategraph" / "templates"
WORKFLOWS = REPO / "workflows"


def static_cycle_document() -> dict[str, Any]:
    """`.scratch/stress-2026-08-29/workflows/stress-bad-static-cycle`, rebuilt.

    Four nodes, no conditional edge: `in1 -> a -> b -> a`, with `a -> out1`
    hanging off the side so the document has an exit and reads as complete.
    """
    return {
        "version": 1,
        "name": "static-cycle",
        "nodes": [
            node("in1", "input.text"),
            node("a", "agent.llm"),
            node("b", "agent.llm"),
            node("out1", "output.formatted"),
        ],
        "edges": [
            edge("in1", "text", "a", "prompt"),
            edge("a", "result", "b", "prompt"),
            edge("b", "result", "a", "prompt"),
            edge("a", "result", "out1", "result"),
        ],
    }


def _cycle_warnings(plan: Any) -> list[str]:
    return [w for w in plan.warnings if "loop" in w and "budget" in w]


class TestTheDocumentIsReported:
    def test_the_plan_names_the_nodes_on_the_loop(self) -> None:
        plan = WorkflowCompiler().plan(static_cycle_document())
        found = _cycle_warnings(plan)
        assert found, plan.warnings
        message = found[0]
        assert "'a' -> 'b' -> 'a'" in message

    def test_validate_document_answers_invalid_and_says_why(self) -> None:
        valid, findings = validate_document(static_cycle_document())
        assert valid is False
        assert any("loop" in f for f in findings), findings

    def test_a_self_loop_is_the_same_finding(self) -> None:
        document = static_cycle_document()
        document["edges"] = [
            edge("in1", "text", "a", "prompt"),
            edge("a", "result", "a", "prompt"),
            edge("a", "result", "out1", "result"),
        ]
        document["nodes"] = [n for n in document["nodes"] if n["id"] != "b"]
        plan = WorkflowCompiler().plan(document)
        assert _cycle_warnings(plan), plan.warnings

    def test_a_send_dispatch_is_a_decision_and_the_replan_loop_is_accepted(
        self,
    ) -> None:
        """**Overturned, with the reason** — `the-cost-of-one-more` 07.

        This test used to assert the opposite, on the premise that
        `orchestrate.supervisor` "chooses how many tasks to run, never whether
        to leave the loop". The compiler contradicts it: a fan-out compiles to
        `add_conditional_edges`, and `_fan_out_router` returns `[]` for an
        orchestrator that planned no subtasks, which dispatches nothing and
        ends the lap. So the supervisor does choose whether to stop, and the
        document below — the supervisor replan loop, an evaluator-optimizer
        with a planner in the middle — was being *refused*: `plan.warnings` is
        the hard channel, so this was a valid workflow failing validation.

        The premise the test was written on is the thing that was wrong, so
        the test is rewritten rather than deleted: what it now protects is
        that a fan-out really is in the plan and the cycle really does close
        through it, and that neither is reported.
        `test_a_fan_out_is_not_an_edge_that_is_always_taken.py` carries the
        rest, including what the guard still catches.
        """
        document = {
            "version": 1,
            "name": "send-cycle",
            "nodes": [
                node("in1", "input.text"),
                node("sup1", "orchestrate.supervisor"),
                node("w1", "orchestrate.worker"),
                node("out1", "output.formatted"),
            ],
            "edges": [
                edge("in1", "text", "sup1", "instruction"),
                edge("sup1", "workers", "w1", "dispatch"),
                edge("w1", "result", "sup1", "instruction"),
                edge("sup1", "result", "out1", "result"),
            ],
        }
        plan = WorkflowCompiler().plan(document)
        assert plan.fan_out.get("sup1") == ["w1"], plan.fan_out
        assert ("w1", "sup1") in plan.edges
        assert not _cycle_warnings(plan), plan.warnings


class TestEveryConditionalStepLetsALoopOut:
    """What counts as conditional is read from `plan.conditional` — the
    compiler's own route table, the one `validate` already prints as
    `Routes:` — rather than from a second list of node types that would drift.
    """

    def test_a_grader_revise_loop_is_not_reported(self) -> None:
        document = static_cycle_document()
        document["nodes"][2] = node("b", "route.grader", criteria="No hedging.", maxAttempts=3)
        document["edges"] = [
            edge("in1", "text", "a", "prompt"),
            edge("a", "result", "b", "candidate"),
            edge("b", "revise", "a", "feedback"),
            edge("b", "pass", "out1", "result"),
        ]
        plan = WorkflowCompiler().plan(document)
        assert not _cycle_warnings(plan), plan.warnings

    def test_a_guard_check_revise_loop_is_not_reported(self) -> None:
        document = static_cycle_document()
        document["nodes"][2] = node("b", "guard.check", check="flag_short")
        document["edges"] = [
            edge("in1", "text", "a", "prompt"),
            edge("a", "result", "b", "candidate"),
            edge("b", "revise", "a", "feedback"),
            edge("b", "pass", "out1", "result"),
        ]
        plan = WorkflowCompiler().plan(document)
        assert not _cycle_warnings(plan), plan.warnings

    def test_a_router_on_the_loop_is_not_reported(self) -> None:
        document = {
            "version": 1,
            "name": "routed-cycle",
            "nodes": [
                node("in1", "input.text"),
                node("a", "agent.llm"),
                node(
                    "r1",
                    "route.classifier",
                    branches=[{"id": "again", "name": "Again"}, {"id": "done", "name": "Done"}],
                ),
                node("out1", "output.formatted"),
            ],
            "edges": [
                edge("in1", "text", "a", "prompt"),
                edge("a", "result", "r1", "question"),
                edge("r1", "branch:again", "a", "prompt"),
                edge("r1", "branch:done", "out1", "result"),
            ],
        }
        plan = WorkflowCompiler().plan(document)
        assert not _cycle_warnings(plan), plan.warnings


class TestNothingShippedIsNewlyFlagged:
    """The four cyclic examples the ticket names, and then every package on
    disk — the check may not turn a document that ships today into a problem.
    """

    def test_the_four_cyclic_examples_still_pass(self) -> None:
        for slug in (
            "fanout-in-a-loop",
            "evaluator-optimizer",
            "two-stage-double-loop",
            "budget-exhaustion",
        ):
            document = json.loads((EXAMPLES / slug / "workflow.json").read_text())
            document = document.get("document", document)
            plan = WorkflowCompiler().plan(document)
            assert not _cycle_warnings(plan), (slug, plan.warnings)

    def test_no_shipped_package_or_template_is_flagged(self) -> None:
        flagged: list[str] = []
        for root in (EXAMPLES, TEMPLATES, WORKFLOWS):
            for manifest in sorted(root.glob("*/workflow.json")):
                document = json.loads(manifest.read_text())
                document = document.get("document", document)
                plan = WorkflowCompiler().plan(document)
                if _cycle_warnings(plan):
                    flagged.append(manifest.parent.name)
        assert flagged == []
