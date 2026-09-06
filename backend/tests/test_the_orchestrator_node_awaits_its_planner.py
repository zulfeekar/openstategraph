"""Phase D, fourth and last family: the supervisor's body is `async def`.

`async-first/10`, and it closes `async-first/06`.

This is the family whose I/O does not belong to it. `_agent`, `_worker` and
`_subgraph` each hold their own `.invoke(` site, so migrating them was a local
change; `_orchestrator`'s closure makes **no** model call at all. It calls
`planner.plan(...)`, and the two model calls a plan can make are two levels
down the *published* orchestrator ladder — the planning call in
`PlanningOrchestrator.split`, and the archetype-labelling call in
`BaseOrchestrator.label`.

So the migration had to wait for `async-first/05`, which grew `asplit`,
`alabel` and `aplan`. **Three verbs, not one**, and that is the fact this file
asserts rather than repeats: awaiting the outer verb buys nothing if the inner
two block. An `async def` body that then called the synchronous `plan()` would
hold the **event loop** for a model call rather than a pool thread — strictly
worse than the `def` body it replaced, and cancellable by nothing.

Four claims, the same three the other three families make plus this family's
own:

1. the body is a coroutine function;
2. it reaches its planner through `aplan`, and never through `plan`;
3. the update it writes — subtasks, dispatch record, notes, attempt count — is
   exactly what it always was;
4. **the fan-out it feeds still dispatches and joins**, which is the claim only
   a whole graph can make.

Then the two the migration could break silently, and neither is visible in an
answer: narration on the `custom` channel (`launch-readiness/110` was a blank
panel with a green suite), and the two-arm cancellation measurement that is the
whole point of the phase.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import Any

# The supervisor and worker families moved to `compile/nodes/orchestration.py`
# (`docs-and-gaps/03`) and the substitutions below moved with them: the
# builder resolves `orchestrator_for` in its own module now, so patching the
# name where it used to live would bind nothing the planner ever reads.
import openstategraph.compile.nodes.orchestration as orchestration_module
from openstategraph.abc.orchestrator import BaseOrchestrator, Orchestrator
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan, WorkflowCompiler
from openstategraph.progress import progress_report, report_progress

from conftest import RespondingModel, any_chat_model


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _RecordingPlanner(Orchestrator):
    """A planner that records which door of the ladder it was reached through.

    Both doors are written out, so neither is the installed bridge over the
    other: a test that let the ladder supply one of them would be asserting
    `async_doors.py`'s behaviour rather than this node's choice.
    """

    doors: list[str] = []

    def plan(self, instruction: str, **kwargs: Any) -> list[Any]:
        _RecordingPlanner.doors.append("plan")
        return super().plan(instruction, **kwargs)

    async def aplan(self, instruction: str, **kwargs: Any) -> list[Any]:
        _RecordingPlanner.doors.append("aplan")
        return await super().aplan(instruction, **kwargs)


def _built(monkeypatch: Any, **data: Any) -> Any:
    _RecordingPlanner.doors = []
    monkeypatch.setattr(
        orchestration_module,
        "orchestrator_for",
        lambda **kwargs: _RecordingPlanner(**kwargs),
    )
    runtime = NodeRuntime(model=any_chat_model())
    node = {"id": "lead1", "type": "orchestrate.supervisor", "data": data}
    return runtime._orchestrator("lead1", node, CompiledPlan())


def _state() -> RunState:
    return RunState(  # type: ignore[typeddict-item]
        messages=[],
        question="first thing; second thing",
        attempts=0,
        decisions={},
        outputs={},
    )


def _node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": sp},
        "target": {"nodeId": dst, "portId": dp},
    }


def _document() -> dict[str, Any]:
    """input.text -> orchestrate.supervisor -> orchestrate.worker -> report."""
    return {
        "version": 1,
        "name": "supervised",
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


# --------------------------------------------------------------------------- #
# 1-3. The three claims every migrated family makes.
# --------------------------------------------------------------------------- #


class TestTheOrchestratorBodyIsACoroutine:
    def test_the_factory_returns_an_async_def(self, monkeypatch: Any) -> None:
        assert inspect.iscoroutinefunction(_built(monkeypatch))

    def test_it_reaches_its_planner_through_aplan(self, monkeypatch: Any) -> None:
        """The whole ticket in one assertion.

        `plan` appearing here would mean a model call had been moved from a
        pool thread onto the event loop — the wrong move `async-first/06`
        stopped short of making.
        """
        run = _built(monkeypatch)
        asyncio.run(run(_state()))
        assert _RecordingPlanner.doors == ["aplan"]

    def test_the_update_is_what_it_always_was(self, monkeypatch: Any) -> None:
        run = _built(monkeypatch)
        update = asyncio.run(run(_state()))

        planned = update["subtasks"]["lead1"]
        # `CONTEXT_SUFFIX` and the generation-scoped ids come from `_bounded`,
        # which both doors of the ladder call — so this asserts the plan is the
        # same plan, suffix and all, rather than a plainer one.
        assert [t["instruction"].split(" (part of")[0] for t in planned] == [
            "first thing",
            "second thing",
        ]
        assert all("part of the request" in t["instruction"] for t in planned)
        # The dispatch record (ticket 17): flat, string-valued, `#`-separated,
        # and saying that an unlabelled subtask reached the default worker.
        assert update["decisions"] == {
            "lead1#" + planned[0]["id"]: "(default)",
            "lead1#" + planned[1]["id"]: "(default)",
        }
        assert update["outputs"]["lead1"].startswith("Planned 2 subtask(s).")
        assert update["attempts"] == 1

    def test_a_rejection_still_refines_every_subtask_rather_than_adding_one(
        self, monkeypatch: Any
    ) -> None:
        """The feedback rule, which lives entirely inside the migrated body."""
        run = _built(monkeypatch)
        state = _state()
        state["feedback"] = "too shallow"  # type: ignore[typeddict-unknown-key]
        state["decisions"] = {"g1": "revise"}  # type: ignore[typeddict-item]

        runtime_plan = CompiledPlan()
        runtime_plan.edges.append(("g1", "lead1"))
        update = asyncio.run(run(state))

        planned = update["subtasks"]["lead1"]
        # Two subtasks still, not three: feedback refines, it is never split on.
        assert len(planned) == 2


class TestTheFanOutStillDispatchesAndJoins:
    """The claim only a whole graph can make.

    The supervisor does not dispatch — the compiler's `_fan_out_router` reads
    exactly what this node writes and issues the `Send`s. An async body that
    wrote the same dict a superstep later, or under a different key, would pass
    every test above and dispatch nothing.
    """

    def test_two_subtasks_are_dispatched_and_both_come_back(self) -> None:
        runtime = NodeRuntime(model=RespondingModel([], default="worked"))
        document = _document()
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        result = asyncio.run(
            graph.ainvoke(
                {
                    "messages": [],
                    "question": "first thing; second thing",
                    "attempts": 0,
                    "decisions": {},
                    "outputs": {},
                },
                {"recursion_limit": 50},
            )
        )

        assert len(result["worker_results"]) == 2
        assert set(result["worker_results"].values()) == {"worked"}

    def test_the_same_graph_still_answers_the_sync_door(self) -> None:
        """`compile/node_doors.py`, not a second body.

        Four synchronous callers reach a compiled graph — the blocking
        `/api/runs`, the MCP server, `CompiledWorkflow.run` and the CLI — and
        one migrated node makes the graph async-only at the caller level. The
        door is installed once at the compiler's own `add_node`, so this family
        carries nothing for it; that it is genuinely installed here is what
        this asserts.

        Stated where it cannot be mistaken for the feature: **this door is not
        cancellable and cannot be.** It preserves today's behaviour for those
        four callers. *Stop means stop* is the async door's.
        """
        runtime = NodeRuntime(model=RespondingModel([], default="worked"))
        document = _document()
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        result = graph.invoke(
            {
                "messages": [],
                "question": "first thing; second thing",
                "attempts": 0,
                "decisions": {},
                "outputs": {},
            },
            {"recursion_limit": 50},
        )

        assert len(result["worker_results"]) == 2


# --------------------------------------------------------------------------- #
# 4. Narration, on the wire rather than in a call.
# --------------------------------------------------------------------------- #


class _NarratingAsyncPlanner(Orchestrator):
    """Writes `asplit` natively — the awaited path `aplan` takes."""

    async def asplit(self, instruction: str, feedback: str = "") -> list[str]:
        assert report_progress("planning") is True
        return await super().asplit(instruction, feedback)


class _NarratingSyncPlanner(BaseOrchestrator):
    """Writes only `split`, so `asplit` is the ladder's installed thread door.

    This is the arm that could actually lose the writer. `get_stream_writer()`
    is context-local and this body runs in a worker thread; `asyncio.to_thread`
    copies the ambient context, which is a property to assert rather than to
    trust — the failure is silent on both suites.
    """

    def split(self, instruction: str, feedback: str = "") -> list[str]:
        assert report_progress("planning") is True
        return [p.strip() for p in instruction.split(";") if p.strip()]


def _narration_from(monkeypatch: Any, planner_cls: Any, door: str) -> list[Any]:
    monkeypatch.setattr(
        orchestration_module, "orchestrator_for", lambda **kwargs: planner_cls(**kwargs)
    )
    runtime = NodeRuntime(model=RespondingModel([], default="worked"))
    document = _document()
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    payload = {
        "messages": [],
        "question": "first thing; second thing",
        "attempts": 0,
        "decisions": {},
        "outputs": {},
    }
    config = {"recursion_limit": 50}

    if door == "sync":
        parts = list(
            graph.stream(
                payload, config, stream_mode=["custom"], subgraphs=True, version="v2"
            )
        )
    else:

        async def collect() -> list[Any]:
            seen = []
            async for part in graph.astream(
                payload, config, stream_mode=["custom"], subgraphs=True, version="v2"
            ):
                seen.append(part)
            return seen

        parts = asyncio.run(collect())

    return [
        r
        for r in (progress_report(p["data"]) for p in parts if p["type"] == "custom")
        if r is not None
    ]


class TestNarrationFromTheSupervisorReachesTheWire:
    def test_an_awaited_planning_call_still_narrates(self, monkeypatch: Any) -> None:
        reports = _narration_from(monkeypatch, _NarratingAsyncPlanner, "async")

        # Selected **by the node stamp**, which is the half a changed execution
        # context would have quietly emptied: the workers downstream narrate
        # too, and a frame that arrived unstamped would not be here at all.
        assert [r.message for r in reports if r.node == "lead1"] == ["planning"]

    def test_a_thread_doored_planning_call_still_narrates(
        self, monkeypatch: Any
    ) -> None:
        reports = _narration_from(monkeypatch, _NarratingSyncPlanner, "async")

        assert [r.message for r in reports if r.node == "lead1"] == ["planning"]

    def test_it_narrates_through_the_sync_door_too(self, monkeypatch: Any) -> None:
        reports = _narration_from(monkeypatch, _NarratingAsyncPlanner, "sync")

        assert [r.message for r in reports if r.node == "lead1"] == ["planning"]


# --------------------------------------------------------------------------- #
# 5. The reason the phase exists, for this family.
# --------------------------------------------------------------------------- #


_started = threading.Event()
_completed = threading.Event()


class _SlowAsyncPlanner(Orchestrator):
    async def asplit(self, instruction: str, feedback: str = "") -> list[str]:
        _started.set()
        await asyncio.sleep(5)
        _completed.set()
        return ["something"]


class _SlowSyncPlanner(BaseOrchestrator):
    """Only `split`, so `asplit` is the ladder's installed thread door.

    Not an `Orchestrator` subclass: that class writes a native `asplit` of its
    own, which is exactly the thing being avoided here.
    """

    def split(self, instruction: str, feedback: str = "") -> list[str]:
        _started.set()
        time.sleep(1.0)
        _completed.set()
        return ["something"]


async def _swallow(task: Any) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass


class TestOnlyTheAwaitedPlannerIsCancelled:
    """Ticket 09's measurement, pointed at this family.

    Two arms, and the contrast is the proof: the shape this ticket ships stops
    when the run is stopped, and the shape it replaced does not. Both drive the
    same compiled graph through `astream` and cancel the driving task.
    """

    def _drive(self, graph: Any) -> None:
        async def go() -> None:
            async def pump() -> None:
                async for _ in graph.astream(
                    {
                        "messages": [],
                        "question": "first thing",
                        "attempts": 0,
                        "decisions": {},
                        "outputs": {},
                    },
                    {"recursion_limit": 50},
                ):
                    pass

            task = asyncio.create_task(pump())
            # A deadline rather than a bare wait: if the planner is never
            # reached at all (a body that stopped calling it, a graph that
            # failed upstream) this must fail rather than hang the suite.
            deadline = time.monotonic() + 10
            while not _started.is_set():
                if time.monotonic() > deadline or task.done():
                    raise AssertionError("the planner was never reached")
                await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.wait_for(asyncio.shield(_swallow(task)), timeout=5)

        asyncio.run(go())

    def _graph(self, monkeypatch: Any, planner_cls: Any) -> Any:
        _started.clear()
        _completed.clear()
        monkeypatch.setattr(
            orchestration_module,
            "orchestrator_for",
            lambda **kwargs: planner_cls(**kwargs),
        )
        runtime = NodeRuntime(model=RespondingModel([], default="worked"))
        document = _document()
        return WorkflowCompiler().build(document, RunState, runtime.factory(document))

    def test_an_awaited_plan_never_finishes(self, monkeypatch: Any) -> None:
        self._drive(self._graph(monkeypatch, _SlowAsyncPlanner))

        assert not _completed.is_set()

    def test_a_thread_bridged_plan_runs_to_completion_anyway(
        self, monkeypatch: Any
    ) -> None:
        """The honest other half, and it is not a defect being reported.

        The ladder's default `asplit` is `asyncio.to_thread(self.split, ...)`,
        and a worker thread is not interruptible in Python. A planner that
        writes only a blocking `split` is billed for after the stop — exactly
        what `async-first/09` measured, and exactly what
        `PlanningOrchestrator.asplit` exists so the shipped path does not do.
        """
        self._drive(self._graph(monkeypatch, _SlowSyncPlanner))

        assert _completed.wait(timeout=5.0)
