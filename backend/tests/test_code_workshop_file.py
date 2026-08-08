"""The Code Workshop workflow (ticket 43), proved against the real saved files.

Same stance as `test_intent_routed_demo_file.py`: every assertion here runs
against `workflows/code-workshop/workflow.json` and its review companion as
they exist on disk — the artifacts a developer actually edits — because only
that catches an authoring or serialization defect before a user does.

What the lifecycle test pins beyond compilation:

- the coder's six tools and the release agent's PR tool all resolve through
  real capability discovery (no silent parametric-knowledge degradation);
- the review stage is a **`workflow.subgraph`** node that receives the
  *coder's answer* over the grader's conditional `pass` edge — the exact
  hand-off `_subgraph`'s conditional-upstream fix exists for; a regression
  there makes the reviewer see the original question and this test fail;
- `human.approval` pauses the run with the review as the candidate, and a
  `Command(resume=...)` approval routes on to the release agent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from dyflow.api.capability_discovery import discover_tool_registry
from dyflow.compile.node_runtime import NodeRuntime, RunState
from dyflow.compile.workflow_compiler import WorkflowCompiler

WORKFLOWS_ROOT = Path(__file__).resolve().parent.parent.parent / "workflows"
WORKSHOP_DIR = WORKFLOWS_ROOT / "code-workshop"

RouteRule = tuple[Callable[[str], bool], str]


class RespondingModel(GenericFakeChatModel):
    """Predicate-routed fake — same shape as `test_intent_routed_demo_file`'s."""

    rules: list[RouteRule] = []
    default: str = "PASS"
    calls: list[str] = []

    def __init__(self, rules: list[RouteRule], default: str = "PASS"):
        super().__init__(messages=iter([]))
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "default", default)
        object.__setattr__(self, "calls", [])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        from langchain_core.outputs import ChatGeneration, ChatResult

        content = "\n".join(str(m.content) for m in messages)
        self.calls.append(content)
        answer = self.default
        for predicate, reply in self.rules:
            if predicate(content):
                answer = reply
                break
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001
        """The coder is `tier: "deep"` — `create_deep_agent` always binds its
        built-in tools, and the six workshop tools bind besides."""
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)


def load_document(slug: str) -> dict[str, Any]:
    payload = json.loads((WORKFLOWS_ROOT / slug / "workflow.json").read_text())
    return payload["document"]


def build_runtime(model: Any) -> NodeRuntime:
    return NodeRuntime(
        model=model,
        tools=discover_tool_registry(WORKSHOP_DIR, "code-workshop"),
        document_loader=load_document,
    )


class TestTheSavedDocumentsCompile:
    def test_no_compiler_warnings_in_either_file(self) -> None:
        for slug in ("code-workshop", "code-workshop-review"):
            plan = WorkflowCompiler().plan(load_document(slug))
            assert plan.warnings == [], f"{slug}: {plan.warnings}"

    def test_the_loops_and_gates_are_wired_as_designed(self) -> None:
        plan = WorkflowCompiler().plan(load_document("code-workshop"))
        assert plan.conditional["grader1"] == {"pass": "review1", "revise": "coder1"}
        assert plan.conditional["human1"] == {"approved": "release1", "rejected": "coder1"}
        assert len(plan.tool_bindings["coder1"]) == 6
        # The release manager grounds the PR body in evidence: the PR tool
        # plus read-only diff/tests (a live run confabulated file and test
        # names into PR.md before those two were bound).
        assert sorted(plan.tool_bindings["release1"]) == [
            "tool-diff",
            "tool-pr",
            "tool-tests",
        ]

    def test_every_tool_node_resolves_through_real_discovery(self) -> None:
        document = load_document("code-workshop")
        runtime = build_runtime(model=None)
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        assert graph is not None
        assert runtime.unresolved_tools == []
        assert runtime.unresolved_subgraphs == []
        assert runtime.unresolved_functions == []


class TestRuntimeLifecycle:
    """Coder → grader pass → review subgraph → approval pause → release."""

    TASK = "Fix the failing median test in the fixture project."

    def _model(self) -> RespondingModel:
        return RespondingModel(
            rules=[
                # Both graders judge with their own criteria in the prompt —
                # match those *first*, so a grader never trips the rules below.
                (lambda c: "must contain a unified diff" in c, "PASS"),
                (lambda c: "must quote or reference specific lines" in c, "PASS"),
                # The review subgraph's reviewer: only its prompt carries the
                # reviewer persona. It must be looking at the coder's answer.
                (
                    lambda c: "rigorous code reviewer" in c and "CODER_ANSWER" in c,
                    "REVIEW_OF_CODER_ANSWER\nVerdict: APPROVE — minimal and covered.",
                ),
                (lambda c: "release manager" in c, "PR_PACKAGED (dry run)"),
                (lambda c: "median" in c, "CODER_ANSWER: summary + diff + report"),
            ],
            default="PASS",
        )

    def _run_to_interrupt(self) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        document = load_document("code-workshop")
        runtime = build_runtime(self._model())
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        config = {"configurable": {"thread_id": "workshop-1"}, "recursion_limit": 60}
        result = graph.invoke(
            {"question": self.TASK, "attempts": 0, "decisions": {}, "outputs": {}},
            config,
        )
        return graph, config, result

    def test_the_run_pauses_at_approval_with_the_review_as_candidate(self) -> None:
        _, _, result = self._run_to_interrupt()
        assert "__interrupt__" in result
        payload = result["__interrupt__"][0].value
        # The candidate is the review subgraph's output — which itself proves
        # the subgraph reviewed the coder's answer (the reviewer rule only
        # fires when CODER_ANSWER is in its input): if the subgraph had been
        # handed the original question instead, the fake would have answered
        # its default and this marker could not appear.
        assert "REVIEW_OF_CODER_ANSWER" in payload["candidate"]

    def test_approval_resumes_into_the_release_agent(self) -> None:
        graph, config, _ = self._run_to_interrupt()
        result = graph.invoke(Command(resume={"decision": "approve"}), config)
        assert result["decisions"]["human1"] == "approved"
        assert result["answer"] == "PR_PACKAGED (dry run)"

    def test_rejection_carries_feedback_back_toward_the_coder(self) -> None:
        graph, config, _ = self._run_to_interrupt()
        result = graph.invoke(
            Command(resume={"decision": "reject", "feedback": "Split the fix differently."}),
            config,
        )
        assert result["decisions"]["human1"] == "rejected"
