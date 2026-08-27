"""A graph whose nodes are half `def` and half `async def` is not a broken graph.

`async-first/06`. The whole shape of Phase D rests on one claim, which
`docs/decisions/async-seam.md` takes from LangGraph's own graph-api page —
node functions are wrapped in `RunnableLambda`, which "add batch and **async**
support to your function" — and therefore concludes that the migration can
land one family per commit rather than as a big bang.

The charter states it. Nothing in this repository ever ran it. A claim of that
weight, inherited rather than measured, is exactly the class of assumption this
project keeps paying for, so it is asserted here twice: once against LangGraph
directly, and once against a **real compiled workflow** whose agent node is
`async def` (migrated) and whose input and output nodes are still `def`.

The third and fourth tests are about the two things a silent migration would
break, and neither is visible in an answer:

- **Narration.** `report_progress` reaches the wire through
  `get_stream_writer()`, which is *context-local* — `launch-readiness/110` was
  a blank panel with nothing in the logs and two green suites. An async node
  body changes which context the call sees. The docs say `get_stream_writer`
  works in async on Python 3.11+ and not below; this repository is 3.13, and
  this is the test that says so out loud rather than trusting the version
  number.
- **Cancellation.** The reason the phase exists (`async-first/09`): under
  `astream`, cancelling the driving task stops an `async def` node body and
  does *not* stop a `def` one. Measured there with a 10 s node; asserted here
  cheaply, so `async-first/07` has a floor under it rather than a claim.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, TypedDict

import openstategraph.abc.agent as agent_module
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.progress import progress_report, report_progress

from conftest import RespondingModel


# --------------------------------------------------------------------------- #
# 1. LangGraph's own claim, run rather than quoted.
# --------------------------------------------------------------------------- #


class _Mixed(TypedDict):
    trail: list[str]


class TestLangGraphRunsBothKinds:
    def test_a_sync_node_and_an_async_node_run_in_one_graph(self) -> None:
        def older(state: _Mixed) -> dict[str, list[str]]:
            return {"trail": [*state["trail"], "sync"]}

        async def newer(state: _Mixed) -> dict[str, list[str]]:
            await asyncio.sleep(0)
            return {"trail": [*state["trail"], "async"]}

        graph = StateGraph(_Mixed)
        graph.add_node("older", older)
        graph.add_node("newer", newer)
        graph.add_edge(START, "older")
        graph.add_edge("older", "newer")
        graph.add_edge("newer", END)
        compiled = graph.compile()

        result = asyncio.run(compiled.ainvoke({"trail": []}))

        assert result["trail"] == ["sync", "async"]


# --------------------------------------------------------------------------- #
# 2. The same claim about *this* compiler, mid-migration.
# --------------------------------------------------------------------------- #


def _document() -> dict[str, Any]:
    """input.text -> agent.llm -> output.formatted.

    The agent is the migrated family; the input and output nodes are not, and
    are not going to be — they do no I/O, so migrating them would be
    measurable in nothing (the charter's own words about `_static_text`).
    """
    return {
        "version": 1,
        "name": "half-migrated",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "go"}},
            {"id": "a1", "type": "agent.llm", "position": {"x": 200, "y": 0}, "data": {}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "a1", "portId": "prompt"}},
            {"source": {"nodeId": "a1", "portId": "result"}, "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


class TestTheCompilersOwnHalfMigratedGraph:
    def test_it_runs_and_answers(self) -> None:
        document = _document()
        runtime = NodeRuntime(model=RespondingModel([], default="the answer"))
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        result = asyncio.run(graph.ainvoke({"messages": [], "question": "hello"}))

        assert result["outputs"]["a1"] == "the answer"
        # And the un-migrated nodes on either side of it did their work.
        assert result["outputs"]["in1"] == "hello"
        assert "the answer" in str(result.get("answer") or "")


# --------------------------------------------------------------------------- #
# 3. Narration still reaches the wire from an async node body.
# --------------------------------------------------------------------------- #


class _NarratingAgent:
    """A compiled agent that says something while it works."""

    async def ainvoke(self, _payload: dict) -> dict:
        assert report_progress("halfway", current=1, total=2) is True
        return {"messages": [AIMessage(content="the answer")]}


class _StubTier:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def build(self) -> _NarratingAgent:
        return _NarratingAgent()


class TestNarrationSurvivesTheMigration:
    def test_a_progress_report_from_an_async_agent_body_reaches_the_custom_channel(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda _tier: _StubTier)
        document = _document()
        runtime = NodeRuntime(model=RespondingModel([], default="unused"))
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        async def collect() -> list[Any]:
            seen: list[Any] = []
            async for part in graph.astream(
                {"messages": [], "question": "hello"},
                stream_mode=["custom"],
                subgraphs=True,
                version="v2",
            ):
                if part["type"] == "custom":
                    seen.append(progress_report(part["data"]))
            return seen

        reports = [r for r in asyncio.run(collect()) if r is not None]

        assert [r.message for r in reports] == ["halfway"]
        # Stamped by us from the ambient config, which is the half a changed
        # execution context would have quietly emptied.
        assert [r.node for r in reports] == ["a1"]


# --------------------------------------------------------------------------- #
# 4. And the thing the whole phase is for.
# --------------------------------------------------------------------------- #


class _Flag(TypedDict):
    x: str


def _graph_over(node: Any) -> Any:
    graph = StateGraph(_Flag)
    graph.add_node("slow", node)
    graph.add_edge(START, "slow")
    graph.add_edge("slow", END)
    return graph.compile()


class TestOnlyAnAsyncBodyIsCancelled:
    """Ticket 09's measurement, in miniature, so 07 has a floor under it."""

    def test_an_async_body_never_completes(self) -> None:
        started = threading.Event()
        completed = threading.Event()

        async def slow(_state: _Flag) -> dict[str, str]:
            started.set()
            await asyncio.sleep(5)
            completed.set()
            return {"x": "done"}

        compiled = _graph_over(slow)

        async def drive() -> None:
            async def pump() -> None:
                async for _ in compiled.astream({"x": ""}):
                    pass

            task = asyncio.create_task(pump())
            while not started.is_set():
                await asyncio.sleep(0.01)
            task.cancel()
            with_timeout = asyncio.wait_for(asyncio.shield(_swallow(task)), timeout=3)
            await with_timeout

        asyncio.run(drive())

        assert not completed.is_set()

    def test_a_sync_body_runs_to_completion_anyway(self) -> None:
        started = threading.Event()
        completed = threading.Event()

        def slow(_state: _Flag) -> dict[str, str]:
            started.set()
            time.sleep(1.0)
            completed.set()
            return {"x": "done"}

        compiled = _graph_over(slow)

        async def drive() -> None:
            async def pump() -> None:
                async for _ in compiled.astream({"x": ""}):
                    pass

            task = asyncio.create_task(pump())
            while not started.is_set():
                await asyncio.sleep(0.01)
            task.cancel()
            await _swallow(task)

        asyncio.run(drive())

        # The worker thread outlives the cancelled task — this is the second
        # row of ticket 09's table, and the reason `_static_text` first would
        # have been measurable in nothing.
        assert completed.wait(timeout=5.0)


async def _swallow(task: Any) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass
