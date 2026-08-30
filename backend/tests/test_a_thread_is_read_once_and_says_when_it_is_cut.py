"""A thread is walked once, and a thread that was cut off says so.

`the-cost-of-one-more/06`. The `messages` channel is cumulative — verified
against a real `InMemorySaver` rather than taken from this module's own
docstrings, which is the whole reason `test_the_premise_is_the_stores_and_not_a_docstrings`
below exists. `read_thread` then walked that whole cumulative list once per
checkpoint, three separate times, and rendered it a fourth: ×3.76 per doubling
of the checkpoint count, which is a quadratic bounded only by a cap of 200 that
nothing in the response mentioned.

Both halves are pinned here, and neither is a stopwatch: **operations counted,
not seconds asserted** — a wall-clock assertion is a flaky test, and the claim
worth defending is the complexity class rather than the machine.
"""

from __future__ import annotations

import types
from typing import Annotated, Any, TypedDict

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from openstategraph.api.audience import Audience
from openstategraph.api.main import create_app
from openstategraph.api.threads import MAX_READ_LIMIT, list_threads, read_thread


class _Meter:
    def __init__(self) -> None:
        self.touched = 0


class _CountedMessages(list):  # type: ignore[type-arg]
    """A `messages` channel that counts how many of its elements were looked at.

    A `list` subclass rather than a wrapper, because `_values` hands the raw
    channel value on and every reader tests it with `isinstance(..., list)`.
    Iteration counts lazily, so a render that stops at the value cap is charged
    only for what it consumed.
    """

    def __init__(self, items: list[Any], meter: _Meter) -> None:
        super().__init__(items)
        self._meter = meter

    def __iter__(self) -> Any:
        for item in list.__iter__(self):
            self._meter.touched += 1
            yield item

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, slice):
            taken = list.__getitem__(self, key)
            self._meter.touched += len(taken)
            return taken
        self._meter.touched += 1
        return list.__getitem__(self, key)


def _checkpoint(index: int, messages: Any, *, namespace: str = "agent:one") -> Any:
    return types.SimpleNamespace(
        config={"configurable": {"thread_id": "t", "checkpoint_ns": namespace}},
        metadata={"step": index, "source": "loop", "workflow_slug": "w", "session_id": "s"},
        checkpoint={
            "id": f"ck{index}",
            "ts": f"2026-08-30T00:{index // 60:02d}:{index % 60:02d}+00:00",
            "channel_values": {"messages": messages, "answer": "a" * 200},
            "updated_channels": ["messages"],
        },
        pending_writes=[],
    )


class _Saver:
    """Hand-built tuples, newest first, the way a real saver's `list` yields."""

    def __init__(self, oldest_first: list[Any]) -> None:
        self._rows = list(reversed(oldest_first))

    def list(
        self, config: Any, *, filter: Any = None, before: Any = None, limit: int | None = None
    ) -> list[Any]:
        rows = self._rows
        if config is not None:
            thread_id = config["configurable"]["thread_id"]
            rows = [row for row in rows if row.config["configurable"]["thread_id"] == thread_id]
        if filter:
            rows = [
                row
                for row in rows
                if all((row.metadata or {}).get(key) == value for key, value in filter.items())
            ]
        return rows if limit is None else rows[:limit]


def _thread(checkpoints: int, *, meter: _Meter | None = None) -> _Saver:
    """`checkpoints` supersteps of one thread, with `messages` accumulating.

    Each message is longer than the rendered-value cap on purpose: that is the
    realistic shape (a model's turn is not four characters) and it makes the
    count of elements a render has to touch a property of the cap rather than
    of the history's length.
    """
    body = "x" * 4_100
    messages: list[Any] = []
    rows = []
    for index in range(checkpoints):
        messages = messages + [
            AIMessage(
                content=body,
                tool_calls=[{"name": "query", "args": {"i": index}, "id": f"c{index}"}],
            ),
            ToolMessage(content=body, tool_call_id=f"c{index}"),
        ]
        channel: Any = list(messages)
        if meter is not None:
            channel = _CountedMessages(messages, meter)
        rows.append(_checkpoint(index, channel))
    return _Saver(rows)


def _touched(checkpoints: int) -> int:
    meter = _Meter()
    history = read_thread(
        [_thread(checkpoints, meter=meter)], "t", audience=Audience.DEVELOPER, limit=MAX_READ_LIMIT
    )
    assert history is not None and len(history.steps) == checkpoints
    return meter.touched


class TestThePremiseIsTheStoresAndNotADocstrings:
    def test_a_real_saver_writes_the_whole_history_into_every_checkpoint(self) -> None:
        """The claim the fold was deleted on, checked against LangGraph itself.

        Three docstrings in `api/threads.py` say the channel is cumulative. A
        docstring in this repository has been wrong before — which is why this
        runs a real graph through a real checkpointer and reads the lengths
        back rather than believing any of the three.
        """

        class _State(TypedDict, total=False):
            messages: Annotated[list, add_messages]

        builder: StateGraph = StateGraph(_State)
        builder.add_node("a", lambda state: {"messages": [AIMessage(content="one")]})
        builder.add_node("b", lambda state: {"messages": [AIMessage(content="two")]})
        builder.add_edge(START, "a")
        builder.add_edge("a", "b")
        builder.add_edge("b", END)
        saver = InMemorySaver()
        builder.compile(checkpointer=saver).invoke({"messages": []}, {"configurable": {"thread_id": "t"}})

        lengths = [
            len((row.checkpoint.get("channel_values") or {}).get("messages") or [])
            for row in reversed(list(saver.list({"configurable": {"thread_id": "t"}})))
        ]
        assert lengths == sorted(lengths), "not cumulative — the fold cannot be collapsed"
        assert lengths[-1] == 2


