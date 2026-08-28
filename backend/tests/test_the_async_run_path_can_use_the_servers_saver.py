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


class TestTheBridgeIsTheDestinationAfterAll:
    """Phase B, measured (`async-first/03`, 2026-08-28): the bridge is kept.

    The ticket asked one question — does the bridge cost enough, under real
    concurrency, to justify a genuine `AsyncSqliteSaver`? Measured on the
    installed `langgraph-checkpoint-sqlite 3.1.1` / `aiosqlite 0.22.1`, on
    twelve cores (so `asyncio.to_thread` has a 16-worker pool):

    ``checkpointer ops only, aget_tuple + aput + aput_writes per superstep``

    ===========  ==================  ==================
    concurrency  bridge mean/step    native mean/step
    ===========  ==================  ==================
    1            0.63 ms             1.02 ms
    8            4.60 ms             11.63 ms
    32           16.25 ms            34.20 ms
    64           26.07 ms            61.86 ms
    ===========  ==================  ==================

    ``a six-node graph, 50 ms per node, concurrent runs under astream``
    (ideal floor 0.30 s): at 64 concurrent runs the bridge finished in
    0.357 s and the native saver in 0.439 s. The bridge's own absolute cost
    is **0.24 ms per superstep** — three `to_thread` hops over a 0.349 ms
    synchronous baseline, against a superstep that contains a model call.

    So the native saver is not merely unnecessary here, it is **2.2x–2.4x
    slower under concurrency**, and the two tests below are why rather than a
    footnote: it serialises every operation on one `asyncio.Lock` over one
    aiosqlite connection thread, while the bridge's `check_same_thread=False`
    connection is walked by the whole default thread pool.

    The portability constraint the ticket called the design is confirmed too,
    and it is the second test: `AsyncSqliteSaver.__init__` calls
    `asyncio.get_running_loop()`, so it cannot be *constructed* in a plain
    script — which is exactly the promise `load_workflow` makes.

    Both facts are pinned rather than recorded in prose, because either could
    change in a future release and the decision would then need re-taking. A
    number in a docstring has no way to fail; these two do.
    """

    def test_the_native_saver_serialises_every_operation_on_one_lock(self) -> None:
        """One `asyncio.Lock` per saver, held across each async operation.

        This is the mechanism behind the measurement above. If a release
        removes it, the concurrency arm must be re-run before quoting the
        table.
        """
        import inspect

        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        assert "self.lock" in inspect.getsource(AsyncSqliteSaver.__init__)
        for name in ("aget_tuple", "aput", "aput_writes"):
            source = inspect.getsource(getattr(AsyncSqliteSaver, name))
            assert "self.lock" in source, name

    def test_the_native_saver_cannot_be_built_without_a_running_loop(self) -> None:
        """`__init__` captures the loop, so a plain script cannot construct one.

        Not "answers the sync four badly" — it cannot be *built* at all. That
        is what makes swapping the shared saver a portability break rather
        than a performance trade, and it is why the answer stays the bridge
        even if a future release makes the native saver faster.
        """
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        assert "get_running_loop" in __import__("inspect").getsource(
            AsyncSqliteSaver.__init__
        )

        class _FakeConn:
            pass

        try:
            AsyncSqliteSaver(_FakeConn())  # type: ignore[arg-type]
        except RuntimeError as exc:
            assert "no running event loop" in str(exc)
        else:  # pragma: no cover - the day this stops being true, re-decide
            raise AssertionError(
                "AsyncSqliteSaver constructed with no running loop — the "
                "portability constraint behind async-first/03 has changed"
            )
