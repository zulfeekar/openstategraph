"""A stop that was *cancelled* and a stop that was *abandoned* (async-first/07).

The map's promise is "stop means stop", and the ticket's own warning is the
half that is easy to drop: **a run that was cancelled and a run that was
abandoned look identical from the browser.** They always have — the
client-visible stop has been 0.00 s throughout (`async-first/09`), so the
timing never told the two apart and never could. What differs is the *work*:

| the step in flight | what a stop does to it | measured, 2026-08-27 |
| --- | --- | --- |
| an `async def` body (Phase D) | cancelled at its next await | 0.41–1.08 s of trailing work |
| a `def` body in a worker thread | runs to completion, result discarded | 12.65–24.16 s |

Both numbers are the same fan-out (`morning-brief`, three concurrent workers,
disconnected 12 s in) on the same model. So the distinction is real, it is
large, and until this module it was invisible: `AskPanel` rendered one
sentence — the *abandoned* one — for both.

Which node is which is not a guess and not a table anybody maintains. The
compiler installs the async door (`compile/node_doors.both_doors`), so the
compiler is what says so, and it says so on the object it hands LangGraph.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from conftest import ScriptedGraph, drive_fold  # noqa: E402

from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.compile.node_doors import (
    both_doors,
    interruptible_nodes,
    is_interruptible,
    with_both_doors,
)
from openstategraph.api.streaming import FRAME_FIELDS, _stream_run


# --------------------------------------------------------------------------
# The compiler's own answer


def test_the_async_door_marks_itself_interruptible() -> None:
    async def body(_state):  # pragma: no cover - never called
        return {}

    assert is_interruptible(both_doors(body)) is True


def test_a_sync_body_is_not_interruptible() -> None:
    """The identity path of `with_both_doors` — a `def` LangGraph runs in a thread."""

    def body(_state):  # pragma: no cover - never called
        return {}

    assert is_interruptible(with_both_doors(body)) is False


def test_anything_the_compiler_did_not_wrap_is_not_interruptible() -> None:
    """`__start__`, an error handler, a node from a future family — all `False`.

    Never `True` by omission: the sentence a `False` earns is the one this
    product has always shown, so an unknown node keeps today's honest claim.
    """
    assert is_interruptible(object()) is False
    assert is_interruptible(None) is False


def test_a_compiled_graph_reports_which_of_its_nodes_a_stop_cancels() -> None:
    async def slow(_state):  # pragma: no cover - never called
        return {}

    def quick(_state):  # pragma: no cover - never called
        return {}

    graph = SimpleNamespace(
        nodes={
            "agent1": SimpleNamespace(bound=with_both_doors(slow)),
            "in1": SimpleNamespace(bound=with_both_doors(quick)),
            "__start__": SimpleNamespace(bound=None),
        }
    )
    assert interruptible_nodes(graph) == {"agent1"}


def test_a_graph_that_cannot_be_asked_reports_nothing_rather_than_raising() -> None:
    """Every stub in this suite is such a graph, and none of them may break."""
    assert interruptible_nodes(SimpleNamespace()) == set()


# --------------------------------------------------------------------------
# What the reader is told


class _Graph:
    """A stub graph that also answers "which of your nodes are cancellable"."""

    def __init__(self, chunks, interruptible=("step_one",)) -> None:
        self._chunks = chunks

        async def slow(_state):  # pragma: no cover - never called
            return {}

        def quick(_state):  # pragma: no cover - never called
            return {}

        self.nodes = {
            name: SimpleNamespace(
                bound=with_both_doors(slow if name in interruptible else quick)
            )
            for name in ("step_one", "step_two")
        }

    def stream(self, *_args, **_kwargs):
        return iter(self._chunks)

    def get_state(self, _config):
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs):
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


KNOWN = {"step_one": "node:a", "step_two": "node:b"}
_RUNTIME = SimpleNamespace(diagnostics=CompileDiagnostics())


def _frames(chunks):
    return drive_fold(
        _stream_run(
            ScriptedGraph(_Graph(chunks)),
            {},
            {},
            SimpleNamespace(warnings=[]),
            KNOWN,
            _RUNTIME,
            "t1",
        )
    )


def _payload(frames, event):
    for frame in frames:
        if frame.startswith(f"event: {event}\n"):
            return json.loads(frame.split("data: ", 1)[1])
    raise AssertionError(f"no {event} frame in {frames}")


def test_an_update_frame_says_whether_a_stop_would_cancel_that_node() -> None:
    cancellable = _payload(
        _frames([((), "updates", {"step_one": {"outputs": {"step_one": "a"}}})]),
        "update",
    )
    assert cancellable["interruptible"] is True

    thread_bound = _payload(
        _frames([((), "updates", {"step_two": {"outputs": {"step_two": "b"}}})]),
        "update",
    )
    assert thread_bound["interruptible"] is False


def test_the_three_frames_that_carry_an_active_node_carry_it_too() -> None:
    """One field, on exactly the frames that say which node is in charge.

    `done`, `error`, `interrupt` and `spawn` do not carry it: the first three
    are terminal (there is nothing left to cancel) and `spawn` names a task
    rather than the node currently working.
    """
    for name in ("update", "token", "progress"):
        assert "interruptible" in FRAME_FIELDS[name], name
    for name in ("done", "error", "interrupt", "spawn"):
        assert "interruptible" not in FRAME_FIELDS[name], name


# --------------------------------------------------------------------------
# The only record a disconnected run leaves


def _stop_after_one(chunks, caplog):
    from conftest import FoldPump

    frames = FoldPump(
        _stream_run(
            ScriptedGraph(_Graph(chunks)),
            {},
            {},
            SimpleNamespace(warnings=[]),
            KNOWN,
            _RUNTIME,
            "t1",
        )
    )
    frames.next()
    with caplog.at_level("INFO", logger="openstategraph.api.streaming"):
        frames.close()
    return " ".join(record.getMessage() for record in caplog.records)


def test_the_stop_log_says_the_step_was_cancelled(caplog) -> None:
    """The disconnect path yields no frame, so this line is the whole record."""
    logged = _stop_after_one(
        [((), "updates", {"step_one": {"outputs": {"step_one": "a"}}})], caplog
    )
    assert "cancelled" in logged
    assert "abandoned" not in logged


def test_the_stop_log_says_the_step_was_abandoned(caplog) -> None:
    logged = _stop_after_one(
        [((), "updates", {"step_two": {"outputs": {"step_two": "b"}}})], caplog
    )
    assert "abandoned" in logged
    assert "cancelled" not in logged


# --------------------------------------------------------------------------
# The other client


CHAT = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "openstategraph"
    / "api"
    / "static"
    / "chat.html"
)


def test_the_hosted_chat_page_tells_the_two_apart_too() -> None:
    """Two clients read this stream, and a fix on one of them is half a fix.

    `chat.html` is dependency-free and has no JS test harness, so it is pinned
    by reading it — the same way `test_chat_enter_sends.py` and the trace
    tests do.
    """
    source = CHAT.read_text(encoding="utf-8")

    # It reads the field at all...
    assert "interruptible" in source
    # ...and has a sentence for each case, not one for both.
    assert "was cancelled" in source
    assert "finish in the background" in source


def test_the_hosted_chat_page_does_not_claim_a_cancelled_run_is_silent() -> None:
    """The next false readout, refused in advance — see `is_interruptible`."""
    source = CHAT.read_text(encoding="utf-8")
    cancelled = [
        line for line in source.splitlines() if "was cancelled" in line
    ]
    assert cancelled, "no cancelled sentence to check"
    for line in cancelled:
        assert "nothing is running" not in line.lower()


def test_both_clients_say_the_same_two_sentences() -> None:
    """Two surfaces, one claim about the server — or the claim is a story.

    `graderVerdictLine.parity.test.ts` is the precedent: a sentence about what
    the backend did, rendered by two clients, drifts unless something compares
    them. Whole sentences, because the drift that matters here is a *hedge*
    added on one side and not the other.
    """
    import re
    from pathlib import Path

    def sentences(text: str) -> str:
        # TypeScript splits a long line across concatenated literals; rejoin
        # them so the comparison is about the words, not the line breaks.
        return " ".join(re.sub(r"'\s*\+\s*'", "", text).split())

    chat = sentences(CHAT.read_text(encoding="utf-8"))
    editor = sentences(
        (
            Path(__file__).resolve().parents[2] / "src" / "view" / "ask" / "stoppedLine.ts"
        ).read_text(encoding="utf-8")
    )

    cancelled = (
        "the step that was running was cancelled, and nothing further is scheduled. "
        "The model call it had already sent still finishes; its result is discarded."
    )
    abandoned = (
        "nothing further is scheduled. Steps already dispatched cannot be "
        "interrupted: they finish in the background and their results are discarded."
    )
    for sentence in (cancelled, abandoned):
        assert sentence in chat, sentence
        assert sentence in editor, sentence


# --------------------------------------------------------------------------
# The node the field is *about*


def test_an_internal_frame_reports_the_node_the_run_is_actually_inside() -> None:
    """Found live, not by reading the code (`async-first/07`).

    A stop mid-fan-out logged *abandoned* while all three workers were in fact
    cancelled. The last frames before the disconnect were `progress` frames
    whose reporting `node` was `NarrationMiddleware.before_model` — a name
    that is not a canvas node at all, so it matched nothing and answered
    `False`.

    `activeNode` exists precisely because a frame's reporting node is not
    where the run is (`docs/api.md`), and this field has to be about the same
    node the highlight is on. Otherwise a run whose every frame is internal —
    which is what a long agent step *is* — reads as uncancellable throughout.
    """
    from openstategraph.progress import PROGRESS_KEY, Progress

    frames = drive_fold(
        _stream_run(
            ScriptedGraph(
                _Graph(
                    [
                        # Establishes where the run is...
                        ((), "updates", {"step_one": {"outputs": {"step_one": "a"}}}),
                    ]
                )
            ),
            {},
            {},
            SimpleNamespace(warnings=[]),
            KNOWN,
            _RUNTIME,
            "t1",
        )
    )
    assert _payload(frames, "update")["interruptible"] is True

    # ...and an internal narration frame from inside it must agree.
    narrated = drive_fold(
        _stream_run(
            ScriptedGraph(
                _Graph(
                    [
                        ((), "updates", {"step_one": {"outputs": {"step_one": "a"}}}),
                        (
                            (),
                            "custom",
                            {
                                PROGRESS_KEY: Progress(
                                    message="thinking",
                                    node="NarrationMiddleware.before_model",
                                ).model_dump()
                            },
                        ),
                    ]
                )
            ),
            {},
            {},
            SimpleNamespace(warnings=[]),
            KNOWN,
            _RUNTIME,
            "t1",
        )
    )
    progress = _payload(narrated, "progress")
    assert progress["node"] == "NarrationMiddleware.before_model"
    assert progress["interruptible"] is True, (
        "the field must describe `activeNode`, not the reporting node — "
        "otherwise every internal frame of a long agent step reads as "
        "uncancellable and the stop log says the wrong word"
    )
