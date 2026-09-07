"""A conditional branch carries one edge, and fanning it out drops the rest.

`osg-agent-experience/38`. The try-folder session drew a grader's `revise` port
to fifteen lens agents' `feedback` ports — the obvious way to say *"send it back
to whichever lens answered"*. The document saved, `validate` printed VALID, the
package's own shape assertion stayed green, and the compiled plan held **one**
of the fifteen: `plan.conditional[node][branch]` is a dict keyed by branch, so
the last edge planned wins and the other fourteen are gone with nothing to
report the loss.

Three layers, because the defect crosses all three and a green test at the
wrong one is this repository's recorded trap:

- the **port**, which now declares the cardinality (`branch` implies
  `max_connections: 1`, resolved in `src/core/model/contracts/ports.ts` and
  published in `port_specs.json`);
- the **document**, checked here — `branch-fan-out`, naming the port and every
  edge that leaves it;
- the **plan**, pinned here too: the compiler still keeps one destination per
  branch, which is why the refusal has to stand in front of it rather than
  behind it.

The canvas layer is `src/core/validation/ConnectionValidator.test.ts`.

The second half is the acceptance `32` left open. `unknown_ports` passed any
port id beginning `branch:` because the catalogue publishes the *prefix* and
not the rows; so `branch:lens-9` on a router with three branches was a port
nothing declares, drawn, planned, and never mentioned. Whether the row exists
is knowable from the document's own `branches` field, so it is asked.
"""

from __future__ import annotations

from typing import Any

import pytest

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.document_checks import FindingClass, document_findings
from openstategraph.validation import validate_document


def _grader_fanning_out(destinations: int) -> dict[str, Any]:
    """One grader whose `revise` is drawn to `destinations` agents."""
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "data": {}},
        {"id": "grader1", "type": "route.grader", "data": {}},
        {"id": "out1", "type": "output.formatted", "data": {}},
    ]
    edges: list[dict[str, Any]] = [
        {
            "source": {"nodeId": "grader1", "portId": "pass"},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    ]
    for index in range(destinations):
        node_id = f"lens{index + 1}"
        nodes.append({"id": node_id, "type": "agent.llm", "data": {}})
        edges.append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": node_id, "portId": "prompt"},
            }
        )
        edges.append(
            {
                "source": {"nodeId": "grader1", "portId": "revise"},
                "target": {"nodeId": node_id, "portId": "feedback"},
            }
        )
    return {"version": 3, "name": "fan-out", "nodes": nodes, "edges": edges}


def _router(branch_ids: tuple[str, ...], drawn: str) -> dict[str, Any]:
    """A classifier configured with `branch_ids`, wired out of `drawn`."""
    return {
        "version": 3,
        "name": "router",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {
                "id": "router1",
                "type": "route.classifier",
                "data": {
                    "branches": [
                        {"id": branch_id, "name": branch_id} for branch_id in branch_ids
                    ]
                },
            },
            {"id": "a1", "type": "agent.llm", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "router1", "portId": "question"},
            },
            {
                "source": {"nodeId": "router1", "portId": drawn},
                "target": {"nodeId": "a1", "portId": "prompt"},
            },
        ],
    }


def _of_class(document: dict[str, Any], kind: FindingClass) -> list[str]:
    return [f.message for f in document_findings(document) if f.kind == kind]


class TestABranchDrawnTwice:
    def test_two_edges_from_one_revise_is_a_finding(self) -> None:
        messages = _of_class(_grader_fanning_out(2), FindingClass.BRANCH_FAN_OUT)
        assert len(messages) == 1
        assert "grader1" in messages[0] and "revise" in messages[0]

    def test_the_finding_names_every_edge_not_the_first_one_found(self) -> None:
        # Fifteen was the real number, and "one of your edges is wrong" is not
        # a sentence anybody can act on.
        messages = _of_class(_grader_fanning_out(15), FindingClass.BRANCH_FAN_OUT)
        assert len(messages) == 1
        for index in range(15):
            assert f"lens{index + 1}" in messages[0]

    def test_one_edge_from_a_branch_is_not_a_finding(self) -> None:
        assert _of_class(_grader_fanning_out(1), FindingClass.BRANCH_FAN_OUT) == []

    def test_the_document_is_refused(self) -> None:
        valid, findings = validate_document(_grader_fanning_out(2))
        assert valid is False
        assert any("revise" in finding for finding in findings)


class TestTheCompilerNeverSeesTwoEdgesForOneBranch:
    """Why the refusal stands in *front* of the compiler and not behind it.

    Nothing here asks the compiler to change: a conditional edge is one
    destination per branch in LangGraph as well as in this plan, so there is no
    second destination for it to keep. This pins the loss it cannot report, so
    that removing the document check cannot leave the silence unnoticed.
    """

    def test_the_plan_keeps_one_destination_for_fifteen_drawn_edges(self) -> None:
        document = _grader_fanning_out(15)
        plan = WorkflowCompiler().plan(document)
        drawn = [
            edge
            for edge in document["edges"]
            if edge["source"] == {"nodeId": "grader1", "portId": "revise"}
        ]
        assert len(drawn) == 15
        assert list(plan.conditional["grader1"]).count("revise") == 1

    def test_and_the_document_never_reaches_it_valid(self) -> None:
        valid, _ = validate_document(_grader_fanning_out(15))
        assert valid is False


class TestABranchPortNamingNoRow:
    def test_an_edge_on_a_branch_that_does_not_exist_is_an_unknown_port(self) -> None:
        document = _router(("b-billing", "b-technical"), "branch:b-nowhere")
        messages = _of_class(document, FindingClass.UNKNOWN_PORT)
        assert len(messages) == 1
        assert "branch:b-nowhere" in messages[0]

    def test_an_edge_on_a_configured_branch_is_not(self) -> None:
        document = _router(("b-billing", "b-technical"), "branch:b-billing")
        assert _of_class(document, FindingClass.UNKNOWN_PORT) == []


@pytest.mark.parametrize("kind", [FindingClass.BRANCH_FAN_OUT])
def test_the_class_is_spelled_for_a_terminal(kind: FindingClass) -> None:
    assert kind.value == "branch-fan-out"
