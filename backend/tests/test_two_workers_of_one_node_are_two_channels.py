"""Two instances of one node are two channels, and only display may merge them.

`the-cost-of-one-more/05`. `_namespace` drops the instance id on purpose — a
panel grouping forty rows by name must call five dispatches of `worker_web`
one node (`memory-and-replay/37`). The same string was then the **state key**
for three readers that count how much of a cumulative channel they have
already reported, so two live instances of one node shared one counter: the
second one's tool calls came back as zero and its first superstep was timed
against the first one's clock.

The distinctness is LangGraph's, verified rather than assumed — a real `Send`
fan-out into one node yields `worker_web:<uuid-a>` and `worker_web:<uuid-b>`,
two namespaces that `_namespace` renders identically and `_channel_key` does
not.
"""

from __future__ import annotations

import types
from typing import Any

from langchain_core.messages import AIMessage

from openstategraph.api.audience import Audience
from openstategraph.api.threads import read_thread

WORKER_A = "worker_web:aaaaaaaa-1111-2222-3333-444444444444"
WORKER_B = "worker_web:bbbbbbbb-1111-2222-3333-444444444444"


def _call(index: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "search", "args": {"q": str(index)}, "id": f"c{index}"}],
    )


def _checkpoint(namespace: str, messages: list[Any], ts: str) -> Any:
    return types.SimpleNamespace(
        config={"configurable": {"thread_id": "t", "checkpoint_ns": namespace}},
        metadata={"step": 1, "source": "loop", "workflow_slug": "w"},
        checkpoint={
            "id": f"{namespace}-{ts}",
            "ts": ts,
            "channel_values": {"messages": messages},
            "updated_channels": ["messages"],
        },
        pending_writes=[],
    )


class _Saver:
    """A saver over hand-built tuples. `list` yields newest first, as sqlite's does."""

    def __init__(self, oldest_first: list[Any]) -> None:
        self._rows = list(reversed(oldest_first))

    def list(self, config: Any, *, limit: int | None = None, **_: Any) -> list[Any]:
        rows = self._rows
        if config is not None:
            thread_id = config["configurable"]["thread_id"]
            rows = [row for row in rows if row.config["configurable"]["thread_id"] == thread_id]
        return rows if limit is None else rows[:limit]


def _fanned_out() -> _Saver:
    """One supervisor, two subtasks, one `worker_web`.

    Worker A's channel holds six of its own messages; worker B's is a separate
    channel holding two of its own. Both render as `worker_web`.
    """
    return _Saver(
        [
            _checkpoint(WORKER_A, [_call(i) for i in range(6)], "2026-08-30T00:00:01+00:00"),
            _checkpoint(WORKER_B, [_call(i) for i in (100, 101)], "2026-08-30T00:00:02+00:00"),
        ]
    )


def _steps() -> list[Any]:
    history = read_thread([_fanned_out()], "t", audience=Audience.DEVELOPER)
    assert history is not None
    return history.steps


class TestTheSecondInstanceIsNotTheFirstOneAgain:
    def test_its_tool_calls_are_reported_rather_than_sliced_away(self) -> None:
        """`messages[6:]` of a two-message channel is empty — everything B did."""
        first, second = _steps()
        assert [call.name for call in first.tool_calls] == ["search"] * 6
        assert [call.arguments for call in second.tool_calls] == ['{"q": "100"}', '{"q": "101"}']

    def test_its_first_superstep_is_not_timed_against_another_graphs_clock(self) -> None:
        """`1000` ms was the gap between two unrelated graphs' timestamps.

        Not a duration of anything — a number that looked like one. A channel
        this reader has not seen has nothing to difference against, and says so
        with `None`, the same silence the parent's own first step gets.
        """
        assert [step.duration_ms for step in _steps()] == [None, None]


class TestDisplayStillGroupsThem:
    def test_both_rows_still_name_the_node_and_not_the_instance(self) -> None:
        """The half that was right. A panel must not grow a uuid per row."""
        assert [step.node for step in _steps()] == ["worker_web", "worker_web"]
        assert [step.namespace for step in _steps()] == [["worker_web"], ["worker_web"]]
