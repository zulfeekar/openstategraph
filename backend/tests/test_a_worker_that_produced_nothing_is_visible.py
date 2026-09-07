"""A dispatched worker that produced nothing must reach the warnings channel.

From a live `archetype-orchestrator-report` run (2026-08-14,
`ollama:gpt-oss:120b-cloud`), the two-part day-one-access brief:

    # Onboarding plan
    ### task-1
    _(this member produced no result)_
    ### task-2
    I can't create a useful agenda without knowing who the onboarding is for…

with `warnings: []` and exit 0. `format_report`'s gap marker was the only
reason the miss was visible at all (`workflow-gallery` 18).

Two situations were indistinguishable downstream, and one of them was not
visible at all:

- **The worker ran and the model answered with nothing.** `_worker` writes
  `outputs[f"{node_id}#{task_id}"] = ""`, so `silent_node_warnings` names the
  node *and* the subtask id. That half already worked by the time this ticket
  was taken — pinned below so it stays working, at the **node** layer rather
  than by calling `silent_node_warnings` on a hand-built dict, which is the
  trap ticket 33 paid for (a fix wired into `_agent` and not `_worker`, with
  both of its tests green because neither asked a node anything).

- **No model was configured at all.** That branch returned only
  `{"worker_results": {task_id: ""}}` — no `outputs` entry — so the node was
  absent from the run's record entirely and *nothing*, not even the silent
  channel, could see it. That is the defect this file was written red for.

Both stay on the silent/report half deliberately: `silent_node_warnings`
argues it in as many words, and `cli.run_exit_code` reads `.failures`. A
worker that produced nothing is a report about how the answer was reached,
never a claim that the run failed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import CompiledPlan, silent_node_warnings

from conftest import any_chat_model, drive_node

WORKER_ID = "worker-research"
TASK_ID = "task-1"


def _worker_result(monkeypatch: pytest.MonkeyPatch, *, model: Any, said: str) -> dict[str, Any]:
    """Runs a real `agent.worker` factory whose loop returns `said`."""
    from openstategraph.abc import agent as agent_family

    class StubTier:
        def __init__(self, **_: Any) -> None: ...

        def build(self) -> Any:
            async def ainvoke(_invocation: Any) -> Any:
                return {"messages": [SimpleNamespace(content=said, tool_calls=[], type="ai")]}

            return SimpleNamespace(ainvoke=ainvoke)

    monkeypatch.setattr(agent_family, "ReactAgentNode", StubTier)

    node = {"id": WORKER_ID, "type": "orchestrate.worker", "data": {}}
    document = {"nodes": [node], "edges": []}
    plan = CompiledPlan(nodes=[WORKER_ID], edges=[], conditional={})
    runtime = NodeRuntime(model=model)
    run = runtime.factory(document)(WORKER_ID, node, plan)
    return drive_node(
        run,
        {
            "task_id": TASK_ID,
            "task_instruction": "List day-one access for a new engineer.",
            "outputs": {},
            "decisions": {},
            "messages": [],
        }
    )


class TestAWorkerThatSaidNothing:
    def test_the_empty_answer_is_recorded_against_node_and_subtask(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _worker_result(monkeypatch, model=any_chat_model(), said="")
        assert result["outputs"] == {f"{WORKER_ID}#{TASK_ID}": ""}

    def test_and_therefore_reaches_the_warnings_channel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _worker_result(monkeypatch, model=any_chat_model(), said="")
        warnings = silent_node_warnings(result["outputs"])
        # Both halves of the composite key still identify the step, but as the
        # two things they are rather than as one opaque id — `workflow-gallery`
        # 52 split the sentence into member and node.
        assert warnings
        assert WORKER_ID in warnings[0] and TASK_ID in warnings[0]

    def test_a_worker_that_answered_is_left_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _worker_result(monkeypatch, model=any_chat_model(), said="VPN, SSO, the repo.")
        assert result["worker_results"] == {TASK_ID: "VPN, SSO, the repo."}
        assert silent_node_warnings(result["outputs"]) == []


class TestAWorkerWithNoModelAtAll:
    def test_it_is_recorded_rather_than_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The red one. No `outputs` entry meant no surface could see it."""
        result = _worker_result(monkeypatch, model=None, said="unused")
        assert f"{WORKER_ID}#{TASK_ID}" in result["outputs"]

    def test_and_it_says_so_rather_than_looking_like_an_empty_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinguishable from the worker above, which is half the ticket.

        Both are reports; only one of them is a model that answered.
        """
        result = _worker_result(monkeypatch, model=None, said="unused")
        warnings = silent_node_warnings(result["outputs"])
        # Both halves of the composite key still identify the step, but as the
        # two things they are rather than as one opaque id — `workflow-gallery`
        # 52 split the sentence into member and node.
        assert warnings
        assert WORKER_ID in warnings[0] and TASK_ID in warnings[0]
        assert "no model" in warnings[0].lower()

    def test_the_join_still_sees_nothing_so_the_gap_marker_still_renders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`worker_results` is the join's input and must stay empty.

        Publishing an explanation there would hand `format_report` a sentence
        about our configuration as if it were the subtask's answer.
        """
        result = _worker_result(monkeypatch, model=None, said="unused")
        assert result["worker_results"] == {TASK_ID: ""}
