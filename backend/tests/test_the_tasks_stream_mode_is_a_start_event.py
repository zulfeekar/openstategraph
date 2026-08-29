"""`stream_mode="tasks"` on the installed LangGraph, field by field.

`memory-and-replay` 48. `src/view/ask/timeline.ts` documented a limitation it
believed was structural — *"LangGraph's `updates` stream reports a node only
after it finishes, there is no start event to subtract"* — and the second half
of that sentence was false. LangGraph publishes seven stream modes;
`api/streaming.py` asks for three. A per-task **start** event has been
available the whole time, and nobody subscribed to it.

This file is the record, and it is executable for the reason
`test_a_library_default_is_never_literalised.py` gives: a library fact written
into prose has no way to fail, and this one was wrong in a docstring for
months. Every claim below is derived by **running a graph on the installed
package**, not read off a page — and where the page and the package disagree,
one of these tests says so out loud.

The four questions the ticket had to decide, and where each is answered:

- *Is there really a start?* `TestATaskAnnouncesItselfBeforeItRuns`.
- *Does it carry a clock?* `TestNoPayloadCarriesATime` — **no**, which is why
  this finding does not make ticket 46 unnecessary. It makes it the
  prerequisite.
- *Does the id join to what we already emit?* `TestTheIdentityIsTheRuntimesOwn`
  — the ids are runtime UUIDs; every `taskId` on our own wire is a domain id
  (`task-1`, a tool-call id) minted by our nodes. Two vocabularies, and the
  only bridge is the checkpoint namespace.
- *What does it cost?* `TestTheCost` — two frames per task, and nothing else.

Deliberately scripted rather than model-driven: the shape of a task event does
not depend on what a model said, and a test that needs a provider is a test
nobody runs. The frame *proportions* on a live run are recorded in
`docs/decisions/the-tasks-stream-mode-2026-08-29.md`, which is where a measured
number belongs.
"""

from __future__ import annotations

import asyncio
import operator
from typing import Annotated, Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict


class _State(TypedDict):
    topic: str
    results: Annotated[list, operator.add]


async def _plan(state: _State) -> dict[str, Any]:
    return {"topic": state["topic"]}


def _dispatch(state: _State) -> list[Send]:
    """Three workers in one superstep — the case `timeline.ts` names as the
    one its inferred clock gets wrong."""
    return [Send("worker", {"topic": state["topic"], "i": i, "results": []}) for i in range(3)]


async def _worker(state: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0.01 * (state["i"] + 1))
    return {"results": [f"w{state['i']}"]}


async def _join(state: _State) -> dict[str, Any]:
    return {"results": []}


def _fan_out() -> StateGraph:
    return (
        StateGraph(_State)
        .add_node("plan", _plan)
        .add_node("worker", _worker)
        .add_node("join", _join)
        .add_edge(START, "plan")
        .add_conditional_edges("plan", _dispatch, ["worker"])
        .add_edge("worker", "join")
        .add_edge("join", END)
    )


