"""Every stream ends with a frame that says how it ended (UX-02).

A client must never have to guess between "still working", "finished" and
"died". `_stream_run` is the only producer of the SSE feed, so the guarantee
belongs to it: **exactly one terminal frame — `done`, `interrupt` or `error` —
is the last thing every stream emits**, on every exit path it is still able to
write to.

The one path that cannot be covered by a frame is the client going away — a
generator that yields after `GeneratorExit` raises `RuntimeError: generator
ignored GeneratorExit`, and there is no socket left to write to anyway. That
path is pinned here too, as an explicit "no frame, and here is why", with the
client-side fallback named: the client keys on its own abort signal, and
treats a stream that closed with no terminal frame as a dropped connection.
The same is true of a server that is killed mid-stream (a `--reload`
restart): no Python runs at all, so no frame can exist.

These are synthetic generators on purpose. Each one fails, interrupts or
exits at a different point in the fold, which is exactly what a real backend
does at moments no fixture reproduces on demand.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from openstategraph.api.streaming import TERMINAL_EVENTS, _is_terminal, _stream_run

CHUNKS = [
    ((), "updates", {"step_one": {"outputs": {"step_one": "a"}}}),
    ((), "updates", {"step_two": {"outputs": {"step_two": "b"}}}),
]

KNOWN = {"step_one": "node:a", "step_two": "node:b"}

_RUNTIME = SimpleNamespace(unresolved_tools=[], unresolved_functions=[], unresolved_subgraphs=[])


class _Graph:
    """A graph whose every seam can be made to misbehave, one at a time.

    The four constructor hooks are the four places a real run can die *after*
    the client has already been told the run started: inside `graph.stream`,
    inside the post-loop `get_state` that distinguishes a pause from a finish,
    inside the interrupt payload, and inside `draw_mermaid` while the `done`
    frame is being built.
    """

    def __init__(
        self,
        *,
        chunks: list[Any] | None = None,
        raise_at: int | None = None,
        state: Any = None,
        state_raises: bool = False,
        mermaid_raises: bool = False,
    ) -> None:
        self._chunks = CHUNKS if chunks is None else chunks
        self._raise_at = raise_at
        self._state = state or SimpleNamespace(next=(), tasks=())
        self._state_raises = state_raises
        self._mermaid_raises = mermaid_raises
        self.closed = False

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        def _gen() -> Any:
            try:
                for index, chunk in enumerate(self._chunks):
                    if self._raise_at == index:
                        raise RuntimeError("the model provider hung up")
                    yield chunk
                if self._raise_at == len(self._chunks):
                    raise RuntimeError("the model provider hung up")
            finally:
                self.closed = True

        return _gen()

    def get_state(self, _config: Any) -> Any:
        if self._state_raises:
            raise RuntimeError("the checkpointer is gone")
        return self._state

    def get_graph(self, **_kwargs: Any) -> Any:
        def _mermaid() -> str:
            if self._mermaid_raises:
                raise RuntimeError("mermaid failed")
            return "graph TD;"

        return SimpleNamespace(draw_mermaid=_mermaid)


def _run(graph: Any) -> Any:
    return _stream_run(graph, {}, {}, SimpleNamespace(warnings=[]), KNOWN, _RUNTIME, "t1")


def _events(frames: list[str]) -> list[str]:
    return [frame.split("\n", 1)[0].removeprefix("event: ") for frame in frames]


def _paused_state() -> Any:
    """A snapshot that looks like a run parked on `human.approval`."""
    interrupt = SimpleNamespace(value={"message": "Approve this?", "candidate": "the draft"})
    return SimpleNamespace(next=("approve",), tasks=(SimpleNamespace(interrupts=(interrupt,)),))


# --- the contract, one case per exit path ----------------------------------


def test_a_run_that_finishes_ends_with_done() -> None:
    frames = list(_run(_Graph()))

    assert _events(frames)[-1] == "done"


def test_a_run_that_pauses_ends_with_interrupt() -> None:
    """A pause is an ending too — the stream really is over until a resume."""
    frames = list(_run(_Graph(state=_paused_state())))

    assert _events(frames)[-1] == "interrupt"


def test_the_interrupt_frame_names_the_node_the_run_is_parked_on() -> None:
    """Which node is waiting is a fact the snapshot already has (UX-01).

    Without it a surface can only mark "the last node that reported", which is
    the node *before* the approval — verified live on `/chat`, where the ring
    and the "Waiting for you" badge landed on `in1` while `approve1` was the
    node actually waiting. `snapshot.next` is exactly the scheduled-but-not-run
    node, mapped back to a canvas id the same way every other frame is.
    """
    state = _paused_state()
    state.next = ("step_two",)
    payload = json.loads(list(_run(_Graph(state=state)))[-1].split("data: ", 1)[1])

    assert payload["node"] == "node:b"


def test_an_unmapped_paused_node_passes_through_under_its_own_name() -> None:
    """Same rule as every other frame: `.get(raw, raw)`, never a guess.

    A client that cannot find the name on its diagram keeps the mark it
    already had rather than moving it somewhere wrong.
    """
    state = _paused_state()
    state.next = ("a_graph_node_this_canvas_never_had",)
    payload = json.loads(list(_run(_Graph(state=state)))[-1].split("data: ", 1)[1])

    assert payload["node"] == "a_graph_node_this_canvas_never_had"


def test_a_stream_that_raises_mid_fold_ends_with_error() -> None:
    frames = list(_run(_Graph(raise_at=1)))

    assert _events(frames) == ["update", "error"]
    assert "the model provider hung up" in frames[-1]


def test_a_stream_that_raises_before_its_first_frame_still_ends_with_error() -> None:
    """Nothing yielded yet is still a stream the client is waiting on."""
    frames = list(_run(_Graph(raise_at=0)))

    assert _events(frames) == ["error"]


def test_a_failure_after_the_loop_ends_with_error() -> None:
    """The gap this ticket exists for.

    `graph.get_state` runs *after* the fold, outside every handler the old
    code had: it decided pause-versus-finish, and if it raised, the generator
    unwound with the client having seen updates and no ending at all.
    """
    frames = list(_run(_Graph(state_raises=True)))

    assert _events(frames)[-1] == "error"
    assert "the checkpointer is gone" in frames[-1]


def test_a_failure_while_building_the_done_frame_ends_with_error() -> None:
    """Same gap, one line later: the `done` frame's own mermaid render."""
    frames = list(_run(_Graph(mermaid_raises=True)))

    assert _events(frames)[-1] == "error"
    assert "mermaid failed" in frames[-1]


