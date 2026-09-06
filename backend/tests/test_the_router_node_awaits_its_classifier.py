"""The router's body is `async def` and awaits `aclassify`.

`async-first/14`, second of the two rungs `05` built and nothing reached. The
grader's file carries the argument in full; this is the same finding for the
other ladder, and it needs its own file because it has its own whole-graph
claim: a router's decision is consumed by a *conditional edge*, and a body that
wrote the right dict at the wrong moment would dispatch nowhere.

Measured against this tree before the migration, on the graph below with a
router model that sleeps five seconds: the stream stopped in under a
millisecond and the classification's model call **ran to completion anyway**.
Short is not the same as cancellable, and the router is the node every turn
starts with.

The one shape that must keep asking no model at all is the replay: a router
handed a trusted `revise` re-dispatches to the branch its own last decision
named rather than reclassifying (`workflow-gallery` 48), and that is a model
call not made rather than a model call awaited.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import Any

# The router family moved to `compile/nodes/router.py` (`docs-and-gaps/03`) and
# the substitutions below moved with it. `node_runtime` still re-exports
# `Router`, so patching it there would keep passing while binding a name the
# builder no longer reads — a substitution that proves nothing.
import openstategraph.compile.nodes.router as router_module
from openstategraph.abc.router import Classification, Router
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan, WorkflowCompiler
from openstategraph.progress import progress_report, report_progress

from conftest import RespondingModel

ROUTER = lambda content: "You are a router" in content  # noqa: E731
GRADER = lambda content: "You are a grader" in content  # noqa: E731


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _RecordingRouter(Router):
    """Records which door of the ladder the node reached it through.

    Both doors written out, so neither is `abc/async_doors.py`'s bridge.
    """

    doors: list[str] = []

    def classify(self, question: str) -> Classification:
        _RecordingRouter.doors.append("classify")
        return super().classify(question)

    async def aclassify(self, question: str) -> Classification:
        _RecordingRouter.doors.append("aclassify")
        return await super().aclassify(question)


BRANCHES = [{"id": "b-billing", "name": "billing"}, {"id": "b-tech", "name": "technical"}]


def _plan() -> CompiledPlan:
    plan = CompiledPlan()
    plan.edges.append(("in1", "r1"))
    plan.conditional["r1"] = {"b-billing": "a-billing", "b-tech": "a-tech"}
    return plan


def _built(monkeypatch: Any, model: Any = None, **data: Any) -> Any:
    _RecordingRouter.doors = []
    monkeypatch.setattr(router_module, "Router", _RecordingRouter)
    runtime = NodeRuntime(model=model or RespondingModel([], default="billing"))
    node = {
        "id": "r1",
        "type": "route.classifier",
        "data": {"branches": BRANCHES, **data},
    }
    return runtime._router("r1", node, _plan())


def _state(**extra: Any) -> RunState:
    base: dict[str, Any] = {
        "messages": [],
        "question": "my invoice is wrong",
        "attempts": 0,
        "decisions": {},
        "outputs": {},
    }
    base.update(extra)
    return RunState(**base)  # type: ignore[typeddict-item]


def _node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": sp},
        "target": {"nodeId": dst, "portId": dp},
    }


def _document() -> dict[str, Any]:
    """input -> router -> one of two desks -> output."""
    return {
        "version": 1,
        "name": "triaged",
        "nodes": [
            _node("in1", "input.text"),
            _node("r1", "route.classifier", branches=BRANCHES, fallback="technical"),
            _node("a-billing", "agent.llm", systemPrompt="You answer billing tickets."),
            _node("a-tech", "agent.llm", systemPrompt="You answer technical tickets."),
            _node("out1", "output.formatted"),
        ],
        "edges": [
            _edge("in1", "text", "r1", "question"),
            _edge("r1", "branch:b-billing", "a-billing", "prompt"),
            _edge("r1", "branch:b-tech", "a-tech", "prompt"),
            _edge("a-billing", "result", "out1", "result"),
            _edge("a-tech", "result", "out1", "result"),
        ],
    }


def _payload() -> dict[str, Any]:
    return {
        "messages": [],
        "question": "my invoice is wrong",
        "attempts": 0,
        "decisions": {},
        "outputs": {},
    }


def _classifying(answer: str = "billing", desk: str = "the billing desk") -> RespondingModel:
    return RespondingModel([(ROUTER, answer)], default=desk)


# --------------------------------------------------------------------------- #
# 1-3. The three claims every migrated family makes.
# --------------------------------------------------------------------------- #


class TestTheRouterBodyIsACoroutine:
    def test_the_factory_returns_an_async_def(self, monkeypatch: Any) -> None:
        assert inspect.iscoroutinefunction(_built(monkeypatch))

    def test_it_reaches_its_ladder_through_aclassify(self, monkeypatch: Any) -> None:
        """The whole ticket in one assertion for this family."""
        run = _built(monkeypatch, model=_classifying())
        asyncio.run(run(_state()))
        assert _RecordingRouter.doors == ["aclassify"]

    def test_a_replayed_revision_asks_no_model_at_all(self, monkeypatch: Any) -> None:
        """The short-circuit that must survive the migration untouched.

        `workflow-gallery` 48: a trusted `revise` re-dispatches to the branch
        this router's own last decision named. Reclassifying would be legal and
        wrong — the model is not deterministic, so a fresh answer could hand
        the grader's correction to a desk that never saw the question. An async
        body that awaited first and short-circuited second would pass every
        other assertion here.
        """
        _RecordingRouter.doors = []
        monkeypatch.setattr(router_module, "Router", _RecordingRouter)
        runtime = NodeRuntime(model=_classifying())
        node = {
            "id": "r1",
            "type": "route.classifier",
            "data": {"branches": BRANCHES},
        }
        plan = _plan()
        plan.edges.append(("g1", "r1"))
        plan.conditional["g1"] = {"revise": "r1", "pass": "out1"}
        run = runtime._router("r1", node, plan)

        update = asyncio.run(
            run(_state(decisions={"g1": "revise", "r1": "b-tech"}))
        )

        assert _RecordingRouter.doors == []
        assert update["decisions"] == {"r1": "b-tech"}


class TestTheUpdateIsWhatItAlwaysWas:
    def test_a_classification_writes_the_stable_id_not_the_name(
        self, monkeypatch: Any
    ) -> None:
        """`route_key`, which is the one place name-to-port mapping lives."""
        run = _built(monkeypatch, model=_classifying("billing"))
        update = asyncio.run(run(_state()))

        assert update["decisions"] == {"r1": "b-billing"}
        assert update["outputs"] == {"r1": "my invoice is wrong"}
        # One row, not no row (`launch-readiness/175`). This used to assert
        # `"routes" not in update`, on the argument that a `best`-mode router
        # had nothing extra to say — and it left every door unable to tell a
        # router that took one branch from one that reports no branches at
        # all. The dispatch is unmoved either way: the conditional edge
        # unwraps a one-item list back to a plain label.
        assert update["routes"] == {"r1": ["b-billing"]}

    def test_match_all_still_writes_every_branch_it_matched(
        self, monkeypatch: Any
    ) -> None:
        run = _built(
            monkeypatch, model=_classifying("billing, technical"), matchMode="all"
        )
        update = asyncio.run(run(_state()))

        assert update["routes"] == {"r1": ["b-billing", "b-tech"]}

    def test_an_unmatched_answer_still_falls_back(self, monkeypatch: Any) -> None:
        run = _built(
            monkeypatch, model=_classifying("something else"), fallback="technical"
        )
        update = asyncio.run(run(_state()))

        assert update["decisions"] == {"r1": "b-tech"}


class TestTheConditionalEdgeStillDispatches:
    """The claim only a whole graph can make.

    The router *decides*; the compiler's conditional edge *dispatches* on the
    `decisions` entry it wrote. An async body that wrote the same dict a
    superstep later would pass every test above and route nowhere.
    """

    def _graph(self, model: Any) -> Any:
        runtime = NodeRuntime(model=model)
        document = _document()
        return WorkflowCompiler().build(document, RunState, runtime.factory(document))

    def test_the_named_desk_is_the_one_that_answers(self) -> None:
        result = asyncio.run(
            self._graph(_classifying("billing", "the billing desk")).ainvoke(
                _payload(), {"recursion_limit": 50}
            )
        )

        assert result["decisions"]["r1"] == "b-billing"
        assert result["outputs"].get("a-billing") == "the billing desk"
        assert "a-tech" not in result["outputs"]

    def test_the_same_graph_still_answers_the_sync_door(self) -> None:
        """`compile/node_doors.py`. Not cancellable, and preserved anyway for
        the blocking `/api/runs`, the MCP server, `CompiledWorkflow.run` and
        the CLI."""
        result = self._graph(_classifying("billing", "the billing desk")).invoke(
            _payload(), {"recursion_limit": 50}
        )

        assert result["decisions"]["r1"] == "b-billing"


# --------------------------------------------------------------------------- #
# 4. Narration, on the wire rather than in a call.
# --------------------------------------------------------------------------- #


class _NarratingAsyncRouter(Router):
    async def aclassify(self, question: str) -> Classification:
        assert report_progress("classifying") is True
        return await super().aclassify(question)


class _NarratingSyncRouter(Router):
    """Only `classify`, so `aclassify` is the ladder's installed thread door.

    The arm that could genuinely lose the writer: `get_stream_writer()` is
    context-local and this body runs in a worker thread.
    """

    def classify(self, question: str) -> Classification:
        assert report_progress("classifying") is True
        return Classification(branch="billing", reason="stubbed")


def _narration_from(monkeypatch: Any, router_cls: Any, door: str) -> list[Any]:
    monkeypatch.setattr(router_module, "Router", router_cls)
    runtime = NodeRuntime(model=_classifying("billing", "the billing desk"))
    document = _document()
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    config = {"recursion_limit": 50}

    if door == "sync":
        parts = list(
            graph.stream(
                _payload(), config, stream_mode=["custom"], subgraphs=True, version="v2"
            )
        )
    else:

        async def collect() -> list[Any]:
            seen = []
            async for part in graph.astream(
                _payload(), config, stream_mode=["custom"], subgraphs=True, version="v2"
            ):
                seen.append(part)
            return seen

        parts = asyncio.run(collect())

    return [
        r
        for r in (progress_report(p["data"]) for p in parts if p["type"] == "custom")
        if r is not None
    ]


class TestNarrationFromTheRouterReachesTheWire:
    """Selected **by the node stamp** — the desk downstream narrates too, and
    an unstamped frame would be absent from the list rather than merely wrong
    (`async-first/07`)."""

    def test_an_awaited_classification_still_narrates(self, monkeypatch: Any) -> None:
        reports = _narration_from(monkeypatch, _NarratingAsyncRouter, "async")

        assert [r.message for r in reports if r.node == "r1"] == ["classifying"]

    def test_a_thread_doored_classification_still_narrates(
        self, monkeypatch: Any
    ) -> None:
        reports = _narration_from(monkeypatch, _NarratingSyncRouter, "async")

        assert [r.message for r in reports if r.node == "r1"] == ["classifying"]

    def test_it_narrates_through_the_sync_door_too(self, monkeypatch: Any) -> None:
        reports = _narration_from(monkeypatch, _NarratingAsyncRouter, "sync")

        assert [r.message for r in reports if r.node == "r1"] == ["classifying"]


# --------------------------------------------------------------------------- #
# 5. The reason the phase exists, for this family.
# --------------------------------------------------------------------------- #


_started = threading.Event()
_completed = threading.Event()


class _SlowAsyncRouter(Router):
    async def aclassify(self, question: str) -> Classification:
        _started.set()
        await asyncio.sleep(5)
        _completed.set()
        return Classification(branch="billing", reason="stubbed")


class _SlowSyncRouter(Router):
    def classify(self, question: str) -> Classification:
        _started.set()
        time.sleep(1.0)
        _completed.set()
        return Classification(branch="billing", reason="stubbed")


async def _swallow(task: Any) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass


class TestOnlyTheAwaitedClassificationIsCancelled:
    def _drive(self, graph: Any) -> None:
        async def go() -> None:
            async def pump() -> None:
                async for _ in graph.astream(_payload(), {"recursion_limit": 50}):
                    pass

            task = asyncio.create_task(pump())
            deadline = time.monotonic() + 15
            while not _started.is_set():
                if time.monotonic() > deadline or task.done():
                    raise AssertionError("the router was never reached")
                await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.wait_for(asyncio.shield(_swallow(task)), timeout=10)

        asyncio.run(go())

    def _graph(self, monkeypatch: Any, router_cls: Any) -> Any:
        _started.clear()
        _completed.clear()
        monkeypatch.setattr(router_module, "Router", router_cls)
        runtime = NodeRuntime(model=_classifying("billing", "the billing desk"))
        document = _document()
        return WorkflowCompiler().build(document, RunState, runtime.factory(document))

    def test_an_awaited_classification_never_finishes(self, monkeypatch: Any) -> None:
        self._drive(self._graph(monkeypatch, _SlowAsyncRouter))

        assert not _completed.is_set()

    def test_a_thread_bridged_classification_runs_to_completion_anyway(
        self, monkeypatch: Any
    ) -> None:
        """The honest other half — a worker thread is not interruptible, and
        this is what the shipped node did before this ticket."""
        self._drive(self._graph(monkeypatch, _SlowSyncRouter))

        assert _completed.wait(timeout=5.0)
