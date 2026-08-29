"""The grader's body is `async def` and awaits `agrade`.

`async-first/14`, first of the two rungs `05` built and nothing reached.

Phase D (`async-first/06`) migrated four families — `_agent`, `_worker`,
`_subgraph`, `_orchestrator` — under a charter that said **longest-running
first**. `_grader` was deliberately outside that four, and the reason given was
that it is short. Then `05` grew `BaseGrader.agrade` and nothing went back to
ask whether this builder could use it, so the rung had zero production callers
and every grep hit for it was a test.

**The measurement is what decides this file, not the charter.**
`docs/decisions/async-seam.md` says the cancellation win is per node and only
for long nodes, and that migrating a short one "would be measurable in
nothing". Taken at the two-arm test `05`, `06` and `10` all used — `astream`
plus `task.cancel()` — that turns out not to hold here. Measured against this
tree before the migration, on the graph below with a grader model that sleeps
five seconds: **the stream stops in under a millisecond and the grader's model
call runs to completion anyway.** That is the `stop_when_client_leaves`
defect exactly — abandoned, not cancelled — and it is billed.

The distinguishing property is not duration. It is **whether the closure holds
a model call at all**: the seam document's own example of a node measurable in
nothing is `_static_text`, which makes none. `_grader` makes one, one level
down the published ladder, and it makes it *every lap of a revision loop* —
which is why "short" here describes one call and not a run.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import Any

# The grader family moved to `compile/nodes/grader.py` (`docs-and-gaps/03`) and
# the substitutions below moved with it. `node_runtime` still re-exports
# `Grader`, so patching it there would keep passing while binding a name the
# builder no longer reads — a substitution that proves nothing.
import openstategraph.compile.nodes.grader as grader_module
from openstategraph.abc.grader import Grader, Verdict
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan, WorkflowCompiler
from openstategraph.progress import progress_report, report_progress

from conftest import RespondingModel, any_chat_model

GRADER = lambda content: "You are a grader" in content  # noqa: E731


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _RecordingGrader(Grader):
    """Records which door of the ladder the node reached it through.

    Both doors are written out, so neither is the bridge `install_doors` would
    otherwise supply: a test that let the ladder fill one in would be asserting
    `abc/async_doors.py`'s behaviour rather than this node's choice.
    """

    doors: list[str] = []

    def grade(self, candidate: str, *, question: str = "") -> Verdict:
        _RecordingGrader.doors.append("grade")
        return super().grade(candidate, question=question)

    async def agrade(self, candidate: str, *, question: str = "") -> Verdict:
        _RecordingGrader.doors.append("agrade")
        return await super().agrade(candidate, question=question)


def _plan() -> CompiledPlan:
    plan = CompiledPlan()
    plan.edges.append(("a1", "g1"))
    plan.conditional["g1"] = {"pass": "out1", "revise": "a1"}
    return plan


def _built(monkeypatch: Any, model: Any = None, **data: Any) -> Any:
    _RecordingGrader.doors = []
    monkeypatch.setattr(grader_module, "Grader", _RecordingGrader)
    runtime = NodeRuntime(model=model or any_chat_model())
    node = {"id": "g1", "type": "route.grader", "data": data}
    return runtime._grader("g1", node, _plan())


def _state(candidate: str = "an answer") -> RunState:
    return RunState(  # type: ignore[typeddict-item]
        messages=[],
        question="what is the answer?",
        attempts=0,
        decisions={},
        outputs={"a1": candidate},
    )


def _node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": sp},
        "target": {"nodeId": dst, "portId": dp},
    }


def _document() -> dict[str, Any]:
    """input -> agent -> grader, `revise` back to the agent's feedback port."""
    return {
        "version": 1,
        "name": "judged",
        "nodes": [
            _node("in1", "input.text"),
            _node("a1", "agent.llm"),
            _node("g1", "route.grader", criteria="Say something.", maxAttempts="3"),
            _node("out1", "output.formatted"),
        ],
        "edges": [
            _edge("in1", "text", "a1", "prompt"),
            _edge("a1", "result", "g1", "candidate"),
            _edge("g1", "revise", "a1", "feedback"),
            _edge("g1", "pass", "out1", "result"),
        ],
    }