async def _stream(graph: Any, modes: list[str], thread: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    async for chunk in graph.astream(
        {"topic": "x", "results": []},
        {"configurable": {"thread_id": thread}},
        stream_mode=modes,
        # Both of the settings `api/streaming.py` actually sends, because the
        # ticket's third worry was that `tasks` collides with them.
        subgraphs=True,
        version="v2",
    ):
        frames.append(chunk)
    return frames


def _run(modes: list[str], thread: str, *, checkpointer: Any = None) -> list[dict[str, Any]]:
    graph = _fan_out().compile(checkpointer=checkpointer or InMemorySaver())
    return asyncio.run(_stream(graph, modes, thread))


def _is_finish(payload: dict[str, Any]) -> bool:
    """A finish event is the one that carries a result. There is no `type`
    discriminator inside the payload — `TasksStreamPart.data` is a union of
    `TaskPayload` and `TaskResultPayload`, and telling them apart is the
    reader's job."""
    return "result" in payload


class TestATaskAnnouncesItselfBeforeItRuns:
    def test_every_node_gets_a_start_and_a_finish(self) -> None:
        frames = _run(["updates", "tasks"], "t-start")
        tasks = [f["data"] for f in frames if f["type"] == "tasks"]

        starts = [t for t in tasks if not _is_finish(t)]
        finishes = [t for t in tasks if _is_finish(t)]

        # plan, three workers, join.
        assert [t["name"] for t in starts] == ["plan", "worker", "worker", "worker", "join"]
        assert sorted(t["id"] for t in starts) == sorted(t["id"] for t in finishes)

    def test_the_start_arrives_before_the_update_that_reports_the_same_node(self) -> None:
        """The whole point. `updates` is a completion report; this is not."""
        frames = _run(["updates", "tasks"], "t-order")
        order = [
            ("start", f["data"]["name"])
            if f["type"] == "tasks" and not _is_finish(f["data"])
            else ("finish", f["data"]["name"])
            if f["type"] == "tasks"
            else ("update", next(iter(f["data"])))
            for f in frames
        ]

        assert order.index(("start", "plan")) < order.index(("update", "plan"))
        assert order.index(("start", "worker")) < order.index(("update", "worker"))

    def test_a_start_payload_carries_the_nodes_input(self) -> None:
        """`id`, `name`, `input`, `triggers` — and `metadata` only when the
        task config carried user-meaningful keys, which a bare graph's does
        not. `NotRequired` in the TypedDict, absent here."""
        frames = _run(["tasks"], "t-shape")
        start = next(f["data"] for f in frames if not _is_finish(f["data"]))

        assert set(start) == {"id", "name", "input", "triggers"}
        assert start["input"] == {"topic": "x", "results": []}
        # A **tuple**, though `TaskPayload` annotates `list[str]`. Harmless
        # over JSON, which renders both as an array, and worth pinning anyway:
        # a reader who does `payload["triggers"].append(...)` on the strength
        # of the annotation gets an AttributeError from a type that promised
        # otherwise.
        assert start["triggers"] == ("branch:to:plan",)

    def test_a_finish_payload_carries_the_result_and_a_place_for_the_error(self) -> None:
        """`error` is a **per-task** field, which our `error` frame is not:
        ours ends the run. A task that failed inside a fan-out while its
        siblings succeeded is expressible here and nowhere else on our wire."""
        frames = _run(["tasks"], "t-finish")
        finish = next(f["data"] for f in frames if _is_finish(f["data"]))

        assert set(finish) == {"id", "name", "error", "result", "interrupts"}
        assert finish["error"] is None
        assert finish["result"] == {"topic": "x"}


class TestNoPayloadCarriesATime:
    """The finding that decides the order of this map.

    A start event answers *when did this begin* only if something stamps it.
    Nothing in either payload does, so `tasks` supplements ticket 46's clock
    and does not replace it — subscribing without 46 would move the guess from
    "the gap since the previous frame" to "the gap since the start frame
    arrived", which is a better guess measured by the same borrowed clock.
    """

    def test_neither_a_start_nor_a_finish_has_a_time_field(self) -> None:
        frames = _run(["tasks"], "t-clock")
        assert frames

        for frame in frames:
            for key in frame["data"]:
                assert "time" not in key.lower()
                assert key not in {"ts", "at", "started", "finished"}

    def test_debug_is_the_one_mode_that_does_stamp_and_it_is_not_free(self) -> None:
        """`debug` wraps exactly these payloads with `step` and a server
        `timestamp` — and with every checkpoint's **full state values**, which
        is why it is not the cheap way to get a clock. Recorded so nobody
        reaches for it on the strength of the timestamp alone."""
        frames = _run(["debug"], "t-debug")
        kinds = {f["data"]["type"] for f in frames}

        assert kinds == {"task", "task_result", "checkpoint"}
        assert all({"step", "timestamp", "type", "payload"} == set(f["data"]) for f in frames)
        assert any("values" in f["data"]["payload"] for f in frames if f["data"]["type"] == "checkpoint")


class TestTheIdentityIsTheRuntimesOwn:
    def test_three_concurrent_workers_get_three_distinct_ids(self) -> None:
        """What the inferred clock cannot do. `updates` reports all three as
        `{"worker": ...}` with nothing to tell them apart, so the timeline
        "attributes one shared gap to whichever frame arrived"."""
        frames = _run(["tasks"], "t-ids")
        workers = [f["data"] for f in frames if f["data"]["name"] == "worker"]

        assert len({t["id"] for t in workers}) == 3
        assert [t["input"]["i"] for t in workers if not _is_finish(t)] == [0, 1, 2]

    def test_the_id_is_not_any_id_our_own_frames_carry(self) -> None:
        """Two vocabularies, and this is the one that must not be conflated —
        the `loop`/`slug` mistake in a new costume. Our `taskId` is a planner's
        subtask id (`task-1`) or a tool-call id, minted by our own nodes and
        living in graph state. LangGraph's is a UUID minted per task per
        superstep, and nothing in state ever holds it."""
        frames = _run(["tasks"], "t-vocab")
        ids = {f["data"]["id"] for f in frames}

        assert all(len(i) == 36 and i.count("-") == 4 for i in ids)
        assert not any(i.startswith("task-") for i in ids)

    def test_the_bridge_is_the_namespace_not_a_field(self) -> None:
        """A subgraph's own task events arrive under `("<node>:<parent id>",)`
        — so the parent link *is* expressible, and it is the string our frames
        already carry as `namespace`. This is the join that exists."""

        class _Sub(TypedDict):
            v: str

        async def _inner(state: _Sub) -> dict[str, Any]:
            return {"v": state["v"] + "!"}

        sub = (
            StateGraph(_Sub)
            .add_node("inner", _inner)
            .add_edge(START, "inner")
            .add_edge("inner", END)
            .compile()
        )
        parent = (
            StateGraph(_Sub)
            .add_node("child", sub)
            .add_edge(START, "child")
            .add_edge("child", END)
            .compile(checkpointer=InMemorySaver())
        )

        frames = asyncio.run(_stream_sub(parent))
        top = next(f for f in frames if f["ns"] == () and f["data"]["name"] == "child")
        nested = next(f for f in frames if f["ns"] != ())

        assert nested["ns"] == (f"child:{top['data']['id']}",)


async def _stream_sub(graph: Any) -> list[dict[str, Any]]:
    frames = []
    async for chunk in graph.astream(
        {"v": "a"},
        {"configurable": {"thread_id": "t-ns"}},
        stream_mode=["tasks"],
        subgraphs=True,
        version="v2",
    ):
        frames.append(chunk)
    return frames


class TestTheCost:
    def test_subscribing_adds_exactly_two_frames_per_task_and_nothing_else(self) -> None:
        """Measured rather than estimated, which is what the ticket asked for.
        The other three modes emit exactly what they emitted before — `tasks`
        is additive, the way `custom` was."""
        without = _run(["updates", "messages", "custom"], "t-cost-a")
        with_tasks = _run(["updates", "messages", "custom", "tasks"], "t-cost-b")

        added = [f for f in with_tasks if f["type"] == "tasks"]
        assert len(added) == 10  # five tasks, start and finish
        assert [f["data"] for f in without] == [
            f["data"] for f in with_tasks if f["type"] != "tasks"
        ]

    def test_it_does_not_require_a_checkpointer_here_though_the_page_says_it_does(self) -> None:
        """A doc and an installed package disagreeing, recorded rather than
        resolved in someone's favour. `/oss/python/langgraph/streaming` says
        *"Requires a checkpointer"* for both `tasks` and `checkpoints`; on
        langgraph 1.2.10 the task events are emitted from the Pregel loop's
        `tick`, before any saver is consulted, and arrive in full without one.

        The standing rule is that where the two disagree the installed version
        wins — but this one is pinned rather than acted on, because every run
        in this product already has a checkpointer and a graph that quietly
        depends on an undocumented behaviour is a bad trade for nothing.
        """
        graph = _fan_out().compile()  # no checkpointer at all
        frames = asyncio.run(_stream(graph, ["tasks"], "t-nocp"))

        assert len(frames) == 10
        assert {f["data"]["name"] for f in frames} == {"plan", "worker", "join"}


@pytest.mark.parametrize("mode", ["tasks", "checkpoints", "debug"])
def test_the_fold_can_already_decode_a_mode_it_does_not_ask_for(mode: str) -> None:
    """`_stream_part` reads `{"type", "ns", "data"}` generically, so the day
    someone adds a mode the decoder is not the thing that breaks — the fold's
    `if mode == ...` chain simply ignores it. That is what makes this a
    subscription decision rather than a rewrite."""
    from openstategraph.api.streaming import _stream_part

    decoded = _stream_part({"type": mode, "ns": (), "data": {"id": "x"}})

    assert decoded == ((), mode, {"id": "x"})
