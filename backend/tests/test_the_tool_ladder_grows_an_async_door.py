"""`BaseTool` gains an async door, and not one adopter is asked to open it.

`async-first/04` — phase C of `docs/decisions/async-seam.md`, the phase the
charter names "the one most likely to be under-estimated". The reason it is
not a refactor is written into the stability contract: `BaseTool` is **Tier 1,
semver-public** (`docs/stability.md`, "Tier 1, exactly"), pinned by
`tests/public_api.txt`, and `openstategraph.abc`'s own docstring calls the tool
ladder "the *most* public thing the framework ships". There are 26 `def
_execute` implementations in this tree and one in every adopter's
`tools/*.py`. So `_execute` **cannot** become `async def`; the move is an
**added** `_aexecute` whose default runs `_execute` in a thread.

**LangChain's own `BaseTool` is the shape, and it was read rather than
remembered** — from the installed `langchain-core`, not from a docs page:

    async def _arun(self, *args, **kwargs):
        ...
        return await run_in_executor(None, self._run, *args, **kwargs)

`_run` is the abstract one; `_arun` is concrete and defaults to a thread. And
`StructuredTool._arun` says in its own comment that with no `coroutine` set,
"this will delegate to the default implementation which is expected to delegate
to _run on a separate thread". `_execute`/`_aexecute` is that pairing one rung
down, with `run`/`arun` as the caller's verbs the way `invoke`/`ainvoke` are
LangChain's.

**Three substitutability statements, asserted directly rather than implied**,
because CLAUDE.md's L is the risk here and "an override that throws or no-ops"
is the failure it names:

1. a subclass that defines only `_execute` works on the **async** path;
2. a subclass that defines only `_aexecute` works on the **sync** path;
3. a subclass that overrides neither still works, on both.

Statement 2 is the one that costs something, and it is answered rather than
waived — see `TestOnlyAexecute`. `_execute` stays `@abstractmethod`, because
every diagnosis in `abc/tool.py` (`__init_subclass__`'s RC-04 refusal,
`_abstract_tool_diagnosis`, `_is_deliberate_base`, discovery skipping abstract
classes) is built on its abstractness; the bridge is installed *per subclass*
at class-definition time instead, which is the same "one body, two doors" move
`compile/node_doors.py` made for node bodies on `async-first/06`.

**No async pytest plugin**, deliberately, for the reason `conftest.py`'s
`drive_fold` already gives: the assertions here are about tool results and
about which thread ran the work, not about a loop, and a three-line driver is
cheaper than a plugin the whole suite would then depend on.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any, Awaitable, Callable, TypeVar

import pytest

from openstategraph.abc.tool import BaseTool, ITool, NoArgs, ToolResult

T = TypeVar("T")


def drive(work: Callable[[], Awaitable[T]]) -> T:
    """One `asyncio.run` per test, so no loop leaks between them."""
    return asyncio.run(work())


class Echo(BaseTool):
    """The ordinary tool: `_execute` and nothing else. All 26 look like this."""

    name = "echo"
    description = "Echo the word back."
    Args = NoArgs
    side_effecting = False

    def __init__(self) -> None:
        self.thread: str = ""

    def _execute(self, args: Any) -> ToolResult:
        self.thread = threading.current_thread().name
        return ToolResult(content="echoed")


class AsyncOnly(BaseTool):
    """A tool whose work is genuinely async. It writes no `_execute`."""

    name = "async-only"
    description = "Await something."
    Args = NoArgs
    side_effecting = False

    def __init__(self) -> None:
        self.thread: str = ""

    async def _aexecute(self, args: Any) -> ToolResult:
        await asyncio.sleep(0)
        self.thread = threading.current_thread().name
        return ToolResult(content="awaited")


# --------------------------------------------------------------------------
# The shape itself.
# --------------------------------------------------------------------------


class TestTheShape:
    def test_execute_is_still_the_abstract_one(self) -> None:
        """The half that must not move: 26 implementations depend on it."""
        assert BaseTool._execute.__isabstractmethod__ is True
        assert not inspect.iscoroutinefunction(BaseTool._execute)

    def test_aexecute_is_concrete_and_a_coroutine(self) -> None:
        """Concrete, so nobody is forced to write it — the additive rule."""
        assert inspect.iscoroutinefunction(BaseTool._aexecute)
        assert getattr(BaseTool._aexecute, "__isabstractmethod__", False) is False

    def test_arun_is_the_async_twin_of_run(self) -> None:
        assert inspect.iscoroutinefunction(BaseTool.arun)
        assert not inspect.iscoroutinefunction(BaseTool.run)

    def test_the_itool_protocol_did_not_grow_arun(self) -> None:
        """A `runtime_checkable` Protocol is a load-bearing shape, not a list.

        `ITool` is deliberately a Protocol so a plain object can satisfy it
        without inheriting from us. Adding `arun` to it would make every
        third-party satisfier stop being one at the next `isinstance`, in
        their install, silently — a breaking change to Tier 1 wearing an
        addition's clothes.
        """

        class NotOurs:
            name = "x"
            description = "y"

            def run(self, **kwargs: Any) -> ToolResult:
                return ToolResult(content="ok")

        assert isinstance(NotOurs(), ITool)


# --------------------------------------------------------------------------
# Statement 1 — only `_execute`, and the async path works.
# --------------------------------------------------------------------------


class TestOnlyExecute:
    def test_the_async_path_answers(self) -> None:
        tool = Echo()

        assert drive(tool.arun).content == "echoed"

    def test_it_ran_in_a_thread_and_not_on_the_loop(self) -> None:
        """The default is a *thread*, which is the whole of its promise.

        Running a synchronous `_execute` on the event loop would be strictly
        worse than the `def` it replaced — `async-first/10` records that same
        mistake being refused one rung up, on the orchestrator.
        """
        tool = Echo()
        loop_thread: list[str] = []

        async def call() -> ToolResult:
            loop_thread.append(threading.current_thread().name)
            return await tool.arun()

        drive(call)

        assert tool.thread != loop_thread[0]

    def test_the_loop_keeps_running_while_it_works(self) -> None:
        """Not blocked: the loop makes progress while the tool is mid-call."""
        started = threading.Event()
        release = threading.Event()

        class Slow(Echo):
            def _execute(self, args: Any) -> ToolResult:
                started.set()
                release.wait(5.0)
                return ToolResult(content="slow")

        async def call() -> ToolResult:
            task = asyncio.create_task(Slow().arun())
            await asyncio.to_thread(started.wait, 5.0)
            # The loop is free while `_execute` blocks its thread: this
            # resolves, and the task is demonstrably still pending.
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            return await task

        assert drive(call).content == "slow"

    def test_errors_are_data_on_the_async_path_too(self) -> None:
        class Boom(Echo):
            def _execute(self, args: Any) -> ToolResult:
                raise RuntimeError("kaboom")

        result = drive(Boom().arun)

        assert result.ok is False
        assert result.error == "RuntimeError: kaboom"

    def test_invalid_arguments_are_data_on_the_async_path_too(self) -> None:
        result = drive(lambda: Echo().arun(unexpected="value"))

        assert result.ok is False
        assert result.error is not None
        assert result.error.startswith("Invalid arguments:")


# --------------------------------------------------------------------------
# Statement 2 — only `_aexecute`, and the sync path works.
# --------------------------------------------------------------------------


class TestOnlyAexecute:
    def test_it_is_instantiable_at_all(self) -> None:
        """`_execute` is abstract, so this is the statement that costs work.

        The bridge is installed at class-definition time by
        `__init_subclass__`, which runs before `ABCMeta` computes
        `__abstractmethods__` — so the class is concrete rather than an
        abstract class somebody has to remember to complete.
        """
        assert AsyncOnly().name == "async-only"
        assert AsyncOnly.__abstractmethods__ == frozenset()

    def test_the_sync_door_answers(self) -> None:
        assert AsyncOnly().run().content == "awaited"

    def test_the_sync_door_answers_from_inside_a_running_loop_too(self) -> None:
        """The awkward case, and the one that would raise if unhandled.

        `asyncio.run` refuses to nest, and a tool's `run()` is reachable from
        a thread that already has a loop — a caller mid-migration, a notebook,
        an agent whose other tools are async. The bridge gives the coroutine a
        thread of its own rather than raising.
        """

        async def call() -> ToolResult:
            return AsyncOnly().run()

        assert drive(call).content == "awaited"

    def test_the_async_door_does_not_go_through_a_thread(self) -> None:
        """The point of writing `_aexecute` at all: no thread hop."""
        tool = AsyncOnly()
        loop_thread: list[str] = []

        async def call() -> ToolResult:
            loop_thread.append(threading.current_thread().name)
            return await tool.arun()

        drive(call)

        assert tool.thread == loop_thread[0]

    def test_the_bridge_is_not_installed_on_a_tool_that_wrote_execute(self) -> None:
        """A tool that writes both keeps its own sync body, untouched."""

        class Both(Echo):
            async def _aexecute(self, args: Any) -> ToolResult:
                return ToolResult(content="async body")

        assert Both().run().content == "echoed"
        assert drive(Both().arun).content == "async body"

    def test_errors_are_data_through_the_bridge(self) -> None:
        class AsyncBoom(AsyncOnly):
            async def _aexecute(self, args: Any) -> ToolResult:
                raise RuntimeError("kaboom")

        result = AsyncBoom().run()

        assert result.ok is False
        assert result.error == "RuntimeError: kaboom"


# --------------------------------------------------------------------------
# Statement 3 — overrides neither, and still works.
# --------------------------------------------------------------------------


class TestOverridesNeither:
    def test_an_untouched_tool_still_answers_the_sync_door(self) -> None:
        """The 26, unchanged. This is what "additive" has to mean."""
        assert Echo().run().content == "echoed"

    def test_a_leaf_that_adds_nothing_answers_both_doors(self) -> None:
        class Leaf(Echo):
            name = "leaf"

        assert Leaf().run().content == "echoed"
        assert drive(Leaf().arun).content == "echoed"

    def test_a_leaf_of_an_async_only_tool_answers_both_doors(self) -> None:
        class AsyncLeaf(AsyncOnly):
            name = "async-leaf"

        assert AsyncLeaf().run().content == "awaited"
        assert drive(AsyncLeaf().arun).content == "awaited"

    def test_a_subclass_that_implements_nothing_is_still_refused(self) -> None:
        """Unmoved, and deliberately: this is the RC-04 protection.

        A tool that implements neither is abstract and says so at
        instantiation, naming the method. Giving `_execute` a default would
        have traded that for a class that installs cleanly and fails at call
        time — the worst failure shape this project has, per `abc/tool.py`.
        """

        class Nothing(BaseTool):
            name = "nothing"
            description = "d"
            Args = NoArgs

        assert "_execute" in Nothing.__abstractmethods__
        with pytest.raises(TypeError):
            Nothing()  # type: ignore[abstract]


# --------------------------------------------------------------------------
# Cancellation — the reason the map exists at all.
# --------------------------------------------------------------------------


class TestStopMeansStop:
    """Two arms, the way `async-first/06` proved it for node bodies.

    A thread-bridged `_execute` runs to completion after the cancel (today's
    behaviour, preserved); a native `_aexecute` never finishes. That is the
    difference `_aexecute` exists to make *available*, stated as a measurement
    rather than as a claim — and stated so nobody mistakes the default for the
    feature.
    """

    def test_a_thread_bridged_execute_runs_to_completion(self) -> None:
        started = threading.Event()
        finished = threading.Event()

        class Slow(Echo):
            def _execute(self, args: Any) -> ToolResult:
                started.set()
                threading.Event().wait(0.3)
                finished.set()
                return ToolResult(content="done")

        async def call() -> None:
            task = asyncio.create_task(Slow().arun())
            await asyncio.to_thread(started.wait, 5.0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        drive(call)

        assert finished.wait(5.0) is True

    def test_a_native_aexecute_is_genuinely_cancelled(self) -> None:
        finished = threading.Event()

        class SlowAsync(AsyncOnly):
            async def _aexecute(self, args: Any) -> ToolResult:
                await asyncio.sleep(0.3)
                finished.set()
                return ToolResult(content="done")

        async def call() -> None:
            task = asyncio.create_task(SlowAsync().arun())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0.5)

        drive(call)

        assert finished.is_set() is False

    def test_cancellation_is_not_swallowed_into_a_toolresult(self) -> None:
        """`arun` converts exceptions to data. A cancel is not an exception.

        `asyncio.CancelledError` is a `BaseException`, so `except Exception`
        cannot see it — but that is a property of the language somebody could
        undo with one edit of the handler, and "stop means stop" is the whole
        promise of this map.
        """

        class Sleeper(AsyncOnly):
            async def _aexecute(self, args: Any) -> ToolResult:
                await asyncio.sleep(5)
                return ToolResult(content="never")

        async def call() -> None:
            task = asyncio.create_task(Sleeper().arun())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        drive(call)


# --------------------------------------------------------------------------
# The LangChain seam — where an agent actually reaches a tool.
# --------------------------------------------------------------------------


class TestTheLangChainSeam:
    def test_the_adapted_tool_carries_a_coroutine(self) -> None:
        """Without this, `ainvoke` falls back to LangChain's own thread.

        Harmless for an `_execute` tool and wrong for an `_aexecute` one — it
        would put a native async body back in a thread and take the
        cancellation with it.
        """
        assert Echo().as_langchain_tool().coroutine is not None

    def test_ainvoke_reaches_a_native_async_body(self) -> None:
        tool = AsyncOnly()
        loop_thread: list[str] = []

        async def call() -> Any:
            loop_thread.append(threading.current_thread().name)
            return await tool.as_langchain_tool().ainvoke({})

        assert drive(call) == "awaited"
        assert tool.thread == loop_thread[0]

    def test_ainvoke_reaches_a_sync_body_too(self) -> None:
        adapted = Echo().as_langchain_tool()

        assert drive(lambda: adapted.ainvoke({})) == "echoed"

    def test_the_on_call_hook_fires_on_the_async_path(self) -> None:
        """`production-ready` 12's provenance hook, on the new path.

        A footer listing tools that were *offered* rather than *used* is the
        defect that hook exists to prevent; an async path that forgot to fire
        it would reintroduce exactly that, invisibly.
        """
        called: list[str] = []
        adapted = Echo().as_langchain_tool(on_call=called.append)

        drive(lambda: adapted.ainvoke({}))

        assert called == ["echo"]

    def test_a_failure_is_reported_the_same_way_on_both_paths(self) -> None:
        class Boom(Echo):
            def _execute(self, args: Any) -> ToolResult:
                raise RuntimeError("kaboom")

        adapted = Boom().as_langchain_tool()

        assert adapted.invoke({}) == drive(lambda: adapted.ainvoke({}))
        assert "kaboom" in adapted.invoke({})


# --------------------------------------------------------------------------
# The catalogue: 26 implementations, none of them touched.
# --------------------------------------------------------------------------


def _catalogue() -> dict[str, Any]:
    from openstategraph.api.registries import build_tool_registry

    return build_tool_registry(None, None)


class TestNoShippedToolWasAsked:
    def test_the_catalogue_is_not_empty(self) -> None:
        """A census that enumerates nothing passes for the wrong reason."""
        assert len(_catalogue()) >= 5

    def test_not_one_shipped_tool_declares_aexecute(self) -> None:
        """The additive claim, checked rather than asserted.

        The day one of them *should* — `McpTool` is the candidate, its session
        work already being async and already paired `func`/`coroutine` at the
        `StructuredTool` it builds — this test is where that is recorded.
        """
        declaring = {
            node_type: type(tool).__name__
            for node_type, tool in _catalogue().items()
            if isinstance(tool, BaseTool) and type(tool)._aexecute is not BaseTool._aexecute
        }

        assert declaring == {}

    def test_every_shipped_tool_inherits_the_async_door(self) -> None:
        for node_type, tool in _catalogue().items():
            if isinstance(tool, BaseTool):
                assert type(tool).arun is BaseTool.arun, node_type

    def test_a_real_shipped_tool_answers_the_async_door(self) -> None:
        """One end-to-end, so the census above is not the only evidence."""
        from openstategraph.prebuilt_platform import ListWorkflowsTool

        result = drive(ListWorkflowsTool().arun)

        assert isinstance(result, ToolResult)
