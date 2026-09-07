"""An async subagent never sees the parent's state or message history.

`async-first/08`. CLAUDE.md's isolation rule is the hard constraint the whole
design was built around, and the ticket says any design implying otherwise is
wrong before it is discussed — so it is proven **directly** here rather than
inferred from the fact that a task description is a string.

The proof shape: put a marker in the parent's message history *and* in its graph
state, launch a child, and read what the child's launcher was actually handed.
A launcher receives the whole conversation it is to run and nothing else, so if
the marker is not in there it cannot reach the child by any route this code
controls.

The second test is the one that would catch a regression nobody meant to write:
a *second* task launched by the same agent must not see the first task's turns
either. Isolation is between siblings as well as from the parent.
"""

from __future__ import annotations

from typing import Any

from openstategraph.abc.async_task_middleware import AsyncTaskMiddleware
from openstategraph.async_tasks import InProcessTaskDesk, TaskStatus

MARKER = "THE-PARENT-ONLY-SECRET"


class _Runtime:
    """The `ToolRuntime` shape the five tools read: state and a tool-call id."""

    def __init__(self, state: dict[str, Any], tool_call_id: str = "call-1") -> None:
        self.state = state
        self.tool_call_id = tool_call_id


def _seen() -> tuple[list[list[str]], InProcessTaskDesk]:
    seen: list[list[str]] = []

    async def launcher(turns: list[str], identity: dict[str, str]) -> str:
        seen.append(list(turns))
        return "done"

    return seen, InProcessTaskDesk({"researcher": launcher})


def _middleware(desk: InProcessTaskDesk) -> AsyncTaskMiddleware:
    return AsyncTaskMiddleware(
        desk=desk,
        subagents=[{"name": "researcher", "description": "researches things"}],
    )


def _tool(middleware: AsyncTaskMiddleware, name: str) -> Any:
    return next(tool for tool in middleware.tools if tool.name == name)


def test_the_child_receives_its_task_and_nothing_of_the_parent() -> None:
    seen, desk = _seen()
    try:
        middleware = _middleware(desk)
        parent_state = {
            "messages": [{"role": "user", "content": MARKER}],
            "answer": MARKER,
            "decisions": {"router_1": MARKER},
        }
        start = _tool(middleware, "start_async_task")
        # `.func`, not `.invoke`: `runtime` is injected by the agent loop, and
        # the point of this test is what the *body* is handed, with no loop and
        # no model anywhere near it.
        start.func(
            description="count the ports",
            subagent_type="researcher",
            runtime=_Runtime(parent_state),
        )
        _drain(desk)
        assert seen == [["count the ports"]]
        assert MARKER not in "".join(turn for turns in seen for turn in turns)
    finally:
        desk.shutdown()


def test_two_tasks_from_one_agent_do_not_see_each_other() -> None:
    seen, desk = _seen()
    try:
        middleware = _middleware(desk)
        start = _tool(middleware, "start_async_task")
        state: dict[str, Any] = {"messages": []}
        for index, description in enumerate(("first task", "second task")):
            start.func(
                description=description,
                subagent_type="researcher",
                runtime=_Runtime(state, tool_call_id=f"call-{index}"),
            )
        _drain(desk)
        assert sorted(seen) == [["first task"], ["second task"]]
    finally:
        desk.shutdown()


def test_the_run_identity_does_cross_and_that_is_not_a_contradiction() -> None:
    """The second sentence, asserted beside the first because apart they read as
    a contradiction.

    `compile/subagents.py` already records the pair for the blocking subagent:
    *a subagent never sees the parent's message history or graph state*, **and**
    *the run's context crosses into a subagent's tools unchanged*. Isolation is
    about messages and state; identity is a third channel.

    It is load-bearing here rather than merely consistent. The desk's loop is
    outside every run context, so `run_identity()` inside a child answers `{}` —
    and `memory.workflow_scope_slug` says in as many words that a nameless run
    **shares a key**. Two conversations' children writing one memory namespace
    would be the opposite of isolation, arrived at by leaving something out.
    """
    seen: list[dict[str, str]] = []

    async def launcher(turns: list[str], identity: dict[str, str]) -> str:
        seen.append(dict(identity))
        return "done"

    desk = InProcessTaskDesk({"researcher": launcher})
    try:
        middleware = _middleware(desk)
        _tool(middleware, "start_async_task").func(
            description="count the ports",
            subagent_type="researcher",
            runtime=_Runtime({}),
        )
        _drain(desk)
        # Outside a run there is no identity to carry, and `{}` is the honest
        # answer — the same one `run_identity` gives every other reader.
        assert seen == [{}]

        seen.clear()
        desk.start("researcher", "count again", identity={"thread_id": "t-1"})
        _drain(desk)
        assert seen == [{"thread_id": "t-1"}]
    finally:
        desk.shutdown()


def _drain(desk: InProcessTaskDesk, timeout: float = 5.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        statuses = {record.status for record in desk.tasks()}
        if statuses and statuses <= TaskStatus.TERMINAL:
            return
        time.sleep(0.01)
