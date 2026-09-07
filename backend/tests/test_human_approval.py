"""Human-in-the-loop: `human.approval` pauses via `interrupt()`, resumes via `Command`.

Settled here as a real design decision, not left as an unspecified gap:
same node-decides/edge-dispatches split as the router and the grader — this
node decides `approved`/`rejected`, the compiler's conditional edge
dispatches on it — the difference being *who* decides (a human, resumed
with `Command(resume=...)`, instead of an LLM's own judgement).

Requires a checkpointer (`WorkflowCompiler.build`'s `checkpointer` param):
LangGraph raises at compile time for an `interrupt()`-containing graph with
none. `InMemorySaver` here is a *test* choice — these cases are about the
node's decide/dispatch behaviour, and an in-memory saver keeps them fast and
isolated. It is no longer what the server runs: ticket 05 made the API's
checkpointer durable by default, and `test_persisted_checkpointer.py` proves a
pause resumes across a full teardown.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


def approval_document() -> dict[str, Any]:
    """input -> agent -> human.approval -[approved]-> output-a
                                         -[rejected]-> output-b"""
    return {
        "version": 1,
        "name": "approval-proof",
        "nodes": [
            node("node:input.text-1", "input.text"),
            node("node:agent.llm-1", "agent.llm"),
            node("node:human.approval-1", "human.approval", message="OK to publish?"),
            node("node:output.formatted-1", "output.formatted"),
            node("node:output.formatted-2", "output.formatted"),
        ],
        "edges": [
            edge("node:input.text-1", "text", "node:agent.llm-1", "prompt"),
            edge("node:agent.llm-1", "result", "node:human.approval-1", "candidate"),
            edge("node:human.approval-1", "approved", "node:output.formatted-1", "result"),
            edge("node:human.approval-1", "rejected", "node:output.formatted-2", "result"),
        ],
    }


class TestCompilerDispatch:
    def test_declares_one_conditional_edge_per_decision(self) -> None:
        plan = WorkflowCompiler().plan(approval_document())
        assert plan.conditional["node:human.approval-1"] == {
            "approved": "node:output.formatted-1",
            "rejected": "node:output.formatted-2",
        }

    def test_both_branch_targets_have_an_incoming_edge_so_neither_is_a_bogus_entry(
        self,
    ) -> None:
        plan = WorkflowCompiler().plan(approval_document())
        assert "node:output.formatted-1" not in plan.entry
        assert "node:output.formatted-2" not in plan.entry


class TestRuntimeLifecycle:
    def test_the_run_pauses_at_the_approval_node(self) -> None:
        model = _fake_model("Draft answer")
        runtime = NodeRuntime(model=model)
        document = approval_document()
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )

        config = {"configurable": {"thread_id": "t-1"}}
        result = graph.invoke(
            {"question": "draft something", "attempts": 0, "decisions": {}, "outputs": {}},
            config,
        )

        assert "__interrupt__" in result
        payload = result["__interrupt__"][0].value
        assert payload["message"] == "OK to publish?"
        assert payload["candidate"] == "Draft answer"

    def test_resuming_with_approve_continues_to_the_approved_branch(self) -> None:
        model = _fake_model("Draft answer")
        runtime = NodeRuntime(model=model)
        document = approval_document()
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )

        config = {"configurable": {"thread_id": "t-2"}}
        graph.invoke(
            {"question": "draft something", "attempts": 0, "decisions": {}, "outputs": {}},
            config,
        )

        final = graph.invoke(Command(resume={"decision": "approve"}), config)

        assert "__interrupt__" not in final
        assert final["decisions"]["node:human.approval-1"] == "approved"
        assert final["answer"] == "Draft answer"

    def test_resuming_with_reject_routes_to_the_rejected_branch_with_feedback(
        self,
    ) -> None:
        model = _fake_model("Draft answer")
        runtime = NodeRuntime(model=model)
        document = approval_document()
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )

        config = {"configurable": {"thread_id": "t-3"}}
        graph.invoke(
            {"question": "draft something", "attempts": 0, "decisions": {}, "outputs": {}},
            config,
        )

        final = graph.invoke(
            Command(resume={"decision": "reject", "feedback": "Too casual."}), config
        )

        assert final["decisions"]["node:human.approval-1"] == "rejected"
        assert final["feedback"] == "Too casual."

    def test_each_thread_id_is_an_independent_pause(self) -> None:
        """Two concurrent chats must not cross-contaminate each other's pause."""
        # Two invocations happen on this one model (one agent call per
        # thread) — a single-answer fake would be exhausted after the first.
        model = _fake_model("Draft answer", "Draft answer")
        runtime = NodeRuntime(model=model)
        document = approval_document()
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )

        config_a = {"configurable": {"thread_id": "thread-a"}}
        config_b = {"configurable": {"thread_id": "thread-b"}}
        graph.invoke({"question": "q1", "attempts": 0, "decisions": {}, "outputs": {}}, config_a)
        graph.invoke({"question": "q2", "attempts": 0, "decisions": {}, "outputs": {}}, config_b)

        final_a = graph.invoke(Command(resume={"decision": "approve"}), config_a)
        final_b = graph.invoke(Command(resume={"decision": "reject", "feedback": "no"}), config_b)

        assert final_a["decisions"]["node:human.approval-1"] == "approved"
        assert final_b["decisions"]["node:human.approval-1"] == "rejected"


def _fake_model(*answers: str) -> Any:
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    return GenericFakeChatModel(messages=iter(answers or ["Draft answer"]))
