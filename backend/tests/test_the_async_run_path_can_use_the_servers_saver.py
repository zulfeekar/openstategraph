"""The streaming door drives `astream`, and the server's saver is synchronous.

`async-first/02` turned the run fold into an async generator. LangGraph's
async loop calls a checkpointer's **async** four (`aget_tuple`, `aput`,
`aput_writes`, `alist`), and the server's default saver — `SqliteSaver`, since
install-experience ticket 05 — raises `NotImplementedError` on every one of
them. Not a subtlety: without a bridge the first superstep of every streamed
run never happens.

That is a dependency the async charter (`docs/decisions/async-seam.md`) has
backwards — it sizes the async saver as phase **B**, after this one. Recorded
on the ticket; pinned here, because a rule about a library that nobody
re-checks is the defect class this project keeps paying for.

`memory.async_capable` is the bridge, and these tests pin both halves of what
it must do: make the async four work, and leave the sync four exactly as they
were. The second half is the one with a trap in it — `/api/runs`, the MCP
server and `load_workflow` all hold the same saver and all call it
synchronously, which is why the shared saver is wrapped at the async door
rather than replaced.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
from typing import Any, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.base import BaseCheckpointSaver  # noqa: E402
from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from openstategraph.memory import async_capable  # noqa: E402


class _State(TypedDict):
    trail: str


def _saver() -> SqliteSaver:
    saver = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    saver.setup()
    return saver


def _graph(checkpointer: Any) -> Any:
    builder: Any = StateGraph(_State)
    builder.add_node("step", lambda state: {"trail": state["trail"] + "!"})
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile(checkpointer=checkpointer)


CONFIG = {"configurable": {"thread_id": "t1"}}


def test_the_bare_server_saver_cannot_drive_an_async_run() -> None:
    """The measurement this whole file exists for, kept as a test.

    If a future `langgraph-checkpoint-sqlite` grows async support this fails,
    which is the correct outcome: the bridge becomes removable and somebody
    should be told.
    """
    graph = _graph(_saver())

    async def run() -> None:
        async for _ in graph.astream({"trail": "a"}, CONFIG):
            pass

    try:
        asyncio.run(run())
    except NotImplementedError as exc:
        assert "async" in str(exc)
    else:  # pragma: no cover - the day the library changes
        raise AssertionError(
            "SqliteSaver now supports async methods; memory.async_capable may be removable"
        )


def test_the_wrapped_saver_drives_an_async_run() -> None:
    graph = _graph(async_capable(_saver()))

    async def run() -> list[Any]:
        return [chunk async for chunk in graph.astream({"trail": "a"}, CONFIG)]

    assert asyncio.run(run()) == [{"step": {"trail": "a!"}}]


def test_a_synchronous_caller_cannot_tell_it_is_holding_a_wrapper() -> None:
    """`/api/runs`, the MCP server and `load_workflow` share this saver."""
    graph = _graph(async_capable(_saver()))

    assert graph.invoke({"trail": "a"}, CONFIG) == {"trail": "a!"}
    assert graph.get_state(CONFIG).values == {"trail": "a!"}
    assert len(list(graph.get_state_history(CONFIG))) == 3


def test_both_doors_write_the_same_thread() -> None:
    """One saver, two access patterns — a resume must find what a run wrote."""
    saver = async_capable(_saver())
    graph = _graph(saver)

    async def run() -> None:
        async for _ in graph.astream({"trail": "a"}, CONFIG):
            pass

    asyncio.run(run())

    assert graph.get_state(CONFIG).values == {"trail": "a!"}


def test_it_is_a_real_saver_because_compile_insists() -> None:
    """`StateGraph.compile` calls `ensure_valid_checkpointer`, which isinstances.

    Pinned because it is the whole reason the bridge is a subclass rather than
    the duck-typed adapter it would otherwise be — and a refactor that made it
    a plain wrapper would fail far away from here, at every compile.
    """
    assert isinstance(async_capable(_saver()), BaseCheckpointSaver)
