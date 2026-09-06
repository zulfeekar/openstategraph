"""A declared branch with no edge is a finding, whatever declares it.

`osg-agent-experience/76`. A router document — a `route.classifier` with
sixteen branches and fifteen mounts — had four branch out-ports with no edge.
`openstategraph validate` printed **VALID**, listed all sixteen branch names
under `Routes:`, and said nothing; the editor, opening the same file, showed
four diagnostics. Two doors, one document, opposite answers, and the CLI is the
door a coding agent trusts.

`60` had already registered `unwired-fallback` for the one port whose absence
was known to cost a run. The general case is the same defect: `_router_for`
falls through to the first *wired* destination when a decision names a branch
nothing was drawn from, so a run that takes an unwired branch quietly does some
other branch's work.

**Derived from the descriptor, never from a list of types.** The catalogue
marks a conditional out-port `branch: true` — that mark is what
`capacityRule` reads on the canvas and what `branch_fan_out` already reads
here — so a node type that grows a branch is asked this question by existing.
The test below asserts that by naming types the check was not written against.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from openstategraph.document_checks import FindingClass, document_findings

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "backend" / "openstategraph" / "examples"


def _classifier(edges: list[dict], *, extra_nodes: list[dict] | None = None) -> dict:
    return {
        "nodes": [
            {
                "id": "router1",
                "type": "route.classifier",
                "data": {
                    "branches": [
                        {"id": "b1", "name": "billing"},
                        {"id": "b2", "name": "shipping"},
                    ]
                },
            },
            {"id": "out1", "type": "io.output", "data": {}},
            *(extra_nodes or []),
        ],
        "edges": edges,
    }


WIRED_B1 = {
    "id": "e1",
    "source": {"nodeId": "router1", "portId": "branch:b1"},
    "target": {"nodeId": "out1", "portId": "text"},
}


def _branch_findings(document: dict) -> list:
    return [f for f in document_findings(document) if f.kind is FindingClass.UNWIRED_BRANCH]


class TestOneUnwiredBranchIsOneFinding:
    def test_it_is_a_finding(self) -> None:
        findings = _branch_findings(_classifier([WIRED_B1]))
        assert len(findings) == 1, findings
        assert findings[0].subject == "router1.branch:b2"

    def test_the_sentence_names_the_node_and_the_branch(self) -> None:
        message = _branch_findings(_classifier([WIRED_B1]))[0].message
        assert "router1" in message
        # The branch's own name, not only the port id: `shipping` is what the
        # author typed and what `Routes:` prints back at them.
        assert "shipping" in message, message

    def test_the_sentence_says_what_a_run_taking_it_would_do(self) -> None:
        """A router does not fall through any more (`osg-agent-experience/80`).

        The verdict takes the declared fallback, or the run stops at the
        node when none is declared — never another branch's work. `76`'s
        sentence said the old thing; this asserts the routing ending rather
        than the fall-through one, which the guard/approval tests below
        still get.
        """
        message = _branch_findings(_classifier([WIRED_B1]))[0].message
        assert "falls through" not in message, message
        assert "declared fallback" in message, message
        assert "stops at" in message, message

    def test_a_fully_wired_router_is_silent(self) -> None:
        wired_b2 = {
            "id": "e2",
            "source": {"nodeId": "router1", "portId": "branch:b2"},
            "target": {"nodeId": "out1", "portId": "text"},
        }
        assert _branch_findings(_classifier([WIRED_B1, wired_b2])) == []


class TestItIsAskedOfTheDescriptorRatherThanOfATypeName:
    """Types the check was not written against, asked by the same mark."""

    def test_a_guard_policys_blocked_branch(self) -> None:
        document = {
            "nodes": [
                {"id": "guard1", "type": "guard.policy", "data": {}},
                {"id": "out1", "type": "io.output", "data": {}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": {"nodeId": "guard1", "portId": "allowed"},
                    "target": {"nodeId": "out1", "portId": "text"},
                }
            ],
        }
        findings = _branch_findings(document)
        assert [f.subject for f in findings] == ["guard1.blocked"]
        # `guard.policy` is not a routing family (`osg-agent-experience/80`
        # only changed `route.classifier`/`route.check`): its unwired branch
        # still falls through, deliberately, and the sentence still says so.
        assert "falls through" in findings[0].message, findings[0].message

    def test_an_approvals_rejected_branch(self) -> None:
        document = {
            "nodes": [
                {"id": "ask1", "type": "human.approval", "data": {}},
                {"id": "out1", "type": "io.output", "data": {}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": {"nodeId": "ask1", "portId": "approved"},
                    "target": {"nodeId": "out1", "portId": "text"},
                }
            ],
        }
        findings = _branch_findings(document)
        assert [f.subject for f in findings] == ["ask1.rejected"]
        assert "falls through" in findings[0].message, findings[0].message


class TestTheRoutingFamiliesGetTheRoutingSentence:
    """`route.classifier` and `route.check` since `osg-agent-experience/80`.

    One document holding one of each, and one holding a non-routing
    conditional family, so the split is asserted rather than assumed
    (ticket 84's done-when).
    """

    def test_a_route_check_unwired_branch_gets_the_routing_sentence(self) -> None:
        document = {
            "nodes": [
                {
                    "id": "fork1",
                    "type": "route.check",
                    "data": {
                        "check": "needs_a_date_range",
                        "branches": [
                            {"id": "ask", "name": "ask"},
                            {"id": "answer", "name": "answer"},
                        ],
                    },
                },
                {"id": "out1", "type": "io.output", "data": {}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": {"nodeId": "fork1", "portId": "branch:ask"},
                    "target": {"nodeId": "out1", "portId": "text"},
                },
                {
                    "id": "e2",
                    "source": {"nodeId": "fork1", "portId": "fallback"},
                    "target": {"nodeId": "out1", "portId": "text"},
                },
            ],
        }
        findings = [f for f in _branch_findings(document) if f.subject == "fork1.branch:answer"]
        assert len(findings) == 1, findings
        assert "falls through" not in findings[0].message, findings[0].message
        assert "declared fallback" in findings[0].message, findings[0].message
        assert "stops at" in findings[0].message, findings[0].message


class TestItNeverSaysTheSameThingTwice:
    def test_an_unwired_fallback_stays_one_finding(self) -> None:
        """`60`'s id and sentence survive; this check does not repeat them.

        `fallback` carries `branch: true` like every other conditional
        out-port, so the general question reaches it — and answering it a
        second time would print two lines about one missing edge.
        """
        document = {
            "nodes": [
                {
                    "id": "fork1",
                    "type": "route.check",
                    "data": {
                        "check": "needs_a_date_range",
                        "branches": [{"id": "ask", "name": "ask"}],
                    },
                },
                {"id": "out1", "type": "io.output", "data": {}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": {"nodeId": "fork1", "portId": "branch:ask"},
                    "target": {"nodeId": "out1", "portId": "text"},
                }
            ],
        }
        about_fallback = [
            f for f in document_findings(document) if f.subject == "fork1.fallback"
        ]
        assert len(about_fallback) == 1, about_fallback
        assert about_fallback[0].kind is FindingClass.UNWIRED_FALLBACK

    def test_a_graders_unwired_revise_is_not_reported_here(self) -> None:
        """Already decided, and decided the other way.

        `Finding.UNWIRED_REVISE` is `REPORT_ONLY` on the argument that a
        grader-as-recorder is a legitimate document and the runtime publishes
        the identical observation as a report (`workflow-gallery` 50).
        Reporting it here would reverse that classification into an exit code
        without anybody deciding to.
        """
        document = {
            "nodes": [
                {"id": "grader1", "type": "route.grader", "data": {}},
                {"id": "out1", "type": "io.output", "data": {}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": {"nodeId": "grader1", "portId": "pass"},
                    "target": {"nodeId": "out1", "portId": "text"},
                }
            ],
        }
        assert _branch_findings(document) == []

    def test_the_mount_at_the_far_end_is_not_a_second_finding(self) -> None:
        """The absent edge is reported at the branch, once.

        The editor reports the same absence from the target side — *"<mount>
        needs an input"* — and both sentences are about one edge nobody drew.
        A door that printed both would hand a reader two problems to fix and
        one edge to draw.
        """
        mount = {
            "id": "mount1",
            "type": "workflow.subgraph",
            "data": {"slug": "child"},
        }
        document = _classifier([WIRED_B1], extra_nodes=[mount])
        assert [f.subject for f in _branch_findings(document)] == ["router1.branch:b2"]


class TestEveryShippedExampleStillValidates:
    def test_no_example_carries_an_unwired_branch(self) -> None:
        offenders: dict[str, list[str]] = {}
        for package in sorted(EXAMPLES.iterdir()):
            manifest = package / "workflow.json"
            if not manifest.is_file():
                continue
            document = json.loads(manifest.read_text(encoding="utf-8"))
            found = [f.subject for f in _branch_findings(document)]
            if found:
                offenders[package.name] = found
        assert offenders == {}, offenders

    def test_validate_exits_zero_for_every_example(self) -> None:
        failed: dict[str, str] = {}
        for package in sorted(EXAMPLES.iterdir()):
            if not (package / "workflow.json").is_file():
                continue
            result = subprocess.run(
                [sys.executable, "-m", "openstategraph.cli", "validate", str(package)],
                capture_output=True,
                text=True,
                cwd=REPO / "backend",
            )
            if result.returncode != 0:
                failed[package.name] = (result.stdout + result.stderr)[-600:]
        assert failed == {}, failed


class TestTheTwoDoorsDescribeOneAbsentEdge:
    """One missing edge, two ends, one sentence each — and neither says both.

    The ticket asked for the editor's diagnostic and the CLI's finding to
    share one sentence. They cannot be the *same* sentence, because they are
    written from opposite ends: the editor names the node that is starving
    (`required-inputs`, target side), and this door names the branch that goes
    nowhere (source side). What matters — and what the ticket's symptom
    actually was — is that neither door is silent and neither prints both.

    Pinned rather than argued, so the day somebody gives the editor a
    source-side rule as well, this fails and the "once, not twice" decision
    gets taken again instead of eroding.
    """

    RULE = REPO / "src" / "core" / "validation" / "WorkflowValidator.ts"

    def test_the_editor_still_speaks_from_the_target_side(self) -> None:
        source = self.RULE.read_text(encoding="utf-8")
        assert 'needs a "${port.label}" input' in source, (
            "the editor's target-side sentence moved; this door's source-side "
            "finding was written to be its other half"
        )

    def test_the_editor_has_no_source_side_rule_of_its_own(self) -> None:
        source = self.RULE.read_text(encoding="utf-8")
        assert "unwired-branch" not in source, (
            "an editor rule with this id would print the branch side beside the "
            "target side — two problems to fix and one edge to draw"
        )
