"""Every child a run announces is accounted for — `memory-and-replay` 54.

`spawn` says a child began. Until this module nothing ever said it stopped, so
a lane on a timeline had a start and no end, and the only way to draw a bar was
to end it where the next frame happened to arrive — which is the arrival-clock
guess `46` exists to stop.

**One close frame, not two.** AG-UI has `SUBAGENT_FINISHED` and
`SUBAGENT_ERROR`; we have one `settled` frame with an `outcome`, for the reason
`launch-readiness/176` settled the analogous question by adding a *value*
rather than a class: our `error` frame is **terminal for the whole run**, and a
second frame kind that ends one child while the run continues would make
`TERMINAL_EVENTS` a rule with an exception in it.

**`spawnId` is the join, and it is a new field rather than a reused one.**
`taskId` is a domain id and joins three of the four kinds honestly — a
`fanout` child's is the orchestrator's own subtask id, a `subagent`'s and an
`async`'s is the tool call id. It joins the fourth not at all: a `subgraph`
spawn has `taskId: null`. A field that is the join for three kinds and absent
for the fourth is not a join, so `spawnId` is minted by the watcher, is present
on both halves of every pair, and is what a reader matches on without first
having to know which kind it is looking at.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from conftest import ScriptedGraph, drive_fold

from openstategraph.compile.diagnostics import CompileDiagnostics

from openstategraph.api.streaming import (
    FRAME_FIELDS,
    RUN_EVENTS,
    SPAWN_OUTCOMES,
    TERMINAL_EVENTS,
    SpawnWatcher,
    _stream_run,
)


# --------------------------------------------------------------------------
# The vocabulary


def test_the_close_frame_is_declared_beside_the_open_one() -> None:
    assert "settled" in RUN_EVENTS
    assert "settled" not in TERMINAL_EVENTS
    assert FRAME_FIELDS["settled"] == (
        "spawnId", "kind", "parent", "label", "taskId", "namespace", "outcome",
        "seq", "elapsedMs",
    )


def test_the_open_frame_carries_the_join_field() -> None:
    """`46`'s composition gives it the clock; this is the field 54 adds."""
    assert "spawnId" in FRAME_FIELDS["spawn"]
    assert FRAME_FIELDS["spawn"][-2:] == ("seq", "elapsedMs")


def test_a_close_frame_carries_no_result_at_all() -> None:
    """The audience boundary, answered by not crossing it.

    AG-UI's `SUBAGENT_FINISHED` carries `result`. Ours does not, and the
    argument is not redaction but duplication: what a child produced already
    reaches the reader on the frame that revealed the completion — a worker's
    own `update.output`, already redacted a value at a time — so a copy here
    would be a second spelling of one fact, and the only one of the two that a
    future edit could forget to redact.
    """
    assert "result" not in FRAME_FIELDS["settled"]
    assert "outcome" in FRAME_FIELDS["settled"]


def test_the_outcomes_are_a_closed_set() -> None:
    assert SPAWN_OUTCOMES == ("ok", "error", "detached", "unknown")


# --------------------------------------------------------------------------
# Which kinds can be closed by observation


def _plan(owner: str, *tasks: tuple[str, str]) -> dict[str, Any]:
    return {
        "subtasks": {
            owner: [
                {"id": task_id, "instruction": "do it", "archetype": archetype}
                for task_id, archetype in tasks
            ]
        }
    }


def test_three_fanout_children_sharing_one_label_are_closed_one_by_one() -> None:
    """The case the join field exists for.

    Measured live on `stress-review` (2026-08-29): three `Send` children, all
    labelled `impact-analyst`, distinguished only by the orchestrator's own
    task ids. A close keyed on the label would close whichever bar it found.
    """
    watcher = SpawnWatcher()
    spawns = watcher.inspect(
        "lead", (), _plan("lead", ("task-1", "impact-analyst"),
                          ("task-2", "impact-analyst"),
                          ("task-3", "impact-analyst")), internal=False
    )
    assert [s["label"] for s in spawns] == ["impact-analyst"] * 3
    ids = [s["spawnId"] for s in spawns]
    assert len(set(ids)) == 3

    closed = watcher.settled("worker", (), {"worker_results": {"task-2": "done"}}, False)
    assert [c["spawnId"] for c in closed] == [ids[1]]
    assert closed[0]["outcome"] == "ok"
    assert closed[0]["taskId"] == "task-2"
    assert closed[0]["kind"] == "fanout"


