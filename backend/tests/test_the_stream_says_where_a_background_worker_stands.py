"""A reader sees a background worker start, watch it, and see it finish.

`async-first/08`, and it is the owner's explicit requirement: *the stream must
say what is happening and the current status of each async subagent* — on the
rails that already exist, never a new channel.

Two rails, answering two different questions:

- **`spawn`** answers *a task began*. `SpawnWatcher` reads the
  `start_async_task` call off the agent's own model frame, exactly as it already
  reads `task`, and emits `kind: "async"`.
- **`progress`** answers *and here is where each one stands now*.
  `AsyncTaskMiddleware` reports the roster before every model call —
  deterministically, out of the desk, with no model in the loop.

**How a non-node task is attributed.** `140`'s `ThinkingStack` renders by
`activeNode` / `frameTarget`, never `event.node`, and a background worker is not
a canvas node — it has no id to be. So both frames are attributed to the **agent
node that launched the task**: `spawn.parent`, and, for the progress line, the
`activeNode` the stream resolves from the namespace the tool ran in. The task's
own identity travels as `taskId`, which is the string `canvas-feels-right/07`
will draw with — and it is the same string the model polls with, because the
task is named after the tool call that started it.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from openstategraph.abc.async_task_middleware import AsyncTaskMiddleware, async_task_status_line
from openstategraph.api.streaming import SpawnWatcher
from openstategraph.async_tasks import InProcessTaskDesk, TaskStatus
from openstategraph.progress import PROGRESS_KEY, progress_report


class _Runtime:
    def __init__(self, state: dict[str, Any], tool_call_id: str = "call_async_1") -> None:
        self.state = state
        self.tool_call_id = tool_call_id


def test_the_launch_is_a_spawn_frame_of_its_own_kind() -> None:
    """`subagent` and `async` must not render identically: one ends with this
    run and the other does not."""
    message = SimpleNamespace(
        tool_calls=[
            {
                "name": "start_async_task",
                "id": "call_async_1",
                "args": {"subagent_type": "researcher", "description": "Count the ports"},
            }
        ]
    )
    spawns = SpawnWatcher().inspect("agent_deep", (), {"messages": [message]}, internal=True)

    assert len(spawns) == 1
    assert spawns[0]["kind"] == "async"
    # Attribution: the agent node that launched it. A task is not a canvas node.
    assert spawns[0]["parent"] == "agent_deep"
    assert spawns[0]["label"] == "researcher"
    assert spawns[0]["instruction"] == "Count the ports"
    assert spawns[0]["taskId"] == "call_async_1"


def test_the_spawn_frames_task_id_is_the_one_the_model_will_poll_with() -> None:
    """The stream and the state agree by construction, not by correlation."""
    desk = InProcessTaskDesk({"researcher": _slow})
    try:
        middleware = _middleware(desk)
        state: dict[str, Any] = {}
        start = _tool(middleware, "start_async_task")
        result = start.func(
            description="Count the ports",
            subagent_type="researcher",
            runtime=_Runtime(state, tool_call_id="call_async_1"),
        )
        rows = result.update["async_tasks"]
        assert list(rows) == ["call_async_1"]

        message = SimpleNamespace(
            tool_calls=[
                {
                    "name": "start_async_task",
                    "id": "call_async_1",
                    "args": {"subagent_type": "researcher", "description": "Count the ports"},
                }
            ]
        )
        spawn = SpawnWatcher().inspect("agent_deep", (), {"messages": [message]}, True)[0]
        assert spawn["taskId"] in rows
    finally:
        desk.shutdown()


def test_a_reader_sees_running_become_finished_without_the_model_being_asked() -> None:
    released: list[bool] = []
    desk = InProcessTaskDesk({"researcher": lambda turns, identity: _gated(turns, released)})
    try:
        middleware = _middleware(desk)
        start = _tool(middleware, "start_async_task")
        start.func(
            description="Count the ports",
            subagent_type="researcher",
            runtime=_Runtime({}),
        )

        # The roster line is what rides the `progress` rail, and it is assembled
        # from the desk's own records — never from a model asked to narrate
        # itself, which `launch-readiness/143` settled for the same reason.
        assert async_task_status_line(desk.tasks()) == "Background workers: researcher running"
        released.append(True)
        _wait(desk, TaskStatus.SUCCESS)
        assert async_task_status_line(desk.tasks()) == "Background workers: researcher success"
    finally:
        desk.shutdown()


def test_the_roster_reaches_the_progress_rail_in_our_envelope() -> None:
    """Anything on `custom` without our envelope is ignored, deliberately — so
    the roster has to be inside one to render at all."""
    payload = {
        PROGRESS_KEY: {
            "message": "Background workers: researcher running",
            "current": None,
            "total": None,
            "node": "agent_deep",
        }
    }
    report = progress_report(payload)
    assert report is not None
    assert report.message == "Background workers: researcher running"
    # Attribution again: the frame names the agent node, and `api/streaming.py`
    # maps that graph-step name to a canvas id exactly as it does for a token.
    assert report.node == "agent_deep"


def test_an_agent_with_no_background_worker_says_nothing_at_all() -> None:
    desk = InProcessTaskDesk({"researcher": _slow})
    try:
        assert async_task_status_line(desk.tasks()) == ""
    finally:
        desk.shutdown()


# -- helpers ---------------------------------------------------------------- #


async def _slow(turns: list[str], identity: dict[str, str]) -> str:
    import asyncio

    await asyncio.sleep(60)
    return "never"


async def _gated(turns: list[str], released: list[bool]) -> str:
    import asyncio

    while not released:
        await asyncio.sleep(0.005)
    return "counted"


def _middleware(desk: InProcessTaskDesk) -> AsyncTaskMiddleware:
    return AsyncTaskMiddleware(
        desk=desk,
        subagents=[{"name": "researcher", "description": "counts things"}],
    )


def _tool(middleware: AsyncTaskMiddleware, name: str) -> Any:
    return next(tool for tool in middleware.tools if tool.name == name)


def _wait(desk: InProcessTaskDesk, status: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(record.status == status for record in desk.tasks()):
            return
        time.sleep(0.01)
