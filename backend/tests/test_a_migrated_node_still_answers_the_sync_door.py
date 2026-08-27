"""An `async def` node body must not cost this product its synchronous doors.

`async-first/06`. The charter's coexistence fact — LangGraph wraps a `def`
node in `RunnableLambda`, so sync and async node bodies live in one graph — is
true and is proven next door, in
`tests/test_a_half_migrated_graph_still_runs.py`. It is also **not the whole
question**, and Phase D found the missing half by running:

    TypeError: No synchronous function provided to "n".
    Either initialize with a synchronous function or invoke via the async API
    (ainvoke, astream, etc.)

Coexistence is about nodes inside a graph. It says nothing about the *caller*.
An `async def` node makes the whole compiled graph async-only, and this
backend has four synchronous doors onto the same compiled object: the blocking
`/api/runs`, the MCP server, `CompiledWorkflow.run` (the library path a
package's own `tests/` uses), and the CLI. Migrating one node family without
this would have broken all four — 203 tests said so on the first run.

This is the same shape Phase A hit from the other side (`async-first/02`): one
object shared by transports that are not all async, bridged rather than
swapped. There the bridge supplied the checkpointer's async four over its sync
ones; here it supplies the sync door over the async body, in one place — the
compiler's own `add_node` call, the last thing between a node body and
LangGraph — so no family carries a second copy of its own body and no builder
has to remember.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import openstategraph.abc.agent as agent_module
from langchain_core.messages import AIMessage
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.progress import progress_report, report_progress

from conftest import RespondingModel


def _document() -> dict[str, Any]:
    return {
        "version": 1,
        "name": "sync-door",
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


class _NarratingAgent:
    async def ainvoke(self, _payload: dict) -> dict:
        assert report_progress("halfway") is True
        return {"messages": [AIMessage(content="the answer")]}


class _StubTier:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def build(self) -> _NarratingAgent:
        return _NarratingAgent()


class TestTheBlockingDoorStillRunsAMigratedNode:
    def test_a_graph_with_an_async_agent_answers_graph_invoke(self) -> None:
        document = _document()
        runtime = NodeRuntime(model=RespondingModel([], default="the answer"))
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        result = graph.invoke({"messages": [], "question": "hello"})

        assert result["outputs"]["a1"] == "the answer"

    def test_narration_reaches_the_wire_through_the_sync_door_too(
        self, monkeypatch
    ) -> None:
        """`get_stream_writer()` is context-local, and the sync door runs the
        body on a loop of its own. A `Task` copies the ambient context at
        creation, so the writer is still there — asserted, not assumed, because
        the failure mode is `launch-readiness/110`: a blank panel and a green
        suite."""
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda _tier: _StubTier)
        document = _document()
        runtime = NodeRuntime(model=RespondingModel([], default="unused"))
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        reports = [
            progress_report(part["data"])
            for part in graph.stream(
                {"messages": [], "question": "hello"},
                stream_mode=["custom"],
                subgraphs=True,
                version="v2",
            )
            if part["type"] == "custom"
        ]

        assert [r.message for r in reports if r] == ["halfway"]
        assert [r.node for r in reports if r] == ["a1"]


class TestTheBridgeIsAppliedWhereItIsNeededAndNowhereElse:
    def test_a_sync_body_is_handed_on_untouched(self) -> None:
        """A `def` node must stay a `def` node. Wrapping one would replace the
        `RunnableLambda` LangGraph makes for itself with one of ours, for no
        behaviour anybody asked for."""
        from openstategraph.compile.node_doors import with_both_doors

        def body(state: object) -> dict[str, Any]:
            return {"seen": state}

        assert with_both_doors(body) is body

    def test_an_async_body_arrives_with_both_doors(self) -> None:
        from openstategraph.compile.node_doors import with_both_doors

        async def body(state: object) -> dict[str, Any]:
            return {"seen": state}

        made = with_both_doors(body)

        assert inspect.iscoroutinefunction(made.afunc)
        assert callable(made.func) and not inspect.iscoroutinefunction(made.func)

    def test_the_two_doors_are_one_body(self) -> None:
        """Not two spellings of one node. The sync door runs the async body."""
        calls: list[str] = []

        async def body(state: object) -> dict[str, Any]:
            calls.append("body")
            return {"seen": state}

        from openstategraph.compile.node_doors import both_doors

        node = both_doors(body)

        assert asyncio.run(node.ainvoke({"a": 1})) == {"seen": {"a": 1}}
        assert node.invoke({"a": 2}) == {"seen": {"a": 2}}
        assert calls == ["body", "body"]


class TestASyncOnlySaverSurvivesAnAsyncNodeBody:
    """The second half of the same discovery, and the sharper half.

    Phase A found that `graph.astream()` calls a checkpointer's **async four
    only**, and bridged the server's `SqliteSaver` at the two streaming
    handlers — "on the two async doors only", because at that point nothing
    else could reach the async four.

    Phase D makes that reasoning expire. An `async def` node body invokes its
    own compiled agent through `ainvoke`, and a nested graph inherits the
    parent's checkpointer through the ambient config — so an **async** call on
    a sync-only saver now happens on the *synchronous* door, which was the one
    door the bridge deliberately did not cover:

        NotImplementedError: The SqliteSaver does not support async methods.
        Consider using AsyncSqliteSaver instead.

    Swallowed by the graph-wide error handler, so the run answered `''` and
    said nothing — the two-states-one-output shape again. The bridge therefore
    moves to the compiler, where every door passes: it is transparent to a sync
    caller by construction (`_AsyncCapableSaver` delegates the sync four one by
    one), so nothing a synchronous caller does changes.
    """

    def test_an_agent_runs_under_a_saver_that_has_no_async_methods(self) -> None:
        from langgraph.checkpoint.base import BaseCheckpointSaver
        from langgraph.checkpoint.memory import InMemorySaver

        class _SyncOnly(BaseCheckpointSaver):
            """A saver shaped like `SqliteSaver`: the sync four and no more."""

            def __init__(self) -> None:
                super().__init__()
                self._inner = InMemorySaver()

            def get_tuple(self, config: Any) -> Any:
                return self._inner.get_tuple(config)

            def put(self, config: Any, checkpoint: Any, metadata: Any, versions: Any) -> Any:
                return self._inner.put(config, checkpoint, metadata, versions)

            def put_writes(self, config: Any, writes: Any, task_id: str, task_path: str = "") -> Any:
                return self._inner.put_writes(config, writes, task_id, task_path)

            def list(self, config: Any, **kwargs: Any) -> Any:
                return self._inner.list(config, **kwargs)

        document = _document()
        runtime = NodeRuntime(model=RespondingModel([], default="the answer"))
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=_SyncOnly()
        )

        result = graph.invoke(
            {"messages": [], "question": "hello"},
            config={"configurable": {"thread_id": "t1"}},
        )

        assert result["outputs"]["a1"] == "the answer"
