"""A follow-up question, and the thread that makes it answerable (ticket 11).

The report was *"follow up did not work — I got random response when asking
about relevant data."* Charted with two candidate designs — a `follow_up`
router branch, or giving the router history — and both were the wrong
question. The router already has history and already knows what a follow-up
is; what it was given was an empty conversation.

Everything asserted here comes out of
`tests/data/recorded_chinook_followup_thread.json`, which is two verbatim
recordings of the **same** four-turn conversation against the live stack:
one that sends a `thread_id` on every turn (what `/chat` does) and one that
omits it (what the editor's Ask panel does). Nothing is synthesised. That
distinction has already caught two bugs on this repo, where an invented
fixture passed while the live path was broken.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.api.streaming import _stream_run
from openstategraph.compile.node_runtime import _thread_question

RECORDING = json.loads(
    (Path(__file__).parent / "data" / "recorded_chinook_followup_thread.json").read_text()
)


def _turn(run: str, number: int) -> dict:
    return next(t for t in RECORDING[run] if t["turn"] == number)


# --- what the recording shows ---------------------------------------------- #


def test_a_thread_gives_the_router_the_previous_turn_to_classify_against() -> None:
    """Turn 2, recorded: the router sees the conversation, not a bare fragment.

    `_thread_question` renders the history block; this is the evidence that it
    reaches the router in a real run rather than only in a unit test.
    """
    routed = _turn("withThread", 2)["routerInput"]

    assert routed.startswith("Conversation so far:")
    assert "Which genre earns the most revenue?" in routed
    # The new message is named as the task, below the context, so the history
    # block cannot be mistaken for it.
    assert routed.rstrip().endswith("How did you get that?")


def test_without_a_thread_the_router_gets_the_follow_up_with_no_antecedent() -> None:
    """The same turn, same model, same document — recorded without a thread.

    "How did you get that?" arrives as that sentence and nothing else. There
    is no antecedent for "that" anywhere in the run.
    """
    routed = _turn("withoutThread", 2)["routerInput"]

    assert routed == "How did you get that?"
    assert "Conversation so far:" not in routed


def test_the_recorded_symptom_is_the_report_the_owner_filed() -> None:
    """Turn 2's two answers, side by side, are the whole defect.

    With a thread the assistant explains the join it ran; without one it
    answers a question nobody asked — the "random response when asking about
    relevant data".
    """
    with_thread = _turn("withThread", 2)["answer"]
    without = _turn("withoutThread", 2)["answer"]

    assert "InvoiceLine" in with_thread and "Genre" in with_thread
    assert "InvoiceLine" not in without
    assert "set up to answer questions about the Chinook" in without


def test_a_follow_up_with_no_antecedent_also_burns_the_run() -> None:
    """Turn 4, recorded without a thread, never finished at all.

    Worth pinning as its own fact: the cost of a missing conversation is not
    only a wrong answer. Asked to "remind me what the top genre was" with
    nothing to remind it of, the analyst re-read the schema until it invented
    a tool name, and the stream was still going when the probe's connection
    ended. The same question on a thread answered in one lap.
    """
    stranded = _turn("withoutThread", 4)
    threaded = _turn("withThread", 4)

    assert stranded["terminalEvent"] == ""
    assert threaded["terminalEvent"] == "done"
    assert "Rock" in threaded["answer"] and "826.65" in threaded["answer"]
    assert stranded["updates"] > threaded["updates"]


def test_the_recording_is_what_the_editor_actually_sends() -> None:
    """The un-threaded run is not a straw man.

    `RunRequest.thread_id` is optional and `run_workflow_stream` invents one
    per request, so a client that never sets it opens a new conversation on
    every send. That is exactly what the editor's Ask panel does, and this
    recording is that request shape.
    """
    assert RECORDING["withoutThread"][0]["routerInput"] == RECORDING["withoutThread"][0]["question"]
    assert RECORDING["threadId"]


# --- the gap that made it unfixable from the client ------------------------ #


class _FinishingGraph:
    """A graph that runs one step and stops. Enough to reach the `done` frame."""

    def stream(self, *_args, **_kwargs):
        yield (), "updates", {"step_one": {"outputs": {"step_one": "a"}}}

    def get_state(self, _config):
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs):
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


class _FailingGraph(_FinishingGraph):
    def stream(self, *_args, **_kwargs):
        raise RuntimeError("the provider went away")
        yield  # pragma: no cover — makes this a generator function


_RUNTIME = SimpleNamespace(
    diagnostics=CompileDiagnostics()
)


def _frames(graph):
    return list(
        _stream_run(
            graph, {}, {}, SimpleNamespace(warnings=[]), {"step_one": "node:a"}, _RUNTIME, "t1"
        )
    )


def _payload(frame: str) -> dict:
    return json.loads(frame.split("data: ", 1)[1])


@pytest.mark.parametrize("graph", [_FinishingGraph(), _FailingGraph()])
def test_every_terminal_frame_names_the_thread_it_ran_in(graph) -> None:
    """`interrupt` always did; `done` and `error` now do too.

    The server mints a `thread_id` when the request omits one. Until this, it
    kept it: the client that most needed to continue a conversation — the one
    that had not named a thread — was the one that could not learn which
    thread it had been given. Continuity has to be *offered* before a client
    can choose it.
    """
    last = _frames(graph)[-1]

    assert last.startswith("event: done") or last.startswith("event: error")
    assert _payload(last)["threadId"] == "t1"


def test_the_recorded_done_frames_predate_that_and_carry_no_thread_id() -> None:
    """The before half of the fix, kept as recorded rather than described."""
    for run in ("withThread", "withoutThread"):
        for turn in RECORDING[run]:
            if turn["terminalEvent"] == "done":
                assert "threadId" not in turn["terminalKeys"]


# --- the runtime was never the problem ------------------------------------- #


def test_the_runtime_is_conversation_aware_the_moment_state_has_a_conversation() -> None:
    """Replayed from the recorded thread, not from an invented message list.

    This is the reason no `follow_up` branch and no router change are part of
    this fix: given the history a thread carries, `_thread_question` already
    produces exactly what the recorded live run shows.
    """
    turn_one = _turn("withThread", 1)
    turn_two = _turn("withThread", 2)
    state = {
        "question": turn_two["question"],
        "messages": [
            SimpleNamespace(type="human", content=turn_one["question"]),
            SimpleNamespace(type="ai", content=turn_one["answer"]),
            SimpleNamespace(type="human", content=turn_two["question"]),
        ],
    }

    assert _thread_question(state) == turn_two["routerInput"]


def test_an_empty_conversation_degrades_to_the_bare_question() -> None:
    """And that is correct behaviour — a first turn has no history.

    Which is why the defect was invisible to every existing test: the runtime
    does the right thing with what it is given, and it was given nothing.
    """
    state = {"question": "How did you get that?", "messages": []}

    assert _thread_question(state) == "How did you get that?"
