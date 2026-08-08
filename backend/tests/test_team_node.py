"""The Team node (ticket 56): `team.workflow` runs a team package as one step.

A Team compiles through the exact same path as `workflow.subgraph` — the type
exists for its contract (outcome on the card), not for new machinery. These
tests pin the aliasing and the scaffolded package's shape, because the
prebuilt template is the "minimum viable code" every prebuilt node owes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


from dyflow.compile.node_runtime import NodeRuntime, RunState
from dyflow.compile.workflow_compiler import WorkflowCompiler

REPO = Path(__file__).resolve().parent.parent.parent


def parent_doc(slug: str) -> dict:
    return {
        "version": 2,
        "name": "parent",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "team1", "type": "team.workflow", "data": {"workflow": slug}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "team1", "portId": "input"}},
            {"source": {"nodeId": "team1", "portId": "result"}, "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


class TestTeamCompilesAsSubgraph:
    def test_a_team_node_is_an_ordinary_graph_node(self) -> None:
        plan = WorkflowCompiler().plan(parent_doc("research-team"))
        assert "team1" in plan.nodes
        assert plan.entry == ["in1"] and plan.exits == ["out1"]

    def test_the_runtime_builds_a_team_through_the_subgraph_loader(self) -> None:
        """`team.workflow` must hit the same loader as `workflow.subgraph` —
        a missing loader is the readable error, not a passthrough."""
        runtime = NodeRuntime(model=None)
        doc = parent_doc("research-team")
        factory = runtime.factory(doc)
        run = factory("team1", {"id": "team1", "type": "team.workflow", "data": {"workflow": "nope"}},
                      WorkflowCompiler().plan(doc))
        update = run(RunState(question="q"))  # type: ignore[typeddict-item]
        assert update["outputs"]["team1"] == ""
        # The miss is recorded loudly — the API surfaces this as a warning.
        assert runtime.unresolved_subgraphs == ["nope"]


class TestScaffoldedTeamPackage:
    def test_the_shipped_research_team_is_a_valid_loop(self) -> None:
        doc = json.loads((REPO / "workflows/research-team/workflow.json").read_text())["document"]
        plan = WorkflowCompiler().plan(doc)
        assert plan.fan_out == {"lead1": ["member1"]}
        assert ("grader1", {"pass": "out1", "revise": "lead1"}) in [
            (src, dsts) for src, dsts in plan.conditional.items()
        ]
        assert plan.warnings == []

    def test_the_scaffold_refuses_an_existing_slug(self, tmp_path: Path) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts/new_team.py"), "research-team"],
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
        from dyflow.api.workflow_store import WorkflowStore
        store = WorkflowStore(REPO / "workflows")
        assert "concierge" not in [s.slug for s in store.list()]
        assert store.load("concierge")["name"] == "Concierge (gateway)"  # load() unwraps the envelope

    def test_the_concierge_compiles_with_all_five_routes(self) -> None:
        doc = json.loads((REPO / "workflows/concierge/workflow.json").read_text())["document"]
        plan = WorkflowCompiler().plan(doc)
        assert plan.conditional["router1"] == {
            "b-videogames": "wf-videogames", "b-music": "wf-music",
            "b-livedata": "wf-livedata", "b-build": "wf-architect",
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
        }
