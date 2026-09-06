"""The five async-task tools survive being called the way a model calls them.

`async-first/16`. Every earlier proof of these tools reaches the body as
`tool.func(..., runtime=_Runtime(...))` — **handing** the runtime over by name.
That is a fine way to prove what the body does with a state it is given, and it
is exactly the shape that let this ship broken: in a real run nobody hands the
runtime over, it is *injected*, and injection is a seam those tests never cross.

Live, `?w=deepworkers` against `openai/gpt-4.1-mini`, every call died with

    TypeError: start_async_task() missing 1 required positional argument: 'runtime'

The seam is two objects wide. `ToolNode` decides *whether* to inject by reading
the function's signature (`_get_all_injected_args`), and `StructuredTool` then
decides whether to *keep* what was injected — by reading the same signature
again through `inspect.signature`, which under `from __future__ import
annotations` hands back the **string** `"ToolRuntime"` rather than the class.
The first read resolves the string; the second does not. So the runtime was
injected into the call and then dropped on the way to the function.

So this file drives the real `ToolNode`, inside a real graph, from a real
`AIMessage` carrying a tool call with an id. Nothing here may pass `runtime=`.
"""

from __future__ import annotations

import json
import time
from typing import Annotated, Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from openstategraph.abc.async_task_middleware import ASYNC_TASKS_KEY, AsyncTaskMiddleware
from openstategraph.async_tasks import InProcessTaskDesk, TaskStatus
from openstategraph.compile.reducers import Reducer, reducer_for

_WORKERS = [{"name": "researcher", "description": "researches things"}]


class _State(TypedDict, total=False):
    """The agent-loop state the tools read and write, minus the agent loop."""

    messages: Annotated[list[Any], reducer_for(Reducer.ADD_MESSAGES)]
    async_tasks: Annotated[dict[str, Any], reducer_for(Reducer.MERGE)]


def _desk() -> InProcessTaskDesk:
    async def launcher(turns: list[str], identity: dict[str, str]) -> str:
        return "the answer is 41 ports"

    return InProcessTaskDesk({"researcher": launcher})


def _call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _run(middleware: AsyncTaskMiddleware, call: dict[str, Any], state: _State) -> _State:
    """Execute one tool call through `ToolNode`, exactly as the agent loop does.

    A compiled graph rather than a bare `ToolNode.invoke`, because the node
    reads the LangGraph `Runtime` out of the executing context to build the
    `ToolRuntime` it injects — which is the whole subject of this file.
    """
    graph = StateGraph(_State)
    graph.add_node("tools", ToolNode(middleware.tools))
    graph.set_entry_point("tools")
    graph.add_edge("tools", END)
    seeded: _State = {
        "messages": [*state.get("messages", []), AIMessage(content="", tool_calls=[call])],
        "async_tasks": dict(state.get("async_tasks") or {}),
    }
    return graph.compile().invoke(seeded)


def _last_tool_message(result: _State) -> ToolMessage:
    return [m for m in result["messages"] if isinstance(m, ToolMessage)][-1]


def _settle(desk: InProcessTaskDesk, task_id: str) -> None:
    deadline = time.time() + 5.0
    while time.time() < deadline and desk.status(task_id) == TaskStatus.RUNNING:
        time.sleep(0.02)


def test_a_model_calling_start_async_task_actually_starts_one() -> None:
    """The ticket's own *done when*, and the regression that names the bug."""
    desk = _desk()
    try:
        middleware = AsyncTaskMiddleware(desk=desk, subagents=_WORKERS)
        result = _run(
            middleware,
            _call(
                "start_async_task",
                {"description": "count the ports", "subagent_type": "researcher"},
                "call_start_1",
            ),
            {},
        )

        assert "Started `researcher`" in str(_last_tool_message(result).content)
        # The task id is the tool call id, and it reached the channel — which is
        # what a later turn polls with.
        assert "call_start_1" in result["async_tasks"]
        assert desk.status("call_start_1") in {TaskStatus.RUNNING, TaskStatus.SUCCESS}
    finally:
        desk.shutdown()


@pytest.mark.parametrize(
    ("tool_name", "args", "expected"),
    [
        ("check_async_task", {"task_id": "call_start_1"}, "call_start_1"),
        (
            "update_async_task",
            {"task_id": "call_start_1", "message": "also count the docks"},
            "Queued for `researcher`",
        ),
        ("cancel_async_task", {"task_id": "call_start_1"}, "call_start_1"),
        ("list_async_tasks", {}, "call_start_1"),
    ],
)
def test_every_other_async_tool_survives_the_same_call(
    tool_name: str, args: dict[str, Any], expected: str
) -> None:
    """Four of the five take the runtime, so four of the five had the defect.

    Each is asserted only to have *run* — no `TypeError`, and an answer that is
    about the task rather than about a missing argument. What each one decides
    is proven elsewhere; this file is about the seam.
    """
    desk = _desk()
    try:
        middleware = AsyncTaskMiddleware(desk=desk, subagents=_WORKERS)
        started = _run(
            middleware,
            _call(
                "start_async_task",
                {"description": "count the ports", "subagent_type": "researcher"},
                "call_start_1",
            ),
            {},
        )
        result = _run(
            middleware,
            _call(tool_name, args, "call_second_1"),
            {"async_tasks": started["async_tasks"]},
        )

        content = str(_last_tool_message(result).content)
        assert "runtime" not in content
        assert expected in content
    finally:
        desk.shutdown()


def test_the_answer_comes_back_through_check_when_the_worker_has_finished() -> None:
    """End to end on the real seam: launch, wait, collect."""
    desk = _desk()
    try:
        middleware = AsyncTaskMiddleware(desk=desk, subagents=_WORKERS)
        started = _run(
            middleware,
            _call(
                "start_async_task",
                {"description": "count the ports", "subagent_type": "researcher"},
                "call_start_1",
            ),
            {},
        )
        _settle(desk, "call_start_1")
        checked = _run(
            middleware,
            _call("check_async_task", {"task_id": "call_start_1"}, "call_check_1"),
            {"async_tasks": started["async_tasks"]},
        )

        payload = json.loads(str(_last_tool_message(checked).content))
        assert payload["status"] == TaskStatus.SUCCESS
        assert payload["result"] == "the answer is 41 ports"
        assert checked["async_tasks"]["call_start_1"]["status"] == TaskStatus.SUCCESS
    finally:
        desk.shutdown()


def test_the_model_facing_schema_still_hides_the_runtime() -> None:
    """The injected argument must never appear in what the model is shown.

    The fix is on the *call* seam, so the fix that would break this is the
    tempting one: give the runtime a field in `args_schema` and let a model try
    to fill it in.
    """
    desk = _desk()
    try:
        middleware = AsyncTaskMiddleware(desk=desk, subagents=_WORKERS)
        for tool in middleware.tools:
            properties = tool.tool_call_schema.model_json_schema().get("properties", {})
            assert "runtime" not in properties, tool.name
        assert ASYNC_TASKS_KEY == "async_tasks"
    finally:
        desk.shutdown()
