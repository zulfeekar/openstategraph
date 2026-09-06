"""`0 ms`, and no token count anywhere — `memory-and-replay` 37, part 2.

Part 1 made the replay panel readable: one lane per graph, and every tool call
with its arguments and its result. What a reader still could not see is the two
numbers a profiler exists for — **how long a step took, and what it cost.**

The ticket priced those as the expensive half: *"genuinely not stored; this is
part 2 and the storage decision the ticket asks to be priced."* Read against
the stored file, that pricing is **wrong**, and this test is the account of it.
Both numbers are already in the checkpoints:

- **Duration** is the difference between consecutive `ts` values *within one
  namespace*. Every checkpoint carries `ts`, and a checkpoint is written after
  its superstep runs, so `ts(N) - ts(N-1)` is exactly how long superstep `N`
  took. Per namespace, because a worker's supersteps are not the workflow's —
  the same rule the tool-call reader already obeys for the message channel.
- **Tokens** ride on the `AIMessage` itself, in `usage_metadata`. LangChain
  populates it for every provider that reports usage, and it has been going
  into the checkpoints since the day the message channel did.

So no frame table, no second store, no write-side schema — the same finding
part 1 made, one layer along. What genuinely stays unrecoverable is written
into the ticket rather than implied here: the *split* of one superstep between
model time and tool time, and any run whose provider reports no usage.

**These tests drive `read_thread`, not `_step`.** Neither number can be seen
from a single checkpoint — one needs the previous checkpoint in the same
namespace, the other needs to know which messages are new — so a test against
`_step` would stay green against a fix that never learned to look backwards.
"""

from __future__ import annotations

from typing import Any, TypedDict

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated

from openstategraph.api.audience import Audience
from openstategraph.api import threads as thread_queries


class _Stub:
    """One stored checkpoint, with a `ts` this test chose.

    Real timestamps differ by microseconds nobody can assert on, and the rule
    under test is arithmetic over `ts` — so the arithmetic is tested against
    times written by hand, and the *reality* of `usage_metadata` is tested
    against a real graph below.
    """

    def __init__(
        self, ts: str, *, namespace: str = "", step: int = 0, source: str = "loop"
    ) -> None:
        self.config = {"configurable": {"thread_id": "run-1", "checkpoint_ns": namespace}}
        self.checkpoint = {
            "id": f"cp-{namespace}-{step}",
            "ts": ts,
            "channel_values": {"answer": "done"},
            "updated_channels": ["answer"],
        }
        self.metadata = {"step": step, "source": source, "workflow_slug": "morning-brief"}
        self.pending_writes = ()


class _Saver:
    """A saver holding exactly these checkpoints, newest first as LangGraph's is."""

    def __init__(self, tuples: list[Any]) -> None:
        self._tuples = list(reversed(tuples))

    def list(self, config: Any, *, limit: int = 200) -> list[Any]:
        return self._tuples[:limit]


def _steps(tuples: list[Any]) -> list[Any]:
    history = thread_queries.read_thread([_Saver(tuples)], "run-1")
    assert history is not None
    return history.steps


class TestHowLongAStepTook:
    def test_a_step_is_timed_against_the_one_before_it(self) -> None:
        steps = _steps(
            [
                _Stub("2026-08-13T12:42:16.945680+00:00", step=0),
                _Stub("2026-08-13T12:42:18.736931+00:00", step=1),
            ]
        )
        assert steps[1].duration_ms == 1791

    def test_the_first_step_of_a_graph_has_nothing_to_measure_against(self) -> None:
        """`None`, never `0`.

        Zero is a claim — *this took no time* — and the first checkpoint of a
        run supports no such claim. The panel must be able to tell "instant"
        from "unknown", which is the same reason this repository forbids a
        non-finite number in a serialisable field: say it with `None`.
        """
        steps = _steps([_Stub("2026-08-13T12:42:16.945680+00:00", step=0)])
        assert steps[0].duration_ms is None

    def test_a_worker_is_timed_against_its_own_previous_step(self) -> None:
        """Interleaved namespaces, and the trap part 1 already paid for once.

        The parent's step 3 lands *after* the worker ran; differencing against
        whatever row happens to precede it in the list would charge the parent
        a worker's time and charge the worker the gap since the parent.
        """
        steps = _steps(
            [
                _Stub("2026-08-13T12:42:18.700000+00:00", step=2),
                _Stub("2026-08-13T12:42:18.800000+00:00", namespace="worker_web:a", step=0),
                _Stub("2026-08-13T12:42:23.800000+00:00", namespace="worker_web:a", step=1),
                _Stub("2026-08-13T12:42:24.700000+00:00", step=3),
            ]
        )
        assert [step.duration_ms for step in steps] == [None, None, 5000, 6000]

    def test_a_checkpoint_with_no_usable_timestamp_is_silent(self) -> None:
        """An unreadable `ts` reports nothing rather than guessing a zero."""
        steps = _steps([_Stub("2026-08-13T12:42:16+00:00", step=0), _Stub("", step=1)])
        assert steps[1].duration_ms is None

    def test_the_input_that_starts_a_turn_is_not_timed(self) -> None:
        """Found on screen, in the browser, against a real two-turn thread.

        `?w=morning-brief` → History → the `example.com` run read
        `Step 6 · input — 1m 36s`, and nothing took a minute and a half. A
        `source: "input"` checkpoint records what was *handed in*; no superstep
        ran. Differencing it against the previous turn's last checkpoint
        measures how long the person took to type, printed in the column that
        everywhere else means how long the graph took.

        It still advances the clock — the superstep *after* it is timed from
        here, which is right, because that is when this turn began.
        """
        steps = _steps(
            [
                _Stub("2026-08-13T12:42:16.000000+00:00", step=5),
                _Stub("2026-08-13T12:43:52.000000+00:00", step=6, source="input"),
                _Stub("2026-08-13T12:43:53.000000+00:00", step=7),
            ]
        )
        assert [step.duration_ms for step in steps] == [None, None, 1000]

    def test_a_clock_that_went_backwards_is_not_reported_as_negative(self) -> None:
        steps = _steps(
            [
                _Stub("2026-08-13T12:42:18.000000+00:00", step=0),
                _Stub("2026-08-13T12:42:16.000000+00:00", step=1),
            ]
        )
        assert steps[1].duration_ms is None


