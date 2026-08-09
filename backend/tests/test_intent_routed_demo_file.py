"""End-to-end proof against the **real saved file**, not a hand-built document.

Every other test of this graph shape (`test_intent_routed_workflow.py`,
`test_orchestrator_graph.py`) constructs its own document directly in Python.
That is the right tool for pinning the compiler's behaviour, but it cannot
catch a defect in how the *editor* produces `workflow.json` — exactly the
category of bug found live this session: `RouterNode.ts`'s port-id slug
collapsed underscores into hyphens, so importing the real saved
`workflows/intent-routed-demo/workflow.json` silently dropped the
`off_topic` and `general_knowledge` branch edges every time, even though a
hand-built document with the same shape (correct by construction, never
touching the slug function at all) passed every existing test.

This file loads the actual file from disk and runs all four of its real
branches through the compiler with a scripted model — the same proof
`test_intent_routed_workflow.py` gives, but against the artifact a developer
actually authors and re-saves, which is the only thing that can catch a
frontend-authoring regression before a user does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


from openstategraph.compile.node_runtime import NodeRuntime, RunState, chinook_tool_registry
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from conftest import RespondingModel, RouteRule  # noqa: F401  (shared test double)

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent / "workflows" / "intent-routed-demo" / "workflow.json"
)

def load_real_document() -> dict[str, Any]:
    payload = json.loads(WORKFLOW_PATH.read_text())
    return payload["document"]


def run(question: str, model: Any) -> dict[str, Any]:
    document = load_real_document()
    runtime = NodeRuntime(model=model, tools=chinook_tool_registry())
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 60},
    )


class TestTheRealFileCompiles:
    def test_the_saved_document_has_no_compiler_warnings(self) -> None:
        # `plan.warnings` is the compiler's own signal for a malformed
        # document (an unresolved port spec, a dangling edge). A slug-bug
        # class of defect shows up upstream of this, as a *missing* edge the
        # frontend serializer silently dropped — which is exactly why this
        # file also runs every branch below rather than stopping here.
        plan = WorkflowCompiler().plan(load_real_document())
        assert plan.warnings == []

    def test_all_four_router_branches_are_wired(self) -> None:
        """Pins the exact regression: every branch the router declares must
        have a real conditional edge, not just three of four with the fourth
        silently absorbed by a port-id mismatch."""
        plan = WorkflowCompiler().plan(load_real_document())
        assert set(plan.conditional["router1"].keys()) == {
            "dataquery",
            "off_topic",
            "general_knowledge",
            "greeting",
        }


class TestAllFourBranchesRunEndToEnd:
    def test_dataquery_reaches_the_orchestrator_and_the_deep_grader(self) -> None:
        model = RespondingModel([(lambda c: "You are a router" in c, "dataquery")])
        final = run("Which genre earns the most revenue?", model)

        assert final["decisions"]["router1"] == "dataquery"
        assert final["decisions"]["grader-data"] == "pass"
        assert "agent-offtopic" not in final["outputs"]
        assert "agent-general" not in final["outputs"]
        assert "agent-greeting" not in final["outputs"]

    def test_off_topic_reaches_its_own_agent_and_grader(self) -> None:
        # The exact branch the slug bug silently dropped an edge for.
        model = RespondingModel(
            [(lambda c: "You are a router" in c, "off_topic")],
            default="Sorry, I can't help with that.",
        )
        final = run("Tell me a joke about clouds", model)

        assert final["decisions"]["router1"] == "off_topic"
        assert final["decisions"]["grader-offtopic"] == "pass"
        assert "agent-offtopic" in final["outputs"]
        assert "orch1" not in final["outputs"]

    def test_general_knowledge_reaches_its_own_agent_and_grader(self) -> None:
        # The other branch the slug bug silently dropped an edge for.
        model = RespondingModel(
            [(lambda c: "You are a router" in c, "general_knowledge")],
            default="Paris is the capital of France.",
        )
        final = run("What is the capital of France?", model)

        assert final["decisions"]["router1"] == "general_knowledge"
        assert final["decisions"]["grader-general"] == "pass"
        assert "agent-general" in final["outputs"]

    def test_greeting_reaches_its_own_agent_and_grader(self) -> None:
        model = RespondingModel(
            [(lambda c: "You are a router" in c, "greeting")], default="Hi there!"
        )
        final = run("Hello!", model)

        assert final["decisions"]["router1"] == "greeting"
        assert final["decisions"]["grader-greeting"] == "pass"
        assert "agent-greeting" in final["outputs"]
