"""Stop: what actually stops when the consumer goes away (ticket 10).

The client half of Stop is an `AbortController` — it cancels the body reader,
which closes the HTTP connection. Starlette then cancels the task driving the
`StreamingResponse`, and the generator underneath is finalised. These tests
pin the *server* half of that chain, synthetically and without a socket: when
the consumer stops iterating `_stream_run`, the generator must exit and must
close the LangGraph stream it was driving.

The honest boundary, pinned by `test_the_superstep_already_in_flight_is_not
_interrupted`: `graph.stream()` is a generator driven BY this loop, so
cancellation lands *between* supersteps. A model call already in flight inside
the current superstep runs to completion and its result is discarded — nothing
here can reach into it, and no test may pretend otherwise.
"""

from __future__ import annotations

from types import SimpleNamespace

from conftest import FoldPump, ScriptedGraph, drive_fold  # noqa: E402

from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.api.streaming import _stream_run


class _RecordingGraph:
    """A graph whose `stream()` records production and closure."""

    def __init__(self, chunks: list[tuple[tuple[str, ...], str, dict]]) -> None:
        self._chunks = chunks
        self.produced: list[str] = []
        self.closed = False

    def stream(self, *_args, **_kwargs):
        def _gen():
            try:
                for namespace, mode, payload in self._chunks:
                    self.produced.append(next(iter(payload)))
                    yield namespace, mode, payload
            finally:
                self.closed = True

        return _gen()

    def get_state(self, _config):
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs):
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


CHUNKS = [
    ((), "updates", {"step_one": {"outputs": {"step_one": "a"}}}),
    ((), "updates", {"step_two": {"outputs": {"step_two": "b"}}}),
    ((), "updates", {"step_three": {"outputs": {"step_three": "c"}}}),
]

KNOWN = {"step_one": "node:a", "step_two": "node:b", "step_three": "node:c"}


_RUNTIME = SimpleNamespace(
    diagnostics=CompileDiagnostics()
)


def _run(graph):
    """The fold, undriven — an async generator since `async-first/02`.

    Returned rather than drained because half this module is about what
    happens when a consumer stops part way, which a list cannot express. The
    tests that want the whole run say `drive_fold(_run(graph))`; the ones that
    want to stop say `FoldPump(_run(graph))`.
    """
    return _stream_run(
        ScriptedGraph(graph), {}, {}, SimpleNamespace(warnings=[]), KNOWN, _RUNTIME, "t1"
    )


def test_closing_the_consumer_exits_the_generator_and_closes_the_graph_stream() -> None:
    """The disconnect path, end to end on our side of it."""
    graph = _RecordingGraph(CHUNKS)
    frames = FoldPump(_run(graph))

    # Two frames, because the run now opens with one (`memory-and-replay` 53).
    # The first pull is still the pull that drives the graph: `started` is
    # minted without suspending and handed over on the far side of it.
    assert frames.next().startswith("event: started")
    assert frames.next().startswith("event: update")
    assert graph.closed is False

    # What Starlette does when the client goes away: it stops iterating, and
    # the generator is finalised. Nothing below may hang or raise.
    frames.close()

    assert graph.closed is True


def test_the_superstep_already_in_flight_is_not_interrupted() -> None:
    """The honest boundary, stated as a test rather than a comment.

    Exactly one superstep was pulled from `graph.stream` before the stop, and
    exactly one was produced — never two. Cancellation happens *between*
    supersteps because this loop is the thing pulling them; it cannot reach
    into a model call that the current superstep has already issued.
    """
    graph = _RecordingGraph(CHUNKS)
    frames = FoldPump(_run(graph))
    frames.next()
    frames.close()

    assert graph.produced == ["step_one"]


def test_a_stopped_run_reports_no_result() -> None:
    """No `done` frame, no `error` frame — a stop is neither."""
    graph = _RecordingGraph(CHUNKS)
    frames = FoldPump(_run(graph))
    emitted = [frames.next()]
    frames.close()

    assert all("event: done" not in frame for frame in emitted)
    assert all("event: error" not in frame for frame in emitted)


def test_the_stop_is_logged_so_it_can_be_observed_from_outside(caplog) -> None:
    """A Stop whose effect leaves no trace is indistinguishable from a fake one.

    This line is what live verification reads in the uvicorn log to confirm
    the generator really exited, so it is pinned rather than left to chance.
    """
    import logging

    graph = _RecordingGraph(CHUNKS)
    frames = FoldPump(_run(graph))
    frames.next()

    with caplog.at_level(logging.INFO, logger="openstategraph.api.streaming"):
        frames.close()

    assert "stopped by the client" in caplog.text
    assert "t1" in caplog.text


def test_a_run_nobody_stops_still_closes_its_graph_stream() -> None:
    """The `finally` is not a disconnect-only path; normal completion uses it too."""
    graph = _RecordingGraph(CHUNKS)
    frames = drive_fold(_run(graph))

    assert graph.closed is True
    assert frames[-1].startswith("event: done")


# --- the disconnect race ----------------------------------------------------
#
# Starlette does NOT listen for disconnects on a modern ASGI server: for
# `spec_version >= 2.4` it only notices when a `send()` raises. Measured live,
# that meant a browser which aborted its fetch mid-crew left the run streaming
# to its natural end while the UI already claimed it had stopped.
# `stop_when_client_leaves` is what closes that gap, so it gets its own tests.


def _drain(agen, limit: int = 100) -> list[str]:
    """Consumes an async generator from a sync test — no plugin, no event loop config."""
    import asyncio

    async def go() -> list[str]:
        out: list[str] = []
        async for frame in agen:
            out.append(frame)
            if len(out) >= limit:
                break
        return out

    return asyncio.run(go())


def _receive_after(n_calls: int):
    """An ASGI `receive` that reports the client gone on the nth call."""
    import asyncio

    state = {"calls": 0}

    async def receive() -> dict:
        state["calls"] += 1
        if state["calls"] >= n_calls:
            return {"type": "http.disconnect"}
        await asyncio.sleep(3600)  # a client that is still there says nothing
        return {"type": "http.request"}

    return receive


def test_frames_flow_through_while_the_client_is_still_there() -> None:
    from openstategraph.api.streaming import stop_when_client_leaves

    graph = _RecordingGraph(CHUNKS)
    frames = _drain(stop_when_client_leaves(_run(graph), _receive_after(99)))

    # Nothing is swallowed or reordered — the wrapper is transparent until the
    # client leaves.
    assert frames[-1].startswith("event: done")
    assert sum(f.startswith("event: update") for f in frames) == 3


def test_a_disconnect_stops_the_run_instead_of_letting_it_finish() -> None:
    """The bug this exists for, in one test.

    Without the wrapper the generator is pulled to completion and every
    remaining superstep runs for a client that has gone. With it, the pull
    stops and no `done` frame is ever produced.
    """
    from openstategraph.api.streaming import stop_when_client_leaves

    graph = _RecordingGraph(CHUNKS)
    frames = _drain(stop_when_client_leaves(_run(graph), _receive_after(1)))

    assert all("event: done" not in frame for frame in frames)
    # At most the superstep already in flight — never the whole run.
    assert len(graph.produced) < len(CHUNKS)
