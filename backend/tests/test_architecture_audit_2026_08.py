"""Architecture audit 2026-08 — regression pins for the gaps it found.

Each test class pins one mechanism from docs/decisions/architecture-audit-2026-08.md:

1. The turn-boundary RESET must clear *every* per-run scratch channel — the
   fan-out channels (`subtasks`, `worker_results`) were missed, so a
   checkpointed thread's second turn could blend a stale worker result (same
   `task-1` id, fresh plan) into the new report, or list a prior turn's task
   ids as "failed before reporting".
2. The orchestrator must apply the same feedback-trust rule as the agent:
   `feedback` is `keep_latest_nonempty`, so "" on pass can never clear it, and
   only feedback whose deciding node *currently* says revise/rejected may be
   folded into a replan.
3. The worker is an agent too: its per-node model override and its
   skills-context-as-context (not rules) composition must match `_agent`.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import (
    RESET,
    NodeRuntime,
    RunState,
    merge_decisions,
)
from openstategraph.compile.workflow_compiler import CompiledPlan


def _build(runtime: NodeRuntime, node: dict[str, Any], plan: CompiledPlan | None = None):
    plan = plan or CompiledPlan()
    return runtime.factory({"nodes": [node], "edges": []})(node["id"], node, plan)


class TestTurnResetCoversTheFanOutChannels:
    def test_the_input_node_resets_subtasks_and_worker_results(self) -> None:
        run = _build(
            NodeRuntime(model=None), {"id": "in1", "type": "input.text", "data": {}}
        )
        update = run(RunState(question="turn two"))  # type: ignore[typeddict-item]
        assert update["subtasks"] == {RESET: ""}
        assert update["worker_results"] == {RESET: ""}

    def test_the_reset_marker_actually_clears_a_stale_plan(self) -> None:
        stale = {"orch-1": [{"id": "task-1", "instruction": "old"}]}
        assert merge_decisions(stale, {RESET: ""}) == {}

    def test_a_mid_run_worker_write_is_not_clobbered(self) -> None:
        """RESET only ever comes from the input node at turn start; an ordinary
        merge keeps both sides."""
        merged = merge_decisions({"task-1": "kept"}, {"task-2": "new"})
        assert merged == {"task-1": "kept", "task-2": "new"}


class TestOrchestratorFeedbackTrust:
    """`feedback` survives a later pass (by the reducer's own design), so the
    orchestrator must only fold it into a replan while the deciding node still
    stands by it — the exact rule `_agent` already applies."""

    ORCH = {"id": "orch-1", "type": "orchestrate.supervisor", "data": {}}

    def _plan(self) -> CompiledPlan:
        plan = CompiledPlan()
        plan.conditional = {"grader-1": {"pass": "out-1", "revise": "orch-1"}}
        return plan

    def _subtasks(self, state: RunState) -> list[dict[str, Any]]:
        run = _build(NodeRuntime(model=None), dict(self.ORCH), self._plan())
        return run(state)["subtasks"]["orch-1"]

    def test_stale_feedback_after_a_pass_is_ignored(self) -> None:
        tasks = self._subtasks(
            RunState(  # type: ignore[typeddict-item]
                question="who is the best artist?",
                feedback="Your report missed the revenue table.",
                decisions={"grader-1": "pass"},
            )
        )
        assert all("rejected" not in t["instruction"] for t in tasks)

    def test_live_feedback_from_a_revising_grader_is_folded_in(self) -> None:
        tasks = self._subtasks(
            RunState(  # type: ignore[typeddict-item]
                question="who is the best artist?",
                feedback="Your report missed the revenue table.",
                decisions={"grader-1": "revise"},
            )
        )
        assert all("rejected" in t["instruction"] for t in tasks)

    def test_feedback_from_an_unrelated_decider_is_ignored(self) -> None:
        """A rejection on a different branch (whose edge does not target this
        orchestrator) must not pollute the replan."""
        plan = CompiledPlan()
        plan.conditional = {"approval-9": {"approved": "x", "rejected": "y"}}
        run = _build(NodeRuntime(model=None), dict(self.ORCH), plan)
        tasks = run(
            RunState(  # type: ignore[typeddict-item]
                question="who is the best artist?",
                feedback="No, do not send that email.",
                decisions={"approval-9": "rejected"},
            )
        )["subtasks"]["orch-1"]
        assert all("rejected" not in t["instruction"] for t in tasks)


class TestWorkerIsAnAgentToo:
    """The worker factory must honour the same contracts as `_agent`."""

    WORKER = {
        "id": "w1",
        "type": "orchestrate.worker",
        "data": {"model": "openai/gpt-test"},
    }

    def _captured(self, monkeypatch, runtime: NodeRuntime) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        class FakeNode:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

            def build(self) -> Any:
                class A:
                    def invoke(self, _payload: Any) -> dict[str, Any]:
                        return {"messages": []}

                return A()

        from openstategraph.abc import agent as agent_family

        monkeypatch.setattr(agent_family, "ReactAgentNode", FakeNode)
        run = _build(runtime, dict(self.WORKER))
        run(RunState(task_id="t1", task_instruction="do it"))  # type: ignore[typeddict-item]
        return captured

    def test_the_workers_own_model_selection_is_honoured(self, monkeypatch) -> None:
        override = object()
        monkeypatch.setattr(
            "langchain.chat_models.init_chat_model", lambda key: override
        )
        captured = self._captured(monkeypatch, NodeRuntime(model=object()))
        assert captured["model"] is override

    def test_skills_context_rides_as_context_not_rules(self, monkeypatch) -> None:
        """CLAUDE.md's prompt composition: generated context sits above the
        rules; concatenating it into `rules` let a developer's replace-mode
        semantics and the SystemPrompt ordering silently diverge."""
        runtime = NodeRuntime(model=object(), skills_context="House JOIN rules.")
        monkeypatch.setattr(
            "langchain.chat_models.init_chat_model", lambda key: object()
        )
        captured = self._captured(monkeypatch, runtime)
        assert captured["context"] == "House JOIN rules."
        # The worker's own directive is now the `default_rules` layer, so a
        # wired skill adds to it instead of deleting it (ticket 05). Either
        # way the ambient package skills stay context.
        assert "House JOIN rules." not in captured["default_rules"]
        assert "House JOIN rules." not in captured.get("rules", "")


class TestQuestionChannelIsSingleWriter:
    """`question` is a bare scalar with no reducer. That is only legal while
    exactly zero *nodes* write it — it arrives from the caller's invoke (and a
    subgraph mount's explicit mapping) alone. This pins that invariant so the
    channel gains a reducer the day someone makes a node write it."""

    def test_no_node_factory_writes_question(self) -> None:
        import inspect

        from openstategraph.compile import node_runtime

        source = inspect.getsource(node_runtime)
        # The single legal write is the subgraph mount's explicit input
        # mapping (`captured.invoke({"question": ...})`) — an invoke input,
        # not a state update returned by a node.
        assert source.count('"question":') == 1