def test_a_failure_while_building_the_interrupt_frame_ends_with_error() -> None:
    """A snapshot that says "paused" but cannot say what it paused for."""
    class _Boom:
        next = ("approve",)

        @property
        def tasks(self) -> Any:
            raise RuntimeError("no task record")

    frames = list(_run(_Graph(state=_Boom())))

    assert _events(frames)[-1] == "error"
    assert "no task record" in frames[-1]


@pytest.mark.parametrize(
    ("graph", "expected"),
    [
        (_Graph(), "done"),
        (_Graph(state=_paused_state()), "interrupt"),
        (_Graph(raise_at=1), "error"),
        (_Graph(state_raises=True), "error"),
        (_Graph(mermaid_raises=True), "error"),
    ],
)
def test_exactly_one_terminal_frame_and_it_is_last(graph: Any, expected: str) -> None:
    """The whole protocol in one assertion, over every path that can send.

    Not merely "a terminal frame appears" — exactly one, and nothing after it.
    Two endings is as dishonest as none: a client that already rendered an
    answer would be asked to render a failure over it.
    """
    events = _events(list(_run(graph)))
    terminal = [event for event in events if event in TERMINAL_EVENTS]

    assert terminal == [expected]
    assert events[-1] == expected


def test_the_graph_stream_is_closed_on_every_ending() -> None:
    """The terminal frame is not bought by leaking the LangGraph stream."""
    for graph in (_Graph(), _Graph(raise_at=1), _Graph(state_raises=True)):
        list(_run(graph))
        assert graph.closed is True


# --- the one path that cannot carry a frame ---------------------------------


