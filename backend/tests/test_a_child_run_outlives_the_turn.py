"""The task desk: a child that outlives the turn, and who owns it.

`async-first/08`. The question the ticket demanded be answered before any code
was written — *what owns a child that outlives the parent's turn?* — is answered
by `openstategraph/async_tasks.py`, and this file is the answer executed rather
than described.

The three properties that make the answer true, and nothing else here:

1. **The desk outlives the door.** A task started from inside one `asyncio.run`
   is still running, and still collectable, after that loop has closed. That is
   the whole difference from `run_doors.py`'s run-scoped loop.
2. **A follow-up is queued, not injected.** The in-process desk does not claim
   mid-flight steering; it says so, and this proves the semantics it does claim.
3. **A task the desk has never heard of is named as unknown**, never given an
   invented status — the honest shape of "the process that started it has since
   restarted".
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from openstategraph.async_tasks import InProcessTaskDesk, TaskStatus


def _wait_for(desk: InProcessTaskDesk, task_id: str, status: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = desk.status(task_id)
        if current == status:
            return current
        time.sleep(0.01)
    return desk.status(task_id)


def test_a_task_started_inside_one_loop_survives_that_loop_closing() -> None:
    """The property the whole ticket turns on."""
    released = threading.Event()
    desk = InProcessTaskDesk(
        {"researcher": lambda turns, identity: _slow_worker(turns, released)},
    )
    try:

        async def one_turn() -> str:
            # A run's door owns this loop, exactly as `run_doors.invoke_run` does.
            return desk.start("researcher", "count the ports").task_id

        task_id = asyncio.run(one_turn())
        # The door's loop is now closed. The child is not.
        assert desk.status(task_id) == TaskStatus.RUNNING

        released.set()
        assert _wait_for(desk, task_id, TaskStatus.SUCCESS) == TaskStatus.SUCCESS
        assert desk.result(task_id) == "counted: count the ports"
    finally:
        desk.shutdown()


async def _slow_worker(turns: list[str], released: threading.Event) -> str:
    # Polled rather than an `asyncio.Event`, because the desk's loop belongs to
    # the desk: a primitive built on the test's loop cannot be awaited on it.
    # That constraint *is* the property under test — the child is not on any
    # loop a turn owns.
    while not released.is_set():
        await asyncio.sleep(0.005)
    return f"counted: {turns[-1]}"


def test_a_follow_up_is_a_second_turn_and_not_an_interruption() -> None:
    seen: list[list[str]] = []

    async def worker(turns: list[str], identity: dict[str, str]) -> str:
        seen.append(list(turns))
        await asyncio.sleep(0)
        return f"turn {len(turns)}"

    desk = InProcessTaskDesk({"w": worker})
    try:
        record = desk.start("w", "first")
        assert _wait_for(desk, record.task_id, TaskStatus.SUCCESS) == TaskStatus.SUCCESS
        assert desk.follow_up(record.task_id, "second") is True
        assert _wait_for(desk, record.task_id, TaskStatus.SUCCESS) == TaskStatus.SUCCESS
        assert desk.result(record.task_id) == "turn 2"
        assert seen == [["first"], ["first", "second"]]
    finally:
        desk.shutdown()


def test_an_unknown_task_is_unknown_rather_than_given_a_status() -> None:
    desk = InProcessTaskDesk({"w": lambda turns, identity: _immediate("x")})
    try:
        assert desk.status("no-such-task") == TaskStatus.UNKNOWN
        assert desk.result("no-such-task") is None
        assert desk.follow_up("no-such-task", "hi") is False
        assert desk.cancel("no-such-task") is False
    finally:
        desk.shutdown()


async def _immediate(answer: str) -> str:
    return answer


def test_a_failing_child_is_an_error_status_carrying_its_message() -> None:
    async def worker(turns: list[str], identity: dict[str, str]) -> str:
        raise RuntimeError("the provider said no")

    desk = InProcessTaskDesk({"w": worker})
    try:
        record = desk.start("w", "go")
        assert _wait_for(desk, record.task_id, TaskStatus.ERROR) == TaskStatus.ERROR
        assert "the provider said no" in (desk.error(record.task_id) or "")
        assert desk.result(record.task_id) is None
    finally:
        desk.shutdown()


def test_cancelling_a_running_child_stops_it() -> None:
    async def worker(turns: list[str], identity: dict[str, str]) -> str:
        await asyncio.sleep(60)
        return "never"

    desk = InProcessTaskDesk({"w": worker})
    try:
        record = desk.start("w", "go")
        assert desk.cancel(record.task_id) is True
        assert _wait_for(desk, record.task_id, TaskStatus.CANCELLED) == TaskStatus.CANCELLED
    finally:
        desk.shutdown()


def test_starting_an_undeclared_agent_is_refused_rather_than_silently_dropped() -> None:
    desk = InProcessTaskDesk({"w": lambda turns, identity: _immediate("x")})
    try:
        with pytest.raises(KeyError):
            desk.start("nobody", "go")
    finally:
        desk.shutdown()


def test_the_desk_reports_every_task_it_holds() -> None:
    desk = InProcessTaskDesk({"w": lambda turns, identity: _immediate("done")})
    try:
        first = desk.start("w", "a")
        second = desk.start("w", "b")
        _wait_for(desk, second.task_id, TaskStatus.SUCCESS)
        held = {record.task_id for record in desk.tasks()}
        assert held == {first.task_id, second.task_id}
    finally:
        desk.shutdown()
