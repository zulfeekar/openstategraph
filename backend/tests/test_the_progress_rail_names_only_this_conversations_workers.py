"""The roster line names this conversation's workers and no one else's.

`the-boundary-nobody-checked/04`. Two docstrings justified the desk key with a
property the key does not have — *"one agent can never read another's tasks"* —
and the key is `<workflow slug>:<node id>`, which holds no thread. So the desk
separates one **node** from another and never separated one **conversation**
from another: two callers asking the same workflow at the same node share one
desk and one task table.

Four of the five tools were never affected, because they resolve through
`runtime.state[ASYNC_TASKS_KEY]` rather than through the desk. The fifth path
did not: `_announce` rendered `desk.tasks()` — *every record this desk holds* —
onto the `progress` rail before every model call, and a `progress` line reaches
**both** audiences (only `progress.detail` is dropped for a customer). So a
customer was told the archetype and status of every background worker every
other customer had running at that node: an existence-and-activity side channel,
live enough to watch a stranger's fan-out start and finish.

**The fix is the read, not the key**, and the reason is written at the key
itself: a desk narrower than the process *"dies with the turn, which is the
thing being fixed"*, and a follow-up turn on the same thread has to find the
desk that already holds the running child. Adding a thread to the key would
orphan the children the desk exists to keep. So `_announce` now reads the same
per-thread state the other four tools read — `ModelRequest.state`, which is the
agent loop's own state and therefore this conversation's — and asks the desk
only for the *status* of a task this conversation already tracks.

**And it says nothing at all about the rest.** Not a count, not "3 others
running". A count is the leak in miniature — existence and activity are exactly
what leaked — and nothing is being silently omitted from this conversation's
point of view: every task this conversation started is on the line, and the
others were never its business.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

import openstategraph.abc.async_task_middleware as middleware_module
from openstategraph.abc.async_task_middleware import AsyncTaskMiddleware
from openstategraph.async_tasks import (
    ASYNC_TASKS_KEY,
    InProcessTaskDesk,
    TaskStatus,
    reset_desks,
    set_desk_for,
)


class _Request:
    """The `ModelRequest` shape `wrap_model_call` is handed: it carries `state`.

    The same attribute `ToolRuntime` carries, which is why one reader
    (`_all_tracked`) serves both callers rather than two spellings of one fact.
    """

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state = state or {}


@pytest.fixture()
def announced(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every line the middleware publishes on the `progress` rail."""
    lines: list[str] = []

    def record(message: str, **_: Any) -> bool:
        lines.append(message)
        return True

    monkeypatch.setattr(middleware_module, "report_progress", record)
    return lines


class TestAConversationHearsOnlyItsOwnWorkers:
    def test_a_conversation_that_started_nothing_is_told_nothing(
        self, announced: list[str]
    ) -> None:
        """The reproduction, at the layer the defect lives.

        The desk holds a worker; this conversation's state tracks none. Before
        the fix the rail said `Background workers: researcher running`.
        """
        released = threading.Event()
        desk = InProcessTaskDesk({"researcher": _gated(released)})
        try:
            desk.start("researcher", "somebody else's task")
            middleware = _middleware(desk)

            middleware.wrap_model_call(_Request(), lambda request: "answered")

            assert announced == []
        finally:
            released.set()
            desk.shutdown()

    def test_the_line_names_this_conversations_task_and_not_the_other(
        self, announced: list[str]
    ) -> None:
        released = threading.Event()
        desk = InProcessTaskDesk(
            {"mine": _gated(released), "theirs": _gated(released)}
        )
        try:
            mine = desk.start("mine", "count the ports")
            desk.start("theirs", "another conversation's work")
            middleware = _middleware(desk, workers=("mine", "theirs"))

            middleware.wrap_model_call(_tracking(mine), lambda request: "answered")

            assert announced == ["Background workers: mine running"]
            assert not any("theirs" in line for line in announced)
        finally:
            released.set()
            desk.shutdown()

    def test_the_status_is_the_desks_live_one_rather_than_the_stored_snapshot(
        self, announced: list[str]
    ) -> None:
        """State says where a task stood; the desk says where it stands.

        The row in state was written when the task was started, so reading the
        status out of it would report `running` forever. The filter is on the
        *id*; the status still comes from the desk.
        """
        released = threading.Event()
        desk = InProcessTaskDesk({"mine": _gated(released)})
        try:
            mine = desk.start("mine", "count the ports")
            request = _tracking(mine)
            released.set()
            _wait(desk, mine.task_id, TaskStatus.SUCCESS)

            _middleware(desk, workers=("mine",)).wrap_model_call(
                request, lambda _: "answered"
            )

            assert announced == ["Background workers: mine success"]
        finally:
            released.set()
            desk.shutdown()

    @pytest.mark.asyncio()
    async def test_the_async_half_reads_the_same_state(
        self, announced: list[str]
    ) -> None:
        """`awrap_model_call` is the path a real run takes — `_agent` awaits
        `ainvoke` — so a filter on the sync half only would fix nothing."""
        released = threading.Event()
        desk = InProcessTaskDesk({"researcher": _gated(released)})
        try:
            desk.start("researcher", "somebody else's task")
            middleware = _middleware(desk)

            async def handler(request: Any) -> str:
                return "answered"

            await middleware.awrap_model_call(_Request(), handler)

            assert announced == []
        finally:
            released.set()
            desk.shutdown()


