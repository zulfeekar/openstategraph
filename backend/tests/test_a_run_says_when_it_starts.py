"""A run announces itself before it does anything — `memory-and-replay` 53.

Seven frame kinds and not one of them opened the run. The first thing a client
received was whichever of `update`, `token`, `progress` or `spawn` happened to
arrive first, so the first frame's *shape* depended on the workflow — and
`threadId` reached a client only on a **terminal** frame. Measured live on
`stress-review` (2026-08-29, `ollama:gpt-oss:120b-cloud`): frame **377 of
377**. A reader whose connection drops at frame 300 never learns the id of the
thread it was watching, so it cannot reconnect to it, resume it, or look it up
in `/api/threads`.

**A frame, not a header.** SSE has none, and the HTTP response's would have
cost no contract change at all — which is the argument against it. A header is
invisible to `RuntimeClient.ts`, absent from `docs/api.md`'s frame table, and
gone the moment a stream is saved to a file: `memory-and-replay` is a map about
*recording* runs, and the identity of the thread has to survive being written
down. A frame is the only form that does.

**`threadId` and nothing else.** No `runId`: this installation identifies a
*turn*, not a run (`run_identity.py`), and 49's own reading of AG-UI is the
place that warned inventing a second identifier is how `taskId` nearly became
this map's third homonym. A field is easy to add later and impossible to
remove.

**And it makes 46's clock honest.** `elapsedMs` is an offset from the stream's
opening; until now that origin was an event nobody observed. `started` is
`seq: 0` and `elapsedMs` ~0 by construction, because `_stream_run` opens the
clock and then immediately builds this frame with it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from conftest import ScriptedGraph, drive_fold

from openstategraph.compile.diagnostics import CompileDiagnostics

from openstategraph.api.streaming import (
    FRAME_FIELDS,
    OPENING_EVENTS,
    PROGRESS_EVENTS,
    RUN_EVENTS,
    TERMINAL_EVENTS,
    _stream_run,
)


# --------------------------------------------------------------------------
# The vocabulary


def test_the_opening_frame_is_declared_and_is_neither_progress_nor_terminal() -> None:
    """`started` is a third category, and saying so is the point.

    It could not join `PROGRESS_EVENTS` — whose docstring is *"the event names
    that report progress"*, and an announcement that a run began reports none —
    and it obviously could not join `TERMINAL_EVENTS`. `RUN_EVENTS` claims to
    be *"the whole run vocabulary, in the order a client meets it"*, and a
    client meets this one first.
    """
    assert OPENING_EVENTS == ("started",)
    assert RUN_EVENTS[0] == "started"
    assert "started" not in PROGRESS_EVENTS
    assert "started" not in TERMINAL_EVENTS


def test_the_opening_frame_carries_the_thread_and_the_clock() -> None:
    assert FRAME_FIELDS["started"] == ("threadId", "seq", "elapsedMs")


def test_the_opening_frame_invents_no_second_identifier() -> None:
    """49's warning, kept as an assertion. A `runId` here would be a second
    name for a turn, and the map already spent a ticket on one homonym."""
    assert "runId" not in FRAME_FIELDS["started"]
    assert "parentRunId" not in FRAME_FIELDS["started"]


# --------------------------------------------------------------------------
# On the wire


class _Graph:
    def __init__(self, chunks: list[Any], *, explode: bool = False) -> None:
        self._chunks = chunks
        self._explode = explode

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        if self._explode:

            def boom() -> Any:
                raise RuntimeError("the graph died")
                yield  # pragma: no cover

            return boom()
        return iter(self._chunks)

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _frames(
    chunks: list[Any], audience: Any = None, *, explode: bool = False
) -> list[tuple[str, dict[str, Any]]]:
    from openstategraph.api.audience import Audience

    raw = drive_fold(
        _stream_run(
            ScriptedGraph(_Graph(chunks, explode=explode)),
            {"question": "q"},
            {"configurable": {"thread_id": "t"}},
            SimpleNamespace(warnings=[]),
            {"in1": "in1"},
            SimpleNamespace(diagnostics=CompileDiagnostics()),
            "thread-53",
            audience or Audience.DEVELOPER,
        )
    )
    out: list[tuple[str, dict[str, Any]]] = []
    for frame in raw:
        name = frame.split("event: ", 1)[1].split("\n", 1)[0]
        out.append((name, json.loads(frame.split("data: ", 1)[1])))
    return out


_ONE_STEP = [((), "updates", {"in1": {"outputs": {"in1": "hello"}}})]


def test_a_run_opens_with_the_thread_it_is_in() -> None:
    frames = _frames(_ONE_STEP)

    assert frames[0][0] == "started"
    assert frames[0][1]["threadId"] == "thread-53"


def test_the_opening_frame_is_seq_zero_and_the_origin_of_the_clock() -> None:
    """46 decided `elapsedMs` is an offset from the stream's opening. This is
    the frame that offset is now measured from, and it is on the wire."""
    frames = _frames(_ONE_STEP)

    assert frames[0][1]["seq"] == 0
    assert frames[0][1]["elapsedMs"] < 200
    assert [payload["seq"] for _, payload in frames] == list(range(len(frames)))


def test_a_run_that_dies_immediately_still_said_which_thread_it_was() -> None:
    """The case the ticket is actually about, in its sharpest form.

    A run that raises inside `graph.stream` produces exactly two frames. Before
    this ticket the first of them was `error`; the client learned the thread id
    at the same moment it learned there was nothing left to watch.
    """
    frames = _frames([], explode=True)

    assert [name for name, _ in frames] == ["started", "error"]
    assert frames[0][1]["threadId"] == frames[-1][1]["threadId"] == "thread-53"


def test_a_customer_is_told_the_thread_exactly_as_a_developer_is() -> None:
    """Not a disclosure. Every terminal frame has named the thread to both
    audiences since ticket 11; saying it earlier discloses nothing new, and
    46's pin requires the two streams to carry the same frames in the same
    order anyway."""
    from openstategraph.api.audience import Audience

    customer = _frames(_ONE_STEP, Audience.CUSTOMER)
    developer = _frames(_ONE_STEP, Audience.DEVELOPER)

    assert customer[0] == ("started", {"threadId": "thread-53", "seq": 0, **{
        "elapsedMs": customer[0][1]["elapsedMs"]
    }})
    assert [name for name, _ in customer] == [name for name, _ in developer]


# --------------------------------------------------------------------------
# The regression the opening frame nearly caused, pinned twice


def _drive_like_the_transport(frames: Any) -> list[str]:
    """Every frame, each pulled from **its own task** — the live shape.

    `drive_fold` uses one `async for`, so the whole stream is drained inside a
    single context. The server does not: `stop_when_client_leaves` races each
    frame against the disconnect, so every frame is pulled inside its own
    `asyncio.ensure_future(...)` and a task runs on a *copy* of the context
    that created it. That difference is invisible to almost every test in this
    suite and is the whole subject of the two below — the same reason
    `test_the_frame_clock_survives_the_transport.py` exists.
    """
    import asyncio

    async def collect() -> list[str]:
        stream = frames.__aiter__()
        out: list[str] = []
        while True:
            try:
                out.append(await asyncio.ensure_future(stream.__anext__()))
            except StopAsyncIteration:
                return out

    return asyncio.run(collect())


class _TurnWatchingGraph(_Graph):
    """A graph that records whether the run's turn was bound where it ran."""

    def __init__(self) -> None:
        super().__init__([((), "updates", {"in1": {"outputs": {"in1": "hi"}}})])
        self.turn_was_open: bool | None = None

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        from openstategraph.run_journal import _open_turn

        self.turn_was_open = _open_turn.get() is not None
        return super().stream(*args, **kwargs)