class _State(TypedDict, total=False):
    question: str
    answer: str
    messages: Annotated[list[Any], add_messages]


def _usage_graph() -> Any:
    """A real graph writing real `AIMessage`s with real `usage_metadata`.

    No model is called: the point under test is that what LangChain puts on a
    message survives into the checkpointer and can be read back, and a stubbed
    provider would prove only that a stub round-trips.
    """

    def think(state: _State) -> dict[str, Any]:
        return {
            "messages": [
                AIMessage(
                    content="thinking",
                    usage_metadata={
                        "input_tokens": 1436,
                        "output_tokens": 86,
                        "total_tokens": 1522,
                    },
                )
            ]
        }

    def answer(state: _State) -> dict[str, Any]:
        return {
            "answer": "done",
            "messages": [
                AIMessage(
                    content="done",
                    usage_metadata={
                        "input_tokens": 1487,
                        "output_tokens": 137,
                        "total_tokens": 1624,
                    },
                )
            ],
        }

    builder: StateGraph = StateGraph(_State)
    builder.add_node("think", think)
    builder.add_node("answer", answer)
    builder.add_edge(START, "think")
    builder.add_edge("think", "answer")
    builder.add_edge("answer", END)
    return builder


@pytest.fixture()
def usage_history() -> Any:
    saver = InMemorySaver()
    _usage_graph().compile(checkpointer=saver).invoke(
        {"question": "how many tracks?"},
        {"configurable": {"thread_id": "run-usage", "workflow_slug": "chinook-assistant"}},
    )
    history = thread_queries.read_thread(
        [saver], "run-usage", audience=Audience.DEVELOPER
    )
    assert history is not None
    return history


class TestWhatAStepCost:
    def test_a_step_reports_the_tokens_its_own_call_spent(self, usage_history: Any) -> None:
        spent = [step.tokens for step in usage_history.steps if step.tokens]
        assert [(t.input_tokens, t.output_tokens, t.total_tokens) for t in spent] == [
            (1436, 86, 1522),
            (1487, 137, 1624),
        ]

    def test_the_cumulative_channel_is_not_billed_again_on_every_row(
        self, usage_history: Any
    ) -> None:
        """The rule part 1 established, and the one this most easily breaks.

        Every checkpoint holds the *whole* message history, so summing the
        channel would charge the last step for the entire run and make the
        totals climb monotonically — a number that looks plausible on screen
        and is wrong everywhere but the final row.
        """
        totals = [step.tokens.total_tokens for step in usage_history.steps if step.tokens]
        assert totals == [1522, 1624]

    def test_a_step_that_spent_nothing_says_nothing(self, usage_history: Any) -> None:
        """`None`, not a zeroed row: a bookkeeping superstep did not cost zero
        tokens, it did not call a model at all."""
        assert usage_history.steps[0].tokens is None

    def test_a_provider_that_reports_no_usage_is_not_invented_a_number(self) -> None:
        saver = InMemorySaver()

        def mute(state: _State) -> dict[str, Any]:
            return {"answer": "done", "messages": [AIMessage(content="done")]}

        builder: StateGraph = StateGraph(_State)
        builder.add_node("mute", mute)
        builder.add_edge(START, "mute")
        builder.add_edge("mute", END)
        builder.compile(checkpointer=saver).invoke(
            {"question": "?"}, {"configurable": {"thread_id": "run-mute"}}
        )
        history = thread_queries.read_thread(
            [saver], "run-mute", audience=Audience.DEVELOPER
        )
        assert history is not None
        assert all(step.tokens is None for step in history.steps)