class TestTwoConversationsThroughOneCompiledNode:
    """The ticket's own Done-when: a real compiled agent node, driven twice.

    Two drives of one node id with two independent states is what two callers
    on one thread-less desk actually are here — `run_identity()` is `{}` off a
    run, so both resolve the same `":a1"` desk, which is precisely the sharing
    the finding is about.
    """

    def test_the_second_conversation_is_not_told_about_the_firsts_worker(
        self, announced: list[str]
    ) -> None:
        pytest.importorskip("deepagents")

        released = threading.Event()
        desk = InProcessTaskDesk({"researcher": _gated(released)})
        set_desk_for(":a1", desk)
        try:
            _drive_agent(starts_a_task=True)
            assert any("researcher" in line for line in announced), (
                "the conversation that started the worker should hear about it"
            )

            announced.clear()
            _drive_agent(starts_a_task=False)

            assert announced == []
        finally:
            released.set()
            reset_desks()


# -- helpers ---------------------------------------------------------------- #


def _gated(released: threading.Event) -> Any:
    async def worker(turns: list[str], identity: dict[str, str]) -> str:
        import asyncio

        while not released.is_set():
            await asyncio.sleep(0.005)
        return "counted"

    return worker


def _middleware(
    desk: InProcessTaskDesk, workers: tuple[str, ...] = ("researcher",)
) -> AsyncTaskMiddleware:
    return AsyncTaskMiddleware(
        desk=desk,
        subagents=[{"name": name, "description": f"what {name} does"} for name in workers],
    )


def _tracking(*records: Any) -> _Request:
    return _Request({ASYNC_TASKS_KEY: {r.task_id: r.as_dict() for r in records}})


def _wait(desk: InProcessTaskDesk, task_id: str, status: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if desk.status(task_id) == status:
            return
        time.sleep(0.01)


def _drive_agent(*, starts_a_task: bool) -> None:
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from conftest import drive_node
    from openstategraph.compile.node_runtime import NodeRuntime, RunState
    from openstategraph.compile.workflow_compiler import CompiledPlan

    class Scripted(GenericFakeChatModel):
        def __init__(self) -> None:
            super().__init__(messages=iter([]))
            object.__setattr__(self, "calls", 0)

        def bind_tools(self, tools: Any, **kwargs: Any) -> "Scripted":
            return self

        def _generate(self, messages: Any, *args: Any, **kwargs: Any) -> ChatResult:
            object.__setattr__(self, "calls", self.calls + 1)  # type: ignore[attr-defined]
            if starts_a_task and self.calls == 1:  # type: ignore[attr-defined]
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "start_async_task",
                            "args": {
                                "description": "count the ports",
                                "subagent_type": "researcher",
                            },
                            "id": "call-A1",
                        }
                    ],
                )
            else:
                message = AIMessage(content="done")
            return ChatResult(generations=[ChatGeneration(message=message)])

    data = {
        "tier": "deep",
        "systemPrompt": "You are the parent.",
        "summarize": False,
        "subagents": [
            {
                "id": "sa1",
                "name": "researcher",
                "mode": "async",
                "description": "counts things",
                "systemPrompt": "You research.",
            }
        ],
    }
    runtime = NodeRuntime(model=Scripted())
    node = {"id": "a1", "type": "agent.llm", "data": data}
    drive_node(runtime._agent("a1", node, CompiledPlan()), RunState(question="hello"))  # type: ignore[typeddict-item]
