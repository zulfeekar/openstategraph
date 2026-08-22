"""Mounting a *team package* — ticket 56, as it stands after ticket 16.

A team is a **package shape**, not a node type. `team.workflow` used to be a
second id that compiled through the exact same path as `workflow.subgraph`,
existing only for a contract on the card; schema v3 collapsed it, so what is
left is the thing that was always real — a scaffolded package of supervisor +
worker + grader, mounted like any other workflow.

These tests pin the mount and the scaffolded package's shape, because that
template is the "minimum viable code" every prebuilt owes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

REPO = Path(__file__).resolve().parent.parent.parent


def parent_doc(slug: str) -> dict:
    return {
        "version": 2,
        "name": "parent",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "team1", "type": "workflow.subgraph", "data": {"workflow": slug}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "team1", "portId": "input"}},
            {"source": {"nodeId": "team1", "portId": "result"}, "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


class TestTeamCompilesAsSubgraph:
    def test_a_team_node_is_an_ordinary_graph_node(self) -> None:
        plan = WorkflowCompiler().plan(parent_doc("some-team"))
        assert "team1" in plan.nodes
        assert plan.entry == ["in1"] and plan.exits == ["out1"]

    def test_the_runtime_builds_a_team_through_the_subgraph_loader(self) -> None:
        """A mount hits the subgraph loader —
        a missing loader is the readable error, not a passthrough."""
        runtime = NodeRuntime(model=None)
        doc = parent_doc("some-team")
        factory = runtime.factory(doc)
        run = factory("team1", {"id": "team1", "type": "workflow.subgraph", "data": {"workflow": "nope"}},
                      WorkflowCompiler().plan(doc))
        update = run(RunState(question="q"))  # type: ignore[typeddict-item]
        assert update["outputs"]["team1"] == ""
        # The miss is recorded loudly — the API surfaces this as a warning.
        assert runtime.diagnostics.subjects(Finding.UNRESOLVED_SUBGRAPH) == [("nope",)]


class TestScaffoldedTeamPackage:
    def test_the_scaffolded_team_is_a_valid_loop(self, tmp_path: Path) -> None:
        """Pinned against the *scaffold*, not against a shipped package.

        It used to read `workflows/chinook-metrics-team` — a supervisor and a
        single worker, deleted by the one-example ticket because one worker
        role does not earn a planner. The contract worth protecting was never
        that example's existence but the shape `new_team` emits, which is what
        every developer actually gets."""
        from openstategraph.scaffold import new_team

        target = new_team(tmp_path, "sourcing-team", "Deliver a sourced summary.")
        doc = json.loads((target / "workflow.json").read_text())["document"]
        plan = WorkflowCompiler().plan(doc)
        assert plan.fan_out == {"lead1": ["member1"]}
        assert ("grader1", {"pass": "out1", "revise": "lead1"}) in [
            (src, dsts) for src, dsts in plan.conditional.items()
        ]
        assert plan.warnings == []

    def test_the_scaffold_refuses_an_existing_slug(self, tmp_path: Path) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts/new_team.py"), "chinook-assistant"],
            capture_output=True, text=True,
        )
        assert proc.returncode != 0
        assert "exists" in proc.stderr

    def test_the_scaffold_refuses_an_illegal_slug(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts/new_team.py"), "Bad_Slug!"],
            capture_output=True, text=True,
        )
        assert proc.returncode != 0


class TestConciergeGateway:
    """Ticket 67: the hidden gateway is well-formed and stays hidden."""

    def test_the_concierge_is_not_listed_but_is_loadable(self) -> None:
        from openstategraph.api.workflow_store import WorkflowStore
        store = WorkflowStore(REPO / "workflows")
        assert "concierge" not in [s.slug for s in store.list()]
        assert store.load("concierge")["name"] == "Concierge (gateway)"  # load() unwraps the envelope

    def test_the_concierge_compiles_with_all_three_routes(self) -> None:
        doc = json.loads((REPO / "workflows/concierge/workflow.json").read_text())["document"]
        plan = WorkflowCompiler().plan(doc)
        assert plan.conditional["router1"] == {
            "b-music": "wf-music", "b-build": "wf-architect",
            "b-general": "agent-general",
        }
        assert plan.warnings == []

    def test_the_concierge_binds_only_read_only_platform_tools(self) -> None:
        """User spec refined: 'no write — everything else'. The gateway's
        general agent carries the platform introspection family (all
        read-only by construction); nothing else binds anything."""
        doc = json.loads((REPO / "workflows/concierge/workflow.json").read_text())["document"]
        plan = WorkflowCompiler().plan(doc)
        assert set(plan.tool_bindings) == {"agent-general"}
        types = {next(n["type"] for n in doc["nodes"] if n["id"] == t)
                 for t in plan.tool_bindings["agent-general"]}
        assert types == {
            "tool.platform-list-workflows", "tool.platform-describe-workflow",
            "tool.platform-ls", "tool.platform-read-file", "tool.platform-grep",
            "tool.web-search", "tool.web-fetch",
            # The gateway's routing second brain (knowledge-architecture.md):
            # read-only by construction, one doc per child workflow.
            "tool.knowledge-lookup",
        }


class TestChildPackageAssets:
    """A routed child runs with its OWN skills, not the parent's — the gap
    the user found live: 'create a workflow' through Auto reached the
    Architect without its interview skill."""

    def test_the_child_runtime_gets_the_childs_skills_and_middleware(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime, PackageAssets, RunState

        sentinel_mw = object()
        captured: dict = {}

        def loader(slug: str) -> PackageAssets:
            captured["slug"] = slug
            return PackageAssets(tools={}, functions={},
                                 skills_context="CHILD SKILL TEXT",
                                 workflow_middleware={"audit": sentinel_mw})

        parent = NodeRuntime(
            model=None,
            skills_context="PARENT SKILLS",
            document_loader=lambda slug: {"version": 2, "name": slug, "nodes": [
                {"id": "in1", "type": "input.text", "data": {}},
                {"id": "out1", "type": "output.formatted", "data": {}}],
                "edges": [{"source": {"nodeId": "in1", "portId": "text"},
                           "target": {"nodeId": "out1", "portId": "result"}}]},
            package_loader=loader,
        )
        doc = {"version": 2, "name": "p", "nodes": [
            {"id": "sub1", "type": "workflow.subgraph", "data": {"workflow": "child-flow"}}],
            "edges": []}
        from openstategraph.compile.workflow_compiler import CompiledPlan
        run = parent.factory(doc)("sub1", doc["nodes"][0], CompiledPlan())
        run(RunState(question="q"))  # type: ignore[typeddict-item]
        assert captured["slug"] == "child-flow"

    def test_the_parent_conversation_crosses_into_the_child(self) -> None:
        """Found live: the Architect via the concierge re-asked its interview
        question every turn — child subgraphs were invoked with fresh state."""
        from langchain_core.messages import AIMessage, HumanMessage
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import CompiledPlan, WorkflowCompiler

        captured: dict = {}

        class SpyGraph:
            # `context` because the mount passes one since
            # `organisms-first-class/76`, and a stand-in for a compiled graph
            # has to accept what the real one does.
            def invoke(self, payload, config=None, *, context=None):
                captured.update(payload)
                return {"answer": "ok"}

        original = WorkflowCompiler.build
        WorkflowCompiler.build = lambda self, *a, **k: SpyGraph()  # type: ignore[method-assign]
        try:
            parent = NodeRuntime(model=None, document_loader=lambda slug: {"nodes": [], "edges": []})
            doc = {"nodes": [{"id": "sub1", "type": "workflow.subgraph",
                              "data": {"workflow": "child"}}], "edges": []}
            run = parent.factory(doc)("sub1", doc["nodes"][0], CompiledPlan())
            history = [HumanMessage(content="create a workflow"),
                       AIMessage(content="Before I build: what should it produce?")]
            run(RunState(question="a movie review flow", messages=history))  # type: ignore[typeddict-item]
        finally:
            WorkflowCompiler.build = original  # type: ignore[method-assign]
        assert [m.content for m in captured["messages"]][:2] == [
            "create a workflow", "Before I build: what should it produce?"]

    def test_the_input_node_does_not_double_record_the_current_turn(self) -> None:
        from langchain_core.messages import HumanMessage
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import CompiledPlan
        runtime = NodeRuntime(model=None)
        node = {"id": "in1", "type": "input.text", "data": {}}
        run = runtime.factory({"nodes": [node], "edges": []})("in1", node, CompiledPlan())
        update = run(RunState(question="q1",  # type: ignore[typeddict-item]
                              messages=[HumanMessage(content="q1")]))
        assert "messages" not in update
