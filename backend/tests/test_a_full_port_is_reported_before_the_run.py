"""Fifteen edges into one in-port, and the refusal did not fire.

`osg-agent-experience/43`. The try project drew fifteen producers into a single
one-slot input, `validate` said VALID, `graph` drew it, and the first live run
answered with a node's own "nothing arrived here" text. `capacityRule` has
guarded that on the canvas since `workflow-gallery/64`; the document door had
no such rule, and a document written through MCP never passes a canvas.

The fixture is the try project's own document — `fixtures/workflows/warehouse-analyst/`,
scrubbed of the engagement's table names, already in the tree from
`osg-agent-experience/32`. Fifteen agents' `result` converge on one
`output.formatted.result`, whose cap is one.

**The count is producers, not links**, and that is what the check is really
about. Three of this repository's own shipped documents wire several router
branches into one slot on purpose — a router takes one branch, so those are
three links and one value. A check that counted links would refuse them, which
is why `TestTheShippedDocumentsAreNotAccused` is as much of this ticket as the
accusation is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph.document_checks import FindingClass, document_findings
from openstategraph.validation import validate_document

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "workflows"
EXAMPLES = Path(__file__).parents[1] / "openstategraph" / "examples"
WORKFLOWS = Path(__file__).parents[2] / "workflows"


def _document(manifest: Path) -> dict[str, Any]:
    payload = json.loads(manifest.read_text())
    document = payload.get("document", payload)
    assert isinstance(document, dict)
    return document


def _overfull(document: dict[str, Any], root: Path | None = None) -> list[str]:
    return [
        f.subject
        for f in document_findings(document, workflows_root=root)
        if f.kind == FindingClass.PORT_OVERFULL
    ]


class TestTheTryProjectsOwnDocument:
    @pytest.fixture(scope="class")
    def document(self) -> dict[str, Any]:
        return _document(FIXTURE_ROOT / "warehouse-analyst" / "workflow.json")

    def test_fifteen_edges_into_a_one_slot_input_is_a_finding(
        self, document: dict[str, Any]
    ) -> None:
        assert _overfull(document, FIXTURE_ROOT) == ["out1.result"]

    def test_the_finding_names_the_port_and_every_edge(
        self, document: dict[str, Any]
    ) -> None:
        message = next(
            f.message
            for f in document_findings(document, workflows_root=FIXTURE_ROOT)
            if f.kind == FindingClass.PORT_OVERFULL
        )
        assert "out1" in message and "result" in message
        for index in range(1, 16):
            assert f"lens{index}" in message

    def test_the_document_is_refused(self, document: dict[str, Any]) -> None:
        valid, findings = validate_document(document, workflows_root=FIXTURE_ROOT)
        assert valid is False
        assert any("out1" in finding and "result" in finding for finding in findings)


class TestTheCountIsProducersNotLinks:
    """A router's branches are one value however many links they are."""

    def _router_into_one_slot(self, branches: int) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = [
            {"id": "in1", "type": "input.text", "data": {}},
            {
                "id": "router1",
                "type": "route.classifier",
                "data": {
                    "branches": [
                        {"id": f"b{index}", "name": f"b{index}"} for index in range(branches)
                    ]
                },
            },
            {"id": "out1", "type": "output.formatted", "data": {}},
        ]
        edges: list[dict[str, Any]] = [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "router1", "portId": "question"},
            }
        ]
        for index in range(branches):
            node_id = f"a{index}"
            nodes.append({"id": node_id, "type": "agent.llm", "data": {}})
            edges.append(
                {
                    "source": {"nodeId": "router1", "portId": f"branch:b{index}"},
                    "target": {"nodeId": node_id, "portId": "prompt"},
                }
            )
            edges.append(
                {
                    "source": {"nodeId": node_id, "portId": "result"},
                    "target": {"nodeId": "out1", "portId": "result"},
                }
            )
        return {"version": 3, "name": "branches", "nodes": nodes, "edges": edges}

    def test_three_branches_converging_on_one_slot_are_not_a_finding(self) -> None:
        assert _overfull(self._router_into_one_slot(3)) == []

    def test_two_ungated_producers_on_one_slot_are(self) -> None:
        document = self._router_into_one_slot(2)
        # A third producer that no branch decides between: it runs whatever the
        # router chose, so it and the branch agents really do race.
        document["nodes"].append({"id": "loose", "type": "agent.llm", "data": {}})
        document["edges"].append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "loose", "portId": "prompt"},
            }
        )
        document["edges"].append(
            {
                "source": {"nodeId": "loose", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        )
        assert _overfull(document) == ["out1.result"]


class TestABusIsNeverOverfull:
    def test_many_tools_on_one_bus_are_not_a_finding(self) -> None:
        document = {
            "version": 3,
            "name": "bus",
            "nodes": [
                {"id": "a1", "type": "agent.llm", "data": {}},
                {"id": "t1", "type": "tool.web-search", "data": {}},
                {"id": "t2", "type": "tool.web-fetch", "data": {}},
            ],
            "edges": [
                {
                    "source": {"nodeId": "t1", "portId": "tool"},
                    "target": {"nodeId": "a1", "portId": "tools"},
                },
                {
                    "source": {"nodeId": "t2", "portId": "tool"},
                    "target": {"nodeId": "a1", "portId": "tools"},
                },
            ],
        }
        assert _overfull(document) == []


class TestTheShippedDocumentsAreNotAccused:
    """The half that decides whether the check can be trusted.

    Three of these converge several branches on one slot, which is exactly the
    shape a link count would have refused.
    """

    @pytest.mark.parametrize(
        "manifest",
        sorted(EXAMPLES.glob("*/workflow.json")),
        ids=lambda p: p.parent.name,
    )
    def test_the_example_has_no_overfull_port(self, manifest: Path) -> None:
        findings = _overfull(_document(manifest), EXAMPLES)
        assert findings == [], findings

    @pytest.mark.parametrize(
        "manifest",
        sorted(WORKFLOWS.glob("*/workflow.json")),
        ids=lambda p: p.parent.name,
    )
    def test_the_shipped_workflow_has_no_overfull_port(self, manifest: Path) -> None:
        findings = _overfull(_document(manifest), WORKFLOWS)
        assert findings == [], findings


def test_the_class_is_spelled_for_a_terminal() -> None:
    assert FindingClass.PORT_OVERFULL.value == "port-overfull"
