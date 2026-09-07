"""Phase D, second family: the fan-out worker's body is `async def`.

`async-first/06`. The worker is the second-longest-running family and the one
where the abandoned-work bill is largest: it is the node a `Send` fan-out
dispatches N copies of, so one stop mid-fan-out abandons N model calls rather
than one. That is the ~75 s in `_stream_run`'s `GeneratorExit` handler, which
`async-first/09` relabelled — not latency a user waits through, but seconds of
model work billed after the run was stopped.

Same three assertions as the agent's, for the same reasons: the body is a
coroutine function (a `def` body is what LangGraph hands to a worker thread,
and a worker thread is what cannot be cancelled), it reaches its agent through
`ainvoke` (an `async def` body that then blocked on `invoke()` would hold the
event loop instead of a pool thread and still be uncancellable), and the update
it returns is unchanged.

The fourth is this family's own: **the fan-out still joins.** A worker's
update is keyed by task id into `worker_results`, which a reducer merges across
the supersteps `Send` scheduled — the one thing an async body could plausibly
disturb, and the one this family exists to do.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import openstategraph.abc.agent as agent_module
from langchain_core.messages import AIMessage
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan

from conftest import any_chat_model


class _RecordingAgent:
    def __init__(self) -> None:
        self.doors: list[str] = []

    def invoke(self, _payload: dict) -> dict:
        self.doors.append("invoke")
        return {"messages": [AIMessage(content="worked")]}

    async def ainvoke(self, _payload: dict) -> dict:
        self.doors.append("ainvoke")
        return {"messages": [AIMessage(content="worked")]}


class _StubTier:
    agent = _RecordingAgent()

    def __init__(self, **_kwargs: object) -> None:
        pass

    def build(self) -> _RecordingAgent:
        return _StubTier.agent


def _built(monkeypatch) -> tuple[Any, _RecordingAgent]:
    _StubTier.agent = _RecordingAgent()
    monkeypatch.setattr(agent_module, "ReactAgentNode", _StubTier)
    runtime = NodeRuntime(model=any_chat_model())
    node = {"id": "w1", "type": "orchestrate.worker", "data": {}}
    return runtime._worker("w1", node, CompiledPlan()), _StubTier.agent


class TestTheWorkerBodyIsACoroutine:
    def test_the_factory_returns_an_async_def(self, monkeypatch) -> None:
        run, _agent = _built(monkeypatch)
        assert inspect.iscoroutinefunction(run)

    def test_it_reaches_the_agent_through_ainvoke(self, monkeypatch) -> None:
        run, agent = _built(monkeypatch)
        asyncio.run(run(RunState(task_id="t1", task_instruction="do it")))  # type: ignore[typeddict-item]
        assert agent.doors == ["ainvoke"]

    def test_the_update_is_what_it_always_was(self, monkeypatch) -> None:
        run, _agent = _built(monkeypatch)
        update = asyncio.run(run(RunState(task_id="t1", task_instruction="do it")))  # type: ignore[typeddict-item]
        assert update["worker_results"] == {"t1": "worked"}
        assert update["outputs"] == {"w1#t1": "worked"}

    def test_a_model_less_worker_still_records_the_step(self, monkeypatch) -> None:
        """The early return has no I/O in it, and must not have grown any."""
        from openstategraph.compile.workflow_compiler import NO_MODEL_MARKER

        monkeypatch.setattr(agent_module, "ReactAgentNode", _StubTier)
        runtime = NodeRuntime(model=None)
        run = runtime._worker("w1", {"id": "w1", "data": {}}, CompiledPlan())
        update = asyncio.run(run(RunState(task_id="t1", task_instruction="do it")))  # type: ignore[typeddict-item]
        assert update == {
            "worker_results": {"t1": ""},
            "outputs": {"w1#t1": NO_MODEL_MARKER},
        }


class TestTheFanOutStillJoins:
    """The claim only a whole graph can make: N dispatched workers, one report.

    A `Send` fan-out schedules several copies of this one node, each writing
    `worker_results` under its own task id and merged by a reducer. If an async
    body disturbed that, every other test here would still pass.
    """

    def test_two_subtasks_both_reach_the_report(self, monkeypatch) -> None:
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        from conftest import RespondingModel

        monkeypatch.setattr(agent_module, "ReactAgentNode", _StubTier)
        _StubTier.agent = _RecordingAgent()

        def _node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
            return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}

        def _edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
            return {
                "source": {"nodeId": src, "portId": sp},
                "target": {"nodeId": dst, "portId": dp},
            }

        document = {
            "version": 1,
            "name": "fan-out",
            "nodes": [
                _node("in1", "input.text"),
                _node("lead1", "orchestrate.supervisor", maxSubtasks=4),
                _node("w1", "orchestrate.worker"),
                _node("report1", "function.format_report", reportTitle="Report"),
                _node("out1", "output.formatted"),
            ],
            "edges": [
                _edge("in1", "text", "lead1", "instruction"),
                _edge("lead1", "workers", "w1", "dispatch"),
                _edge("w1", "result", "report1", "candidate"),
                _edge("report1", "report", "out1", "result"),
            ],
        }
        runtime = NodeRuntime(model=RespondingModel([], default="ignored"))
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        result = asyncio.run(
            graph.ainvoke(
                {"question": "first thing; second thing", "attempts": 0, "decisions": {}, "outputs": {}},
                {"recursion_limit": 50},
            )
        )

        # Two subtasks were split, dispatched, and both came back.
        assert len(result["worker_results"]) == 2
        assert set(result["worker_results"].values()) == {"worked"}