def test_a_child_is_closed_once_however_often_its_result_is_re_read() -> None:
    watcher = SpawnWatcher()
    watcher.inspect("lead", (), _plan("lead", ("t1", "w")), internal=False)
    results = {"worker_results": {"t1": "done"}}

    assert len(watcher.settled("worker", (), results, False)) == 1
    assert watcher.settled("worker", (), results, False) == []


def test_a_result_for_a_child_nobody_announced_closes_nothing() -> None:
    """Strict in trusting: a close frame with no open frame is not a close."""
    assert SpawnWatcher().settled("worker", (), {"worker_results": {"ghost": "x"}}, False) == []


def _delegation(call_id: str, worker: str = "data-classifier") -> Any:
    return SimpleNamespace(
        tool_calls=[
            {"name": "task", "id": call_id,
             "args": {"subagent_type": worker, "description": "Classify it"}}
        ]
    )


def _answer(call_id: str, content: str = "PCI cardholder data.", status: str = "success") -> Any:
    return SimpleNamespace(
        type="tool", name="task", tool_call_id=call_id, content=content, status=status
    )


def test_a_subagent_is_closed_by_the_answer_its_call_id_names() -> None:
    """Measured live on `stress-deep` (2026-08-29, `ollama:gpt-oss:120b-cloud`):

        3.2s  model  ai   calls=['task/76783c85-…']
        5.1s  tools  tool(name=task tool_call_id=76783c85-…)

    Both frames on the `updates` rail this fold already walks, in the same
    namespace, two seconds apart. The pair is `launch-readiness/178`'s reading,
    reused rather than re-derived.
    """
    watcher = SpawnWatcher()
    announced = watcher.inspect("model", ("deep:abc",), {"messages": [_delegation("call_1")]}, True)
    # The first frame of a namespace also announces the namespace itself; the
    # delegation is the second, which is what this is about.
    opened = [s for s in announced if s["kind"] == "subagent"]
    assert len(opened) == 1

    closed = watcher.settled("tools", ("deep:abc",), {"messages": [_answer("call_1")]}, True)
    assert [c["spawnId"] for c in closed] == [opened[0]["spawnId"]]
    assert closed[0]["outcome"] == "ok"
    assert closed[0]["label"] == "data-classifier"


def test_two_delegations_to_the_same_worker_close_independently() -> None:
    watcher = SpawnWatcher()
    first = watcher.inspect("model", (), {"messages": [_delegation("c1")]}, True)[0]
    second = watcher.inspect("model", (), {"messages": [_delegation("c2")]}, True)[0]

    closed = watcher.settled("tools", (), {"messages": [_answer("c2")]}, True)
    assert [c["spawnId"] for c in closed] == [second["spawnId"]]
    assert first["spawnId"] != second["spawnId"]


def test_a_delegation_that_reached_no_worker_closes_with_an_error() -> None:
    """`deepagents` answers an undeclared worker with an ordinary successful
    `ToolMessage`; `delegations.py` already knows that sentence, so this reads
    it rather than inventing a second test for the same string."""
    watcher = SpawnWatcher()
    opened = watcher.inspect("model", (), {"messages": [_delegation("c9", "nobody")]}, True)[0]
    closed = watcher.settled(
        "tools", (),
        {"messages": [_answer("c9", "We cannot invoke subagent nobody because it does not exist")]},
        True,
    )
    assert closed[0]["spawnId"] == opened["spawnId"]
    assert closed[0]["outcome"] == "error"


def test_a_delegation_the_tool_rail_reports_failed_closes_with_an_error() -> None:
    watcher = SpawnWatcher()
    opened = watcher.inspect("model", (), {"messages": [_delegation("c8")]}, True)[0]
    closed = watcher.settled("tools", (), {"messages": [_answer("c8", "boom", status="error")]}, True)
    assert (closed[0]["spawnId"], closed[0]["outcome"]) == (opened["spawnId"], "error")