def test_a_client_that_walks_away_gets_no_frame_and_that_is_documented() -> None:
    """Honest about the limit rather than pretending to cover it.

    After `GeneratorExit` a generator may not yield — Python raises
    `RuntimeError: generator ignored GeneratorExit` — and the socket the frame
    would go to is already closed. So the client's own fallback is the
    authority here: an abort signal means "you stopped it", and a stream that
    ended with no terminal frame means "the connection dropped".
    """
    graph = _Graph()
    frames = _run(graph)
    first = next(frames)

    frames.close()  # what Starlette does when the client hangs up

    assert _is_terminal(first) is False
    assert graph.closed is True


def test_the_disconnect_is_logged_because_no_frame_can_report_it(caplog: Any) -> None:
    """The log line is the only record that path leaves; it is part of the contract."""
    graph = _Graph()
    frames = _run(graph)
    next(frames)

    with caplog.at_level(logging.INFO, logger="openstategraph.api.streaming"):
        frames.close()

    assert "stopped by the client" in caplog.text


# --- the guard itself -------------------------------------------------------


def test_a_fold_that_ends_without_saying_how_is_reported_as_an_error(
    monkeypatch: Any, caplog: Any
) -> None:
    """Belt and braces: the guard does not trust the fold to have a terminal frame.

    If a future edit adds an early `return` to the fold, this is what stops
    that becoming a silent hang on the client. Synthesised by replacing the
    fold, because no path through the current one can do it.
    """
    from openstategraph.api import streaming

    def _silent(*_args: Any, **_kwargs: Any) -> Any:
        yield streaming._sse("update", {"node": "node:a"})

    monkeypatch.setattr(streaming, "_run_frames", _silent)

    with caplog.at_level(logging.ERROR, logger="openstategraph.api.streaming"):
        frames = list(_run(_Graph()))

    assert _events(frames) == ["update", "error"]
    assert "without a terminal frame" in caplog.text


class TestTheCustomerSurfaceHonoursTheContract:
    """`/chat`'s side of it (UX-01, UX-02).

    Source assertions, and deliberately so: `chat.html` is a dependency-free
    page with no JS test harness in this repo, and the alternative to pinning
    it here is pinning it nowhere. Each check below is a defect that was
    actually shipped, not a style rule — the diagram claiming "running" under
    an approval card, and a killed stream leaving a turn that simply stops.
    """

    @staticmethod
    def _page() -> str:
        from openstategraph.api.chat_page import chat_page_html

        return chat_page_html()

    def test_every_terminal_event_has_a_branch(self) -> None:
        page = self._page()
        for name in TERMINAL_EVENTS:
            assert f'event === "{name}"' in page

    def test_the_interrupt_branch_stops_the_running_treatment(self) -> None:
        """UX-01 exactly: it used to render the approval card and nothing else."""
        page = self._page()
        branch = page.split('event === "interrupt"')[1].split('event === "done"')[0]

        assert "pauseFlow()" in branch
        assert "renderInterrupt" in branch

    def test_pausing_removes_running_and_marks_the_node_distinctly(self) -> None:
        page = self._page()
        body = page.split("function pauseFlow()")[1].split("function finishFlow()")[0]

        assert 'classList.remove("running")' in body
        assert "removeGlow()" in body  # no sweep over a node that is not working
        assert "flow-paused" in body
        assert "placeWait(el)" in body
        assert "Waiting for you" in page

    def test_the_error_branch_also_stops_claiming_to_run(self) -> None:
        page = self._page()
        branch = page.split('event === "error"')[1].split('event === "interrupt"')[0]

        assert "finishFlow()" in branch

    def test_a_stream_that_never_said_how_it_ended_is_reported(self) -> None:
        """UX-02's client half — authoritative, because no frame can exist."""
        page = self._page()

        assert "if (!ended) {" in page
        assert "noteDropped" in page
        assert "restarted or crashed" in page


def test_is_terminal_recognises_exactly_the_ending_events() -> None:
    from openstategraph.api.streaming import _sse

    for name in TERMINAL_EVENTS:
        assert _is_terminal(_sse(name, {})) is True
    for name in ("update", "token", "spawn"):
        assert _is_terminal(_sse(name, {})) is False