def _payload() -> dict[str, Any]:
    return {
        "messages": [],
        "question": "what is the answer?",
        "attempts": 0,
        "decisions": {},
        "outputs": {},
    }


# --------------------------------------------------------------------------- #
# 1-3. The three claims every migrated family makes.
# --------------------------------------------------------------------------- #


class TestTheGraderBodyIsACoroutine:
    def test_the_factory_returns_an_async_def(self, monkeypatch: Any) -> None:
        assert inspect.iscoroutinefunction(_built(monkeypatch, criteria="anything"))

    def test_it_reaches_its_ladder_through_agrade(self, monkeypatch: Any) -> None:
        """The whole ticket in one assertion.

        `grade` appearing here would mean the judgement's model call had stayed
        on the un-cancellable side — the state `TestOnlyTheAwaitedJudgement
        IsCancelled` below measures the cost of.
        """
        run = _built(
            monkeypatch,
            model=RespondingModel([(GRADER, "PASS")], default=""),
            criteria="anything",
        )
        asyncio.run(run(_state()))
        assert _RecordingGrader.doors == ["agrade"]

    def test_a_deterministic_rejection_still_asks_no_model(
        self, monkeypatch: Any
    ) -> None:
        """The prelude is shared by both doors and must stay shared.

        An empty candidate is settled by `deterministic_checks` before any
        model is consulted, and `agrade`'s docstring promises exactly that. A
        body that awaited a model first would still pass every assertion about
        the update.
        """
        model = RespondingModel([(GRADER, "PASS")], default="")
        run = _built(monkeypatch, model=model, criteria="anything")
        update = asyncio.run(run(_state(candidate="")))

        assert update["decisions"] == {"g1": "revise"}
        assert model.calls == []


class TestTheUpdateIsWhatItAlwaysWas:
    def test_a_pass_writes_the_same_keys(self, monkeypatch: Any) -> None:
        model = RespondingModel([(GRADER, "PASS")], default="")
        run = _built(monkeypatch, model=model, criteria="anything", maxAttempts="3")
        update = asyncio.run(run(_state("a real answer")))

        assert update["decisions"] == {"g1": "pass"}
        assert update["revisions"] == {"g1": 1}
        assert update["feedback"] == ""
        assert update["outputs"] == {"g1": "a real answer"}
        assert update["verdicts"]["g1"]["verdict"] == "pass"
        assert "forced" not in update

    def test_a_rejection_writes_the_same_keys(self, monkeypatch: Any) -> None:
        model = RespondingModel([(GRADER, "FAIL\nSay more.")], default="")
        run = _built(monkeypatch, model=model, criteria="anything", maxAttempts="3")
        update = asyncio.run(run(_state("a real answer")))

        assert update["decisions"] == {"g1": "revise"}
        assert update["feedback"] == "Say more."
        assert update["verdicts"]["g1"]["verdict"] == "revise"
        # `revise` is wired in `_plan`, so nothing is reported unrouted.
        assert "unrouted" not in update

    def test_the_attempts_cap_still_forces_a_pass(self, monkeypatch: Any) -> None:
        model = RespondingModel([(GRADER, "FAIL\nSay more.")], default="")
        run = _built(monkeypatch, model=model, criteria="anything", maxAttempts="1")
        update = asyncio.run(run(_state("a real answer")))

        assert update["decisions"] == {"g1": "pass"}
        assert update["forced"] == {"g1": "Say more."}