def test_a_mounted_workflow_is_closed_when_its_own_node_reports() -> None:
    """A `subgraph` spawn has no `taskId`, so it is joined by `spawnId` alone.

    Measured live on `stress-review`: the `audit` mount is announced when its
    namespace first appears and reports as an ordinary top-level `update` on
    the node that owns it, seventy-three frames later.
    """
    watcher = SpawnWatcher({"audit": "audit"})
    watcher.inspect("in1", (), {}, internal=False)
    opened = watcher.inspect("linter", ("audit:594e8dad",), {}, internal=False)[0]
    assert (opened["kind"], opened["taskId"]) == ("subgraph", None)

    assert watcher.settled("other", (), {}, False) == []
    closed = watcher.settled("audit", (), {}, False)
    assert [c["spawnId"] for c in closed] == [opened["spawnId"]]
    assert closed[0]["outcome"] == "ok"


def test_a_mounted_node_a_revise_lap_re_enters_is_closed_once() -> None:
    """One announcement, one close. The watcher already refuses to announce a
    mounted node twice (a `Send` worker gets a fresh checkpoint id per
    instance); a second close would be an end with no beginning."""
    watcher = SpawnWatcher({"worker": "worker"})
    watcher.inspect("lead", (), {}, internal=False)
    watcher.inspect("agent", ("worker:aaa",), {}, internal=False)

    assert len(watcher.settled("worker", (), {}, False)) == 1
    assert watcher.settled("worker", (), {}, False) == []


def test_a_background_task_is_never_closed_by_observation() -> None:
    """`async` is the kind that cannot be closed, and this is the assertion
    that says so out loud.

    The parent does not wait: `start_async_task` hands back an id and the child
    runs on a desk outside the run. Its terminal status is visible only if the
    agent happens to loop again and the desk is polled — so a close driven by
    observation would fire on some runs and not others, which is the very
    defect (*a frame that fires for three kinds and silently not the fourth*)
    one level down. It is closed at the end of the stream instead, as
    `detached`.
    """
    watcher = SpawnWatcher()
    message = SimpleNamespace(
        tool_calls=[{"name": "start_async_task", "id": "call_a",
                     "args": {"subagent_type": "researcher", "description": "Count"}}]
    )
    opened = watcher.inspect("agent_deep", (), {"messages": [message]}, True)[0]
    assert opened["kind"] == "async"

    assert watcher.settled("agent_deep", (), {"worker_results": {"call_a": "x"}}, True) == []
    assert watcher.settled("tools", (), {"messages": [_answer("call_a")]}, True) == []

    assert [(c["spawnId"], c["outcome"]) for c in watcher.abandoned()] == [
        (opened["spawnId"], "detached")
    ]


def test_the_sweep_closes_what_the_run_never_accounted_for() -> None:
    watcher = SpawnWatcher()
    opened = watcher.inspect("lead", (), _plan("lead", ("t1", "w")), internal=False)[0]
    assert [(c["spawnId"], c["outcome"]) for c in watcher.abandoned()] == [
        (opened["spawnId"], "unknown")
    ]


def test_the_sweep_says_nothing_about_a_child_already_closed() -> None:
    watcher = SpawnWatcher()
    watcher.inspect("lead", (), _plan("lead", ("t1", "w")), internal=False)
    watcher.settled("worker", (), {"worker_results": {"t1": "done"}}, False)
    assert watcher.abandoned() == []


def test_the_sweep_is_spent_once() -> None:
    """`_stream_run` reaches its terminal frame by one path per run, but the
    error path and the done path are two pieces of code; a sweep that could
    run twice would double every lane."""
    watcher = SpawnWatcher()
    watcher.inspect("lead", (), _plan("lead", ("t1", "w")), internal=False)
    assert len(watcher.abandoned()) == 1
    assert watcher.abandoned() == []


# --------------------------------------------------------------------------
# On the wire


class _Graph:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        return iter(self._chunks)

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _frames(chunks: list[Any], audience: Any = None) -> list[tuple[str, dict[str, Any]]]:
    from openstategraph.api.audience import Audience

    raw = drive_fold(
        _stream_run(
            ScriptedGraph(_Graph(chunks)),
            {"question": "q"},
            {"configurable": {"thread_id": "t"}},
            SimpleNamespace(warnings=[]),
            {"lead": "lead", "worker": "worker"},
            SimpleNamespace(diagnostics=CompileDiagnostics()),
            "t",
            audience or Audience.DEVELOPER,
        )
    )
    out: list[tuple[str, dict[str, Any]]] = []
    for frame in raw:
        name = frame.split("event: ", 1)[1].split("\n", 1)[0]
        out.append((name, json.loads(frame.split("data: ", 1)[1])))
    return out


