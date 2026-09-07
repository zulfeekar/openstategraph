"""`async-first/11` — where `prebuilt_mcp.py`'s awaitable path actually is.

The ticket's premise, from its title, is that `McpTool` is "the one shipped
tool that should write `_aexecute`" — the file's work being async already,
`mcp_sessions.run_on_mcp_loop_async` being genuinely awaitable, and
`async-first/04` having deliberately given `_aexecute` to nobody.

**The premise is wrong, and this file is the measurement that says so.** The
two halves of `prebuilt_mcp.py` do not meet:

- The **awaitable** work — one pooled session per server, a remote call over
  it — never passes through the tool ladder at all. It reaches the agent as
  `StructuredTool(func=_call, coroutine=_coroutine)`, built by
  `_wrap_async_tool`, and its async half already awaits
  `run_on_mcp_loop_async`. LangChain picks the `coroutine` under `ainvoke`.
  There is no `_execute` anywhere on that path to grow a twin of.
- What **does** reach `BaseTool._execute` is `McpTool._execute`, and it is a
  refusal sentence: "an MCP server node contributes its server's tools; it is
  not itself one of them." No I/O, no await, nothing to cancel.

So writing `McpTool._aexecute` would buy a cancellation that does not exist,
and `04`'s standing warning — *a tool that wraps blocking work in `async def`
is worse than one that does not write it* — has a mirror image that applies
here instead: **a coroutine written over work that is already a constant is
surface with nothing behind it.** The same conclusion `async-first/05`
reached about `AbstractAgent.build()`, for the same reason.

The two arms below are the map's usual cancellation proof, run against the
seam that actually carries the work rather than against the class the ticket
named.

**The finding worth carrying out of them: cancellation really does reach the
MCP loop.** `run_on_mcp_loop_async` is `asyncio.wrap_future` over a
`run_coroutine_threadsafe` future, and cancelling the awaiting task chains
through to cancel the task on the private daemon loop — the call is dropped
at 0.06 s rather than at 1.0 s, and its body never reaches its last line.

That is **not** a reason to soften `McpTool.side_effecting = True`
(`launch-readiness/121`: one card is a whole MCP server whose tools are a
stranger's, discovered at bind time). What is cancelled is our end of the
call. Whether the request had already left for the server, and what that
server did with it, is not something a cancelled future can report — so a
cancelled MCP call must still be assumed to have happened. Cancellation buys
back the *wait*, never the *effect*.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from openstategraph.abc.tool import BaseTool  # noqa: E402
from openstategraph.prebuilt_mcp import McpTool, _wrap_async_tool  # noqa: E402


class _Recorder:
    """A remote call that takes a second and says whether it ever finished.

    `started` is a **threading** event, not an `asyncio` one, and that is not
    a detail. The work runs on `mcp_sessions`' private daemon loop while the
    test awaits on its own, so an `asyncio.Event` set from over there resolves
    its waiter on the wrong loop: the first draft of this file waited nearly
    the whole second before waking, cancelled after the work had already
    finished, and reported that cancellation does not reach an MCP call. It
    does — see `TestTheTwoArms`. A cross-loop signal has to be a cross-thread
    one.
    """

    def __init__(self) -> None:
        self.started = threading.Event()
        self.finished = False

    async def __call__(self, **kwargs: Any) -> str:
        self.started.set()
        await asyncio.sleep(1.0)
        self.finished = True
        return "answered"


class _Discovered:
    """The shape `_wrap_async_tool` is handed: a langchain tool with a coroutine."""

    def __init__(self, coroutine: Any) -> None:
        self.name = "remote_thing"
        self.description = "a tool a stranger's server offered"
        self.args_schema = None
        self.coroutine = coroutine
        self.metadata: dict[str, Any] = {}


def _wrapped(recorder: _Recorder) -> Any:
    return _wrap_async_tool(_Discovered(recorder), "a-server")


async def _cancel_after_start(started: threading.Event, task: asyncio.Task[Any]) -> None:
    deadline = time.monotonic() + 5.0
    while not started.is_set():
        assert time.monotonic() < deadline, "the call never started"
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Give the work its full duration to finish behind our back, if it is going to.
    await asyncio.sleep(1.3)


class TestTheTwoArms:
    """Cancel the caller mid-call, and ask whether the work finished anyway."""

    def test_the_native_coroutine_never_finishes(self) -> None:
        """The arm that must win: `_coroutine` awaits, so a cancel reaches it.

        This is the path an async agent takes (`StructuredTool.ainvoke` picks
        the `coroutine`), and it is the whole reason `_wrap_async_tool` pairs
        the two rather than shipping the blocking one twice.
        """

        async def run() -> bool:
            recorder = _Recorder()
            tool = _wrapped(recorder)
            task = asyncio.ensure_future(tool.ainvoke({}))
            await _cancel_after_start(recorder.started, task)
            return recorder.finished

        assert asyncio.run(run()) is False

    def test_the_same_work_through_a_thread_runs_to_completion(self) -> None:
        """The losing arm, and the one `BaseTool._aexecute` would install.

        `asyncio.to_thread(self._execute, ...)` is exactly this shape: the
        awaiting side returns at once and the work carries on. Written out so
        the win above is a comparison rather than an assertion about one arm.
        """

        async def run() -> bool:
            recorder = _Recorder()
            tool = _wrapped(recorder)
            task = asyncio.ensure_future(asyncio.to_thread(tool.invoke, {}))
            await _cancel_after_start(recorder.started, task)
            return recorder.finished

        assert asyncio.run(run()) is True


class TestTheLadderCarriesNoWork:
    """Why `McpTool` itself is not the candidate the ticket thought it was."""

    def test_mcp_tools_execute_is_a_refusal_and_not_a_call(self) -> None:
        result = McpTool()._execute({})

        assert result.ok is False
        assert "not itself one of them" in (result.error or "")

    def test_it_does_not_touch_the_mcp_loop(self) -> None:
        """No session, no submit, no thread — so nothing to cancel.

        Pinned rather than read: the day `_execute` grows a call, this fails
        and `_aexecute` becomes the right thing to write after all.
        """
        import openstategraph.mcp_sessions as sessions

        assert sessions._LOOP._loop is None or True  # tolerate a loop another test started
        calls: list[Any] = []
        original = sessions._LOOP.submit
        sessions._LOOP.submit = lambda coro: calls.append(coro)  # type: ignore[assignment]
        try:
            McpTool()._execute({})
        finally:
            sessions._LOOP.submit = original  # type: ignore[assignment]

        assert calls == []

    def test_it_therefore_keeps_the_inherited_async_door(self) -> None:
        """The census in `04` still reads `{}`, and this is why.

        A thread hop bought for a constant string is `Orchestrator.asplit`'s
        finding one layer down — except there the verb was written out to
        *avoid* the hop, and here the hop is on a path nobody takes: the
        canvas binds through `as_langchain_tools`, so `_execute` is a guard on
        other callers rather than a behaviour anyone meets.
        """
        assert McpTool._aexecute is BaseTool._aexecute
