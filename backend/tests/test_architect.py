"""The Workflow Architect (ticket 69): compiler-as-tool + the hidden package."""

from __future__ import annotations

import json
from pathlib import Path

from openstategraph.prebuilt_architect import KNOWN_NODE_TYPES, ValidateWorkflowTool

REPO = Path(__file__).resolve().parent.parent.parent


class TestValidateWorkflowTool:
    def test_a_valid_document_reports_its_topology(self) -> None:
        doc = json.dumps({"version": 2, "name": "t", "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}}],
            "edges": [{"source": {"nodeId": "in1", "portId": "text"},
                       "target": {"nodeId": "out1", "portId": "result"}}]})
        result = ValidateWorkflowTool().run(document=doc)
        assert result.error is None
        assert "VALID" in result.content and "entry ['in1']" in result.content

    def test_bad_json_is_a_readable_failure(self) -> None:
        assert ValidateWorkflowTool().run(document="{nope").error is not None

    def test_an_unknown_node_type_is_named(self) -> None:
        doc = json.dumps({"nodes": [{"id": "x1", "type": "wat.nope", "data": {}}], "edges": []})
        result = ValidateWorkflowTool().run(document=doc)
        assert result.error is not None and "wat.nope" in result.error

    def test_known_types_stay_in_lockstep_with_the_runtime(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime
        runtime_types = set(NodeRuntime(model=None)._builders) | {"workflow.subgraph", "team.workflow"}
        assert runtime_types <= KNOWN_NODE_TYPES | {"input.markdown"}
        assert KNOWN_NODE_TYPES <= runtime_types

    def test_the_architects_own_document_validates(self) -> None:
        raw = (REPO / "workflows/workflow-architect/workflow.json").read_text()
        result = ValidateWorkflowTool().run(document=raw)
        assert result.error is None, result.error


class TestArchitectPackage:
    def test_hidden_and_routed_from_the_concierge(self) -> None:
        assert json.loads((REPO / "workflows/workflow-architect/workflow.json").read_text())["hidden"] is True
        concierge = json.loads((REPO / "workflows/concierge/workflow.json").read_text())["document"]
        router = next(n for n in concierge["nodes"] if n["id"] == "router1")
        assert any(b["id"] == "b-build" for b in router["data"]["branches"])
        assert any(n.get("data", {}).get("workflow") == "workflow-architect"
                   for n in concierge["nodes"])
