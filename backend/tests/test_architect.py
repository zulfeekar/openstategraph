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
        runtime_types = set(NodeRuntime(model=None)._builders) | {"workflow.subgraph"}
        assert runtime_types <= KNOWN_NODE_TYPES | {"input.markdown"}
        assert KNOWN_NODE_TYPES <= runtime_types

    def test_the_architects_own_document_validates(self) -> None:
        raw = (REPO / "workflows/workflow-architect/workflow.json").read_text()
        result = ValidateWorkflowTool().run(document=raw)
        assert result.error is None, result.error


class TestArchitectPackage:
    def test_it_can_see_what_already_exists(self) -> None:
        """An architect that cannot list the platform cannot reuse it.

        Its own grammar skill offers `workflow.subgraph` / `team.workflow` with
        `{"workflow": "<slug>"}` — a slug it had no way to learn, so the only
        mount it could compose was an invented one. Read-only listing and
        description are exactly the two facts that make that branch of the
        grammar usable, and they match this package's stated character:
        nothing here can save, run or mutate.
        """
        document = json.loads(
            (REPO / "workflows/workflow-architect/workflow.json").read_text()
        )["document"]
        by_type = {node["type"]: node["id"] for node in document["nodes"]}
        assert "tool.platform-list-workflows" in by_type
        assert "tool.platform-describe-workflow" in by_type

        # Bound to the agent, not merely present: a tool edge is a binding.
        bound = {
            edge["source"]["nodeId"]
            for edge in document["edges"]
            if edge["target"] == {"nodeId": "architect1", "portId": "tools"}
        }
        assert by_type["tool.platform-list-workflows"] in bound
        assert by_type["tool.platform-describe-workflow"] in bound

    def test_the_project_catalogue_has_a_shipped_consumer(self) -> None:
        """`ProjectKnowledgeBuilder` recognises a source from the wiring, and
        until now nothing shipped wired one — the feature had no consumer at
        all. The architect is the natural one, and this pins that the topics
        it grows are real packages rather than an empty set."""
        from openstategraph.knowledge_builders import ProjectKnowledgeBuilder

        package = REPO / "workflows/workflow-architect"
        document = json.loads((package / "workflow.json").read_text())["document"]
        discovery = ProjectKnowledgeBuilder().discover(package, document, REPO / "workflows")
        assert "chinook-assistant" in [topic.name for topic in discovery.topics]

    def test_hidden_and_routed_from_the_concierge(self) -> None:
        assert json.loads((REPO / "workflows/workflow-architect/workflow.json").read_text())["hidden"] is True
        concierge = json.loads((REPO / "workflows/concierge/workflow.json").read_text())["document"]
        router = next(n for n in concierge["nodes"] if n["id"] == "router1")
        assert any(b["id"] == "b-build" for b in router["data"]["branches"])
        assert any(n.get("data", {}).get("workflow") == "workflow-architect"
                   for n in concierge["nodes"])