def test_the_fold_runs_in_the_context_that_opened_the_turn() -> None:
    """The bug this ticket nearly shipped, caught on a live run and pinned here.

    `run_turn` binds LangChain's token meter with a `ContextVar`, and
    everything before an async generator's first `yield` runs in the task that
    made the **first pull**. So a `started` frame yielded before the first pull
    put the turn in one task and `graph.astream` in another — and a task runs
    on a copy of the context that created it, so the meter was invisible to
    every model call the run made. On a live `stress-review` run `done.usage`
    came back `[]` beside 247 token frames, and the run row recorded `{}` where
    the two runs before this ticket recorded 23,664 and 25,445 tokens.

    `_open_turn` stands in for the meter here because they are set by the same
    `run_turn`, in the same context, a line apart: if the fold can see one it
    can see the other, and neither needs a provider to demonstrate it.
    """
    from openstategraph.api.audience import Audience

    graph = _TurnWatchingGraph()
    frames = _drive_like_the_transport(
        _stream_run(
            ScriptedGraph(graph),
            {"question": "q"},
            {"configurable": {"thread_id": "t"}},
            SimpleNamespace(warnings=[]),
            {"in1": "in1"},
            SimpleNamespace(diagnostics=CompileDiagnostics()),
            "thread-53",
            Audience.DEVELOPER,
        )
    )

    assert frames[0].startswith("event: started")
    assert graph.turn_was_open is True, (
        "the fold ran in a context with no turn bound — the token meter is "
        "bound by the same `run_turn`, so this run's cost was not counted"
    )


def test_nothing_is_yielded_before_the_first_pull() -> None:
    """The structural half, so the fix cannot be undone by a tidy-up.

    The test above is a behaviour test and would still pass if somebody moved
    the yield back and the meter happened to survive on some future asyncio.
    This reads the source: inside `_stream_run`, no `yield` may appear before
    the `await` that first pulls from the fold. Minting a frame is free;
    *handing it over* is what suspends, and suspending is what moves the
    context.
    """
    import ast
    import inspect
    import textwrap

    from openstategraph.api import streaming

    tree = ast.parse(textwrap.dedent(inspect.getsource(streaming._stream_run)))
    first_pull = min(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "__anext__"
    )
    yields = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Yield)]
    # Anti-vacuity, both halves: a matcher that found no pull would make
    # `first_pull` a `min()` over nothing and raise; one that found no yields
    # would make the assertion below true of a generator that yields nothing.
    assert yields, "no yield found in `_stream_run` — check the matcher, not the fold"
    early = [line for line in yields if line < first_pull]

    assert early == [], (
        f"`_stream_run` yields at line(s) {early} before pulling its first "
        f"frame at line {first_pull}. That suspension moves the turn's "
        f"`ContextVar` into a different task from `graph.astream`, and the "
        f"run's token meter stops counting — mint the frame there and yield "
        f"it after the pull instead."
    )