class TestTheThreadIsWalkedOnce:
    def test_doubling_the_checkpoints_does_not_quadruple_the_work(self) -> None:
        """The complexity class, counted rather than timed.

        Before: `_ToolCallReader.__init__` walked every checkpoint's whole
        cumulative channel, `_messages` copied it again for the tool reader and
        a third time for the usage reader, and `_text` rendered every message
        of it into a string that was then thrown away above 4,000 characters —
        four walks of an M that itself grows with C. ×3.76 per doubling,
        measured. Linear work doubles.
        """
        small, large = _touched(40), _touched(80)
        assert large < small * 2.5, (
            f"{small} element reads at C=40 and {large} at C=80 — a ratio of "
            f"{large / small:.2f}. Doubling the checkpoints of a thread must "
            "roughly double the work of reading it, not quadruple it."
        )

    def test_the_work_is_bounded_by_what_the_read_returns(self) -> None:
        """Each message read once for attribution, plus a bounded render per row."""
        assert _touched(80) <= 80 * 20


class TestACutThreadSaysSo:
    def test_a_thread_longer_than_the_read_reports_the_truncation(self) -> None:
        history = read_thread([_thread(30)], "t", limit=10)
        assert history is not None
        assert len(history.steps) == 10
        assert history.truncation is not None
        assert history.truncation.kept == 10
        assert history.truncation.end == "oldest"
        assert "Older ones are stored" in history.truncation.message

    def test_a_thread_that_fits_reports_nothing(self) -> None:
        history = read_thread([_thread(4)], "t", limit=10)
        assert history is not None
        assert history.truncation is None

    def test_the_step_count_still_names_the_whole_thread_not_the_page(self) -> None:
        """`thread.steps` is what was read; the truncation is what was not."""
        history = read_thread([_thread(30)], "t", limit=10)
        assert history is not None
        assert history.thread.steps == 10


class TestTheDoorCanBeAskedForMore:
    @staticmethod
    def _client(tmp_path: Any) -> TestClient:
        return TestClient(create_app(workflows_root=tmp_path))

    def test_the_route_takes_a_limit_so_a_long_thread_is_readable(self, tmp_path: Any) -> None:
        client = self._client(tmp_path)
        parameters = client.app.openapi()["paths"]["/api/threads/{thread_id}"]["get"]  # type: ignore[attr-defined]
        assert "limit" in {parameter["name"] for parameter in parameters["parameters"]}

    def test_the_ceiling_is_high_enough_to_read_a_long_thread_whole(self) -> None:
        assert MAX_READ_LIMIT >= 2_000


class TestAListingFindsAWorkflowOlderThanItsScan:
    def test_a_slug_whose_runs_are_older_than_the_window_is_still_listed(self) -> None:
        """The filter ran *after* the scan, so recent noise hid an older workflow.

        `_SCAN_FLOOR` is 400 checkpoints. Five hundred belonging to one
        workflow used to be enough to make `?workflow_slug=` answer "this
        workflow has never run" about a workflow that had.
        """
        rows = []
        for index in range(500):
            row = _checkpoint(index, [])
            row.config = {"configurable": {"thread_id": f"noise-{index}"}}
            row.metadata = {"step": 0, "source": "loop", "workflow_slug": "loud"}
            rows.append(row)
        wanted = _checkpoint(0, [])
        wanted.config = {"configurable": {"thread_id": "quiet-1"}}
        wanted.metadata = {"step": 0, "source": "loop", "workflow_slug": "quiet"}
        saver = _Saver([wanted, *rows])

        listed = list_threads([saver], workflow_slug="quiet")
        assert [row.thread_id for row in listed] == ["quiet-1"]


@pytest.mark.parametrize("checkpoints", [1, 2, 7])
def test_a_short_thread_reads_back_exactly_as_it_did(checkpoints: int) -> None:
    """The refactor is a cost change, not a behaviour change."""
    history = read_thread([_thread(checkpoints)], "t", audience=Audience.DEVELOPER)
    assert history is not None
    assert [step.step for step in history.steps] == list(range(checkpoints))
    # One request per superstep; its answer lands in the same one and is not
    # listed twice.
    assert [len(step.tool_calls) for step in history.steps] == [1] * checkpoints


class TestTheTerminalSaysItToo:
    """`threads show` is a surface, and a cap nobody can see is the whole defect."""

    def test_it_prints_the_truncation_above_the_steps(
        self, monkeypatch: Any, capsys: Any, tmp_path: Any
    ) -> None:
        from openstategraph import cli
        from openstategraph.api import threads as thread_queries

        monkeypatch.setattr(
            thread_queries,
            "read_thread",
            lambda *_, **__: read_thread([_thread(30)], "t", limit=10),
        )
        capsys.readouterr()
        code = cli.main(["threads", "show", "t", "--workflows-root", str(tmp_path)])

        out = capsys.readouterr().out
        assert code == cli.EXIT_OK
        assert "truncated:" in out
        assert "Older ones are stored" in out