class TestTheRevisionLoopStillLapsAndStops:
    """The claim only a whole graph can make.

    The grader does not route — the compiler's conditional edge reads exactly
    what this node writes to `decisions` and dispatches on it. An async body
    that wrote the same dict a superstep later, or under a different key, would
    pass every test above and loop forever or never loop at all.
    """

    def _graph(self, model: Any) -> Any:
        runtime = NodeRuntime(model=model)
        document = _document()
        return WorkflowCompiler().build(document, RunState, runtime.factory(document))

    def _rejecting_once(self) -> RespondingModel:
        verdicts = iter(["FAIL\nSay more.", "PASS"])
        model = RespondingModel([], default="an answer")
        original = model._generate

        def generate(messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
            content = "\n".join(str(m.content) for m in messages)
            if GRADER(content):
                model.calls.append(content)
                return model._reply(next(verdicts))
            return original(messages, stop=stop, run_manager=run_manager, **kwargs)

        model._generate = generate  # type: ignore[method-assign]
        return model

    def test_one_revise_lap_then_a_pass(self) -> None:
        model = self._rejecting_once()
        result = asyncio.run(
            self._graph(model).ainvoke(_payload(), {"recursion_limit": 50})
        )

        assert result["decisions"]["g1"] == "pass"
        assert result["revisions"]["g1"] == 2
        # Only the judgements: `model.calls` also carries the agent's turns,
        # because one fake model serves the whole graph.
        assert len([c for c in model.calls if GRADER(c)]) == 2

    def test_the_same_graph_still_answers_the_sync_door(self) -> None:
        """`compile/node_doors.py`, not a second body.

        Four synchronous callers reach a compiled graph — the blocking
        `/api/runs`, the MCP server, `CompiledWorkflow.run` and the CLI. The
        door is installed once at the compiler's own `add_node`, so this family
        carries nothing for it; that it is genuinely installed here is what
        this asserts.

        **That door is not cancellable and cannot be.** It preserves today's
        behaviour for those four callers. *Stop means stop* is the async
        door's.
        """
        result = self._graph(self._rejecting_once()).invoke(
            _payload(), {"recursion_limit": 50}
        )

        assert result["decisions"]["g1"] == "pass"


# --------------------------------------------------------------------------- #
# 4. Narration, on the wire rather than in a call.
# --------------------------------------------------------------------------- #


class _NarratingAsyncGrader(Grader):
    """Writes `agrade` natively — the awaited path the migrated body takes."""

    async def agrade(self, candidate: str, *, question: str = "") -> Verdict:
        assert report_progress("judging") is True
        return await super().agrade(candidate, question=question)


class _NarratingSyncGrader(Grader):
    """Writes only `grade`, so `agrade` is the ladder's installed thread door.

    This is the arm that could actually lose the writer. `get_stream_writer()`
    is context-local and this body runs in a worker thread; `asyncio.to_thread`
    copies the ambient context, which is a property to assert rather than to
    trust — the failure is silent on both suites (`launch-readiness/110` was a
    blank panel with a green suite).
    """

    def grade(self, candidate: str, *, question: str = "") -> Verdict:
        assert report_progress("judging") is True
        return Verdict(passed=True, reason="fine")


def _narration_from(monkeypatch: Any, grader_cls: Any, door: str) -> list[Any]:
    monkeypatch.setattr(grader_module, "Grader", grader_cls)
    runtime = NodeRuntime(model=RespondingModel([(GRADER, "PASS")], default="answer"))
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


class TestNarrationFromTheGraderReachesTheWire:
    """Selected **by the node stamp**, which is the half a changed execution
    context would have quietly emptied: the agent upstream narrates too, and a
    frame that arrived unstamped would not be in the list at all
    (`async-first/07` — a status field keys on the node, never on the reporter).
    """

    def test_an_awaited_judgement_still_narrates(self, monkeypatch: Any) -> None:
        reports = _narration_from(monkeypatch, _NarratingAsyncGrader, "async")

        assert [r.message for r in reports if r.node == "g1"] == ["judging"]

    def test_a_thread_doored_judgement_still_narrates(self, monkeypatch: Any) -> None:
        reports = _narration_from(monkeypatch, _NarratingSyncGrader, "async")

        assert [r.message for r in reports if r.node == "g1"] == ["judging"]

    def test_it_narrates_through_the_sync_door_too(self, monkeypatch: Any) -> None:
        reports = _narration_from(monkeypatch, _NarratingAsyncGrader, "sync")

        assert [r.message for r in reports if r.node == "g1"] == ["judging"]


# --------------------------------------------------------------------------- #
# 5. The reason the phase exists, for this family.
# --------------------------------------------------------------------------- #


_started = threading.Event()
_completed = threading.Event()


class _SlowAsyncGrader(Grader):
    async def agrade(self, candidate: str, *, question: str = "") -> Verdict:
        _started.set()
        await asyncio.sleep(5)
        _completed.set()
        return Verdict(passed=True, reason="fine")


class _SlowAsyncModel(RespondingModel):
    """A model whose *own* async door sleeps — no grader subclass involved.

    `GenericFakeChatModel` inherits `BaseChatModel`'s default `_agenerate`,
    which runs `_generate` in an executor; writing the async half natively is
    what every real provider does, and is what makes the cancel reach the call
    rather than the thread holding it.
    """

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        if GRADER(content):
            _started.set()
            await asyncio.sleep(5)
            _completed.set()
        return self._generate(messages, stop=stop, run_manager=None, **kwargs)


class _SlowSyncGrader(Grader):
    """Only `grade`, so `agrade` is the ladder's installed thread door."""

    def grade(self, candidate: str, *, question: str = "") -> Verdict:
        _started.set()
        time.sleep(1.0)
        _completed.set()
        return Verdict(passed=True, reason="fine")


async def _swallow(task: Any) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass


class TestOnlyTheAwaitedJudgementIsCancelled:
    """`async-first/09`'s measurement, pointed at this family.

    Two arms, and the contrast is the proof: the shape this ticket ships stops
    when the run is stopped, and the shape it replaced does not. Both drive the
    same compiled graph through `astream` and cancel the driving task.
    """

    def _drive(self, graph: Any) -> None:
        async def go() -> None:
            async def pump() -> None:
                async for _ in graph.astream(_payload(), {"recursion_limit": 50}):
                    pass

            task = asyncio.create_task(pump())
            # A deadline rather than a bare wait: if the grader is never
            # reached at all this must fail rather than hang the suite.
            deadline = time.monotonic() + 15
            while not _started.is_set():
                if time.monotonic() > deadline or task.done():
                    raise AssertionError("the grader was never reached")
                await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.wait_for(asyncio.shield(_swallow(task)), timeout=10)

        asyncio.run(go())

    def _graph(self, monkeypatch: Any, grader_cls: Any) -> Any:
        _started.clear()
        _completed.clear()
        monkeypatch.setattr(grader_module, "Grader", grader_cls)
        runtime = NodeRuntime(model=RespondingModel([], default="an answer"))
        document = _document()
        return WorkflowCompiler().build(document, RunState, runtime.factory(document))

    def test_an_awaited_judgement_never_finishes(self, monkeypatch: Any) -> None:
        self._drive(self._graph(monkeypatch, _SlowAsyncGrader))

        assert not _completed.is_set()

    def test_the_whole_chain_is_awaited_down_to_the_model(
        self, monkeypatch: Any
    ) -> None:
        """The strongest arm: no grader subclass at all.

        The three above prove the *node* is on the awaited side by overriding
        a rung. This one uses the shipped `Grader` and puts the sleep in the
        model's own `_agenerate`, so what is cancelled is the real chain —
        `_grader` -> `BaseGrader.agrade` -> `ainvoke_model` -> `model.ainvoke`.
        A body that awaited an outer verb over a blocking inner one would pass
        the other three and fail here.

        And it is the honest boundary of the feature: `ainvoke_model` is
        tolerant, so a model with no `ainvoke` is still put in a thread and
        still runs to completion. Every real provider this project resolves
        supplies a native one; `_DeepAgentAsChatModel`, which we build
        ourselves, does not.
        """
        _started.clear()
        _completed.clear()
        runtime = NodeRuntime(model=_SlowAsyncModel([], default="an answer"))
        document = _document()
        self._drive(
            WorkflowCompiler().build(document, RunState, runtime.factory(document))
        )

        assert not _completed.is_set()

    def test_a_thread_bridged_judgement_runs_to_completion_anyway(
        self, monkeypatch: Any
    ) -> None:
        """The honest other half, and it is not a defect being reported.

        The ladder's default `agrade` is `asyncio.to_thread(self.grade, ...)`,
        and a worker thread is not interruptible in Python. A grader that
        writes only a blocking `grade` is billed for after the stop — which is
        what the *whole shipped node* did before this ticket, measured at five
        seconds of sleep completing after a cancel that returned in under a
        millisecond.
        """
        self._drive(self._graph(monkeypatch, _SlowSyncGrader))

        assert _completed.wait(timeout=5.0)
