"""Phase D, first family: the agent node's body is `async def`.

`async-first/06`. The map's promise is *stop means stop*, and ticket 09
measured where that can and cannot be delivered on the installed
`langgraph 1.2.10`:

| arm (10 s node, stop at t=3 s) | node body |
| --- | --- |
| `astream` + **sync** node + `task.cancel()` | completed anyway, in its worker thread |
| `astream` + **async** node + `task.cancel()` | **never completed** — genuinely cancelled |

So the cancellation win is per node, and only for nodes that are actually
long. `_agent` is the longest-running family in the compiler, which is why it
is migrated first rather than last — the opposite of the order a refactorer
naturally picks, exactly as `docs/decisions/async-seam.md` warned.

Two things are asserted here and neither is cosmetic:

- the body is a coroutine function, because a `def` body is what LangGraph
  hands to a worker thread, and a worker thread is what cannot be cancelled;
- it reaches the compiled agent through `ainvoke`, because an `async def`
  body that then blocks on `invoke()` is *worse* than the sync node it
  replaced — it blocks the event loop instead of a pool thread.

The returned update is unchanged, and that is the third assertion: this phase
buys cancellation and changes no answer.
"""

from __future__ import annotations

import asyncio
import inspect

import openstategraph.abc.agent as agent_module
from langchain_core.messages import AIMessage
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan

from conftest import any_chat_model


class _RecordingAgent:
    """A compiled agent that records which door the node body used."""

    def __init__(self) -> None:
        self.doors: list[str] = []
        self.payloads: list[dict] = []

    def invoke(self, payload: dict) -> dict:
        self.doors.append("invoke")
        self.payloads.append(payload)
        return {"messages": [AIMessage(content="answered")]}

    async def ainvoke(self, payload: dict) -> dict:
        self.doors.append("ainvoke")
        self.payloads.append(payload)
        return {"messages": [AIMessage(content="answered")]}


class _StubTier:
    """Stands in for whichever tier class `agent_node_for_tier` picks."""

    agent = _RecordingAgent()

    def __init__(self, **_kwargs: object) -> None:
        pass

    def build(self) -> _RecordingAgent:
        return _StubTier.agent


def _built(monkeypatch, data: dict | None = None):
    _StubTier.agent = _RecordingAgent()
    monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda _tier: _StubTier)
    runtime = NodeRuntime(model=any_chat_model())
    node = {"id": "a1", "type": "agent.llm", "data": data or {}}
    return runtime._agent("a1", node, CompiledPlan()), _StubTier.agent


class TestTheAgentBodyIsACoroutine:
    def test_the_factory_returns_an_async_def(self, monkeypatch) -> None:
        run, _agent = _built(monkeypatch)
        assert inspect.iscoroutinefunction(run)

    def test_it_reaches_the_agent_through_ainvoke(self, monkeypatch) -> None:
        run, agent = _built(monkeypatch)
        asyncio.run(run(RunState(question="q")))  # type: ignore[typeddict-item]
        assert agent.doors == ["ainvoke"]

    def test_the_update_is_what_it_always_was(self, monkeypatch) -> None:
        run, _agent = _built(monkeypatch)
        update = asyncio.run(run(RunState(question="q")))  # type: ignore[typeddict-item]
        assert update["outputs"] == {"a1": "answered"}
        assert update["answer"] == "answered"
        assert update["attempts"] == 1

    def test_a_model_less_agent_still_answers_without_touching_a_loop(
        self, monkeypatch
    ) -> None:
        """The early return has no I/O in it, and must not have grown any."""
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda _tier: _StubTier)
        runtime = NodeRuntime(model=None)
        run = runtime._agent("a1", {"id": "a1", "type": "agent.llm", "data": {}}, CompiledPlan())
        update = asyncio.run(run(RunState(question="q")))  # type: ignore[typeddict-item]
        assert update == {"outputs": {"a1": ""}, "attempts": 1}
