"""What the framework-free run surface promises a consumer, one clause at a time.

`test_the_run_surface_names_no_framework.py` proves the surface is not bound to
anybody's web framework. This file proves it is worth having: the four things
an adapter author has to be able to rely on, and which are the four places such
adapters are usually wrong.

- **A stop stops the run**, and does so while the run is *inside* a step rather
  than only between two of them.
- **An error is an event**, never a raise out of the middle of an iteration,
  where a framework has already sent its headers and can render nothing.
- **The pacing is the consumer's.** Nothing is buffered, so a slow consumer
  slows the run instead of filling a queue nobody is draining.
- **A synchronous framework gets the same run**, not a second engine.

The graph is a stub on purpose. Every clause here is about the *fold*, and a
real model would make each of them a slow test about a provider.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from openstategraph.loader import CompiledWorkflow
from openstategraph.run_stream import RunEvent

DOCUMENT: dict[str, Any] = {
    "version": 3,
    "name": "Stub",
    "settings": {},
    "nodes": [{"id": "in1", "type": "input.text", "data": {}}],
    "edges": [],
}


class _State:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.next: tuple[str, ...] = ()


class StubGraph:
    """A compiled graph's streaming surface, and nothing else it does not need.

    Counts the steps it was actually asked for, which is what makes "the stop
    stopped it" a measurement rather than an absence of output.
    """

    def __init__(self, *, steps: int = 4, pause: float = 0.0, boom: bool = False) -> None:
        self.steps = steps
        self.pause = pause
        self.boom = boom
        self.produced = 0

    def astream(self, _graph_input: Any, _config: Any, **_kwargs: Any) -> Any:
        async def run() -> Any:
            for index in range(self.steps):
                if self.pause:
                    await asyncio.sleep(self.pause)
                if self.boom and index == 1:
                    raise RuntimeError("the provider hung up")
                self.produced += 1
                yield {
                    "type": "updates",
                    "ns": (),
                    "data": {"in1": {"outputs": {"in1": f"step {index}"}}},
                }

        return run()

    async def aget_state(self, _config: Any) -> Any:
        return _State({"answer": "final", "outputs": {"in1": "final"}, "attempts": 0})


def workflow(graph: StubGraph) -> CompiledWorkflow:
    return CompiledWorkflow(graph=graph, slug="stub", document=DOCUMENT)


class TestAStopStopsTheRun:
    def test_it_ends_the_stream_mid_step(self) -> None:
        """Not "the next event is skipped" — the step in flight is abandoned.

        The pause is what makes this a real test. A stop consulted only between
        events is indistinguishable from this one when the steps are instant,
        and the step somebody wants to stop *during* is always the slow one.
        """
        graph = StubGraph(steps=20, pause=0.05)
        loaded = workflow(graph)
        stream = loaded.events("q", thread_id="t")

        async def watch() -> list[RunEvent]:
            seen = []
            async for event in stream:
                seen.append(event)
                if len(seen) == 3:
                    stream.stop()
            return seen

        seen = asyncio.run(watch())

        assert [e.type for e in seen] == ["started", "update", "update"]
        assert graph.produced < 20, "the run kept going after the consumer left"

    def test_a_stopped_stream_has_no_terminal_event(self) -> None:
        """Stated in `RunStream.stop`, and pinned because a client depends on it.

        A body that ends with no terminal event is how both of this project's
        own clients tell "the connection dropped" from "the run finished". An
        invented `done` on the stop path would make a cancelled run look
        successful to every consumer that gates on the terminal event.
        """
        stream = workflow(StubGraph(steps=20, pause=0.05)).events("q", thread_id="t")

        async def watch() -> list[str]:
            seen = []
            async for event in stream:
                seen.append(event.type)
                stream.stop()
            return seen

        assert asyncio.run(watch())[-1] not in {"done", "error", "interrupt"}

    def test_stopping_before_the_first_event_yields_nothing(self) -> None:
        """`stop()` is callable from any thread, therefore also from before.

        An adapter that races a disconnect listener can win that race, and a
        stop that only took effect once the loop had started would run the
        whole workflow for a consumer that was already gone.
        """
        graph = StubGraph(steps=5)
        stream = workflow(graph).events("q", thread_id="t")
        stream.stop()

        async def watch() -> list[RunEvent]:
            return [event async for event in stream]

        assert asyncio.run(watch()) == []


class TestAnErrorIsAnEvent:
    def test_a_failing_run_ends_with_an_error_event(self) -> None:
        stream = workflow(StubGraph(steps=4, boom=True)).events("q", thread_id="t")

        async def watch() -> list[RunEvent]:
            return [event async for event in stream]

        seen = asyncio.run(watch())

        assert [e.type for e in seen] == ["started", "update", "error"]
        assert seen[-1].data["threadId"] == "t"
        assert "the provider hung up" in seen[-1].data["detail"]
        assert "RuntimeError" in seen[-1].data["detail"]

    def test_a_bad_context_raises_before_the_first_event(self) -> None:
        """The one thing that is a raise, and it is raised where a 422 is still possible.

        Mid-body a framework has already sent 200 and its headers; the only
        honest report left is an `error` event. Before the first event it can
        still answer the request. So the split is: everything the *request* got
        wrong raises out of `events(...)`, everything the *run* met is an event.
        """
        from openstategraph.errors import OpenStateGraphError

        document = {**DOCUMENT, "settings": {"context": [{"key": "region", "type": "string"}]}}
        loaded = CompiledWorkflow(graph=StubGraph(), slug="stub", document=document)

        with pytest.raises(OpenStateGraphError):
            loaded.events("q", thread_id="t", context={"nonsense": 1})


class TestThePacingIsTheConsumers:
    def test_a_slow_consumer_slows_the_run(self) -> None:
        """The backpressure contract, measured rather than asserted in prose.

        If anything buffered, the producer would run to completion while the
        consumer was still on its second event, and `produced` would already be
        at its ceiling. Pull-based means the count tracks the consumer.
        """
        graph = StubGraph(steps=8)
        stream = workflow(graph).events("q", thread_id="t")
        counts: list[int] = []

        async def watch() -> None:
            async for event in stream:
                if event.type == "update":
                    counts.append(graph.produced)
                    await asyncio.sleep(0.01)

        asyncio.run(watch())

        assert counts == list(range(1, 9)), (
            f"the producer ran ahead of the consumer: {counts}. Nothing in this "
            "fold may buffer — an adapter that wants to shed load does it over "
            "events that carry enough to shed safely."
        )


class TestTheSynchronousDoor:
    def test_it_yields_the_same_events(self) -> None:
        loaded = workflow(StubGraph(steps=3))

        try:
            seen = [event for event in loaded.events("q", thread_id="t")]
        finally:
            loaded.close()

        assert [e.type for e in seen] == ["started", "update", "update", "update", "done"]
        assert seen[-1].data["answer"] == "final"

    def test_abandoning_it_stops_the_run(self) -> None:
        """A WSGI server has no disconnect signal — it drops the response body.

        So the sync door's cancellation is generator finalisation, and this is
        the pin for it: `break` out of the loop, and the run stops. Without it
        a Flask worker whose client went away would pay for every remaining
        superstep, which is the same bill `launch-readiness/10` measured on the
        ASGI side.
        """
        graph = StubGraph(steps=20, pause=0.02)
        loaded = workflow(graph)

        try:
            for index, _event in enumerate(loaded.events("q", thread_id="t")):
                if index == 2:
                    break
            time.sleep(0.2)
        finally:
            loaded.close()

        assert graph.produced < 20, "the run kept going after the body was dropped"

    def test_stop_reaches_it_from_another_thread(self) -> None:
        graph = StubGraph(steps=40, pause=0.02)
        loaded = workflow(graph)
        stream = loaded.events("q", thread_id="t")
        threading.Timer(0.1, stream.stop).start()

        try:
            seen = [event for event in stream]
        finally:
            loaded.close()

        assert len(seen) < 41
        assert graph.produced < 40


GATED: dict[str, Any] = {
    "version": 1,
    "name": "Gate Demo",
    "document": {
        "version": 3,
        "name": "Gate Demo",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
            {
                "id": "gate1",
                "type": "human.approval",
                "data": {"message": "This goes to a customer under your name."},
                "position": {"x": 300, "y": 0},
            },
            {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 600, "y": 0}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "gate1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "gate1", "portId": "approved"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    },
}


class TestAPausedRunSaysSo:
    """A real graph, a real gate, and no model — the same trick `test_cli_resume` uses.

    This is the one terminal path a stub graph cannot show, and it is the one
    most easily lost: a checkpoint that is *read back* does not carry
    `__interrupt__` the way `ainvoke`'s return does, so a stream that folded
    the state naively would end a paused run with a `done` carrying an empty
    answer — a pause and a failure wearing the same clothes
    (`workflow-gallery/24`).
    """

    def test_it_ends_with_an_interrupt_event(self, tmp_path: Any, monkeypatch: Any) -> None:
        import json

        from openstategraph import load_workflow

        monkeypatch.setenv("OPENSTATEGRAPH_CHECKPOINT_PATH", "memory")
        package = tmp_path / "gated"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps(GATED))

        with load_workflow(package) as loaded:
            seen = [event for event in loaded.events("ship it", thread_id="gate-t")]

        assert seen[-1].type == "interrupt", [e.type for e in seen]
        assert seen[-1].data["threadId"] == "gate-t"
        assert "under your name" in seen[-1].data["message"]
        assert seen[-1].data["candidate"] == "ship it"