_FANOUT = [
    ((), "updates", {"lead": _plan("lead", ("t1", "analyst"), ("t2", "analyst"))}),
    ((), "updates", {"worker": {"worker_results": {"t1": "one"}}}),
    ((), "updates", {"worker": {"worker_results": {"t2": "two"}}}),
]


def _through_the_transport(chunks: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    """The frames as the live transport pulls them — a fresh task per frame."""
    import asyncio

    from openstategraph.api.audience import Audience
    from openstategraph.api.streaming import stop_when_client_leaves

    async def still_here() -> dict[str, Any]:
        await asyncio.sleep(3600)
        return {"type": "http.request"}

    async def go() -> list[str]:
        run = _stream_run(
            ScriptedGraph(_Graph(chunks)),
            {"question": "q"},
            {"configurable": {"thread_id": "t"}},
            SimpleNamespace(warnings=[]),
            {"lead": "lead", "worker": "worker"},
            SimpleNamespace(diagnostics=CompileDiagnostics()),
            "t",
            Audience.DEVELOPER,
        )
        return [frame async for frame in stop_when_client_leaves(run, still_here)]

    read: list[tuple[str, dict[str, Any]]] = []
    for frame in asyncio.run(go()):
        head, _, body = frame.partition("\ndata: ")
        read.append((head[len("event: ") :], json.loads(body.rstrip("\n"))))
    return read


def test_every_spawn_on_the_wire_is_joined_to_a_close() -> None:
    frames = _frames(list(_FANOUT))
    opened = [d["spawnId"] for name, d in frames if name == "spawn"]
    closed = [d["spawnId"] for name, d in frames if name == "settled"]

    assert len(opened) == 2
    assert sorted(closed) == sorted(opened)


def test_a_bar_has_two_ends_and_the_second_is_later_than_the_first() -> None:
    """The whole point of the ticket: `50` can draw a bar from these two."""
    frames = _frames(list(_FANOUT))
    opened = {d["spawnId"]: d for name, d in frames if name == "spawn"}
    for name, d in frames:
        if name != "settled":
            continue
        assert d["elapsedMs"] >= opened[d["spawnId"]]["elapsedMs"]
        assert d["seq"] > opened[d["spawnId"]]["seq"]


def test_a_close_arrives_before_the_terminal_frame_that_ends_the_run() -> None:
    frames = _frames([_FANOUT[0]])
    names = [name for name, _ in frames]
    assert names[-1] == "done"
    assert names[-2] == "settled" and names[-3] == "settled"
    assert {d["outcome"] for name, d in frames if name == "settled"} == {"unknown"}


def test_every_swept_close_is_dated_not_only_the_first() -> None:
    """`launch-readiness/108`'s defect, found again on a live run of this very
    feature: four children, and the second sweep frame carried no `seq` at all.

    The transport resumes this generator from a fresh context per frame, so a
    `_sse` call made after a yield finds no clock bound and mints nothing. Two
    children left open is the smallest case that can show it — one would pass
    on the binding the pull above already did.

    Driven **through** `stop_when_client_leaves` rather than with a bare
    `async for`, for the reason
    `test_the_frame_clock_survives_the_transport.py` gives: a plain drain runs
    every frame in one context and the defect is invisible in it. The fold was
    never wrong; the driver was.
    """
    chunks = [((), "updates", {"lead": _plan("lead", ("t1", "a"), ("t2", "a"))})]
    closes = [d for name, d in _through_the_transport(chunks) if name == "settled"]

    assert len(closes) == 2
    for close in closes:
        assert isinstance(close.get("seq"), int)
        assert isinstance(close.get("elapsedMs"), int)
    assert closes[0]["seq"] != closes[1]["seq"]


def test_a_customers_close_frame_is_the_developers_close_frame() -> None:
    """A cadence is not a disclosure, and neither is *that* a child finished."""
    from openstategraph.api.audience import Audience

    def closes(audience: Any) -> list[dict[str, Any]]:
        return [d for name, d in _frames(list(_FANOUT), audience) if name == "settled"]

    assert closes(Audience.CUSTOMER) == closes(Audience.DEVELOPER)
    assert closes(Audience.CUSTOMER) != []
