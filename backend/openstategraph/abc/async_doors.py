"""Two doors onto one verb, for the model-driven ladders (`async-first/05`).

`async-first/04` settled the shape one rung down, on `BaseTool`: a synchronous
verb an adopter implements, an awaitable twin beside it, and neither of them a
second class. This module is that shape made **available** to the router,
grader and orchestrator ladders rather than written out three times — which is
CLAUDE.md's boundary rule applied literally. Sharing across families is
composition, so this is a module of functions the three bases *call*; a common
`AbstractAsyncCapableNode` above them would be the god base class the same rule
forbids, and would force an async door onto `CustomGraphNode`, which has no
model call at all.

**The shape is LangChain's own, read off the installed `langchain-core 1.5.3`
rather than off a page.** `BaseChatModel._generate` is the `@abstractmethod`
and `_agenerate` is concrete; `BaseTool._run` is abstract and `_arun` is
concrete. In both pairs the synchronous half is the one an implementer owes and
the asynchronous half is the one the library supplies a default for. That is
the only shape available to a Tier-1 ladder anyway (`docs/stability.md`): an
adopter's `Router` subclass in their own repository cannot be asked to grow a
method on our schedule.

**What `install_doors` is for, and why it is not `try: await`.** Substitutability
is the whole risk here. A subclass that overrides only the synchronous verb must
still work when called asynchronously, and vice versa — CLAUDE.md's L, stated
without a caveat. The base cannot satisfy both by writing one body, because
whichever half it writes natively is the half that ignores the override. So the
doors are installed **per subclass**, at class-definition time, on exactly the
half that subclass did not write.
"""

from __future__ import annotations

import asyncio
import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Coroutine, Iterable, TypeVar

T = TypeVar("T")

#: Marks a method this module installed, so nothing mistakes a door for an
#: authored body when reading a class.
DOOR_ATTRIBUTE = "__osg_installed_door__"


def declares(cls: type, name: str, base: type) -> bool:
    """Did anything *below* `base` in `cls`'s MRO write `name` itself?

    The walk stops at `base` rather than filtering it out, so a default the
    base supplies for one half of a pair never reads as an override.
    """
    for klass in cls.__mro__:
        if klass is base:
            return False
        if name in klass.__dict__:
            return True
    return False


def install_doors(cls: type, base: type, pairs: Iterable[tuple[str, str]]) -> None:
    """Give a subclass whichever half of each pair it did not write.

    Called from the base's `__init_subclass__`, which matters for more than
    tidiness: `__init_subclass__` runs inside `type.__new__`, which
    `ABCMeta.__new__` calls **before** it computes `__abstractmethods__`. So a
    subclass that writes only the async half of an abstract pair — the
    orchestrator's `split` is exactly that — comes out concrete rather than
    abstract-and-half-finished, and the synchronous half can stay
    `@abstractmethod` for everybody else. `abc/tool.py` does the same thing for
    the same reason.

    A class that wrote both halves is left alone, and so is one that wrote
    neither: the base's own two bodies are then in charge, and those are the
    only place a native `ainvoke` is reached.
    """
    for sync_name, async_name in pairs:
        wrote_sync = declares(cls, sync_name, base)
        wrote_async = declares(cls, async_name, base)
        if wrote_sync and not wrote_async:
            setattr(cls, async_name, _async_door(sync_name))
        elif wrote_async and not wrote_sync:
            setattr(cls, sync_name, _sync_door(async_name))


def _async_door(sync_name: str) -> Callable[..., Any]:
    """The awaitable half over a synchronous body: a thread, never the loop.

    `asyncio.to_thread` and not a bare executor, deliberately — it copies the
    ambient context, so `get_stream_writer()` and `get_config()` still answer
    from inside an overridden `classify` (`launch-readiness/110`: a lost writer
    is a blank panel beside a green suite).

    **Not cancellable, and cannot be.** A thread runs to completion. What this
    door buys is availability on the async path, which is a different thing
    from this map's promise; only a natively async body stops when the run
    stops, and the test file says so in its own two-arm test.
    """

    async def door(self: Any, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self, sync_name)
        return await asyncio.to_thread(lambda: method(*args, **kwargs))

    door.__name__ = f"a{sync_name}"
    door.__qualname__ = door.__name__
    setattr(door, DOOR_ATTRIBUTE, True)
    return door


def _sync_door(async_name: str) -> Callable[..., Any]:
    """The synchronous half over an async body, driven to completion.

    The mirror of `compile/node_doors.py` one layer up, and here for the same
    reason: these ladders are reached from four synchronous doors this map does
    not migrate — the blocking `/api/runs`, the MCP server,
    `CompiledWorkflow.run` (the path a package's own `tests/` uses) and the
    CLI. A router that only worked under `astream` would not be substitutable
    for its base.
    """

    def door(self: Any, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self, async_name)
        return to_completion(lambda: method(*args, **kwargs))

    door.__name__ = async_name.removeprefix("a")
    door.__qualname__ = door.__name__
    setattr(door, DOOR_ATTRIBUTE, True)
    return door


def to_completion(make_coroutine: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run a coroutine from synchronous code, whether or not a loop is running.

    `asyncio.run` is the answer on a thread with no loop — a FastAPI
    threadpool worker, the CLI, a pytest process — and it *refuses to nest*,
    which is the case a bare `asyncio.run` would have shipped as a
    `RuntimeError` in whichever adopter reached one of these ladders from
    inside a coroutine first. So when a loop is already running here, the
    coroutine gets a thread of its own with a loop of its own.

    The context is copied into that thread rather than left behind, for the
    same reason the async door uses `asyncio.to_thread`: a step that stops
    seeing `report_progress()` is a blank panel with a green suite.

    Lived in `abc/tool.py` until `async-first/05`; moved here when the second
    and third ladders needed it, because duplication of *knowledge* is the
    defect the DRY rule names.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coroutine())

    context = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="osg-sync-door") as pool:
        return pool.submit(context.run, lambda: asyncio.run(make_coroutine())).result()


async def ainvoke_model(model: Any, messages: list[Any]) -> Any:
    """Await a model call, accepting a model that cannot be awaited.

    `model` is typed `Any` on all three ladders on purpose — the bases are
    model-agnostic and adapt to whatever the compiler hands them — and this
    repository already hands them something that has no `ainvoke`:
    `compile/node_runtime.py`'s `_DeepAgentAsChatModel`, built fresh per
    grading call, exposes a bare `invoke(messages)` and nothing else. A door
    that required `ainvoke` would refuse an object we construct ourselves, so
    the ladder is **tolerant in reading** here exactly as `normalise` is one
    method along: take the awaitable call when it exists, and put the other one
    in a thread rather than on the loop.

    Strict in trusting, though, and the narrowness is the safety: the only
    thing accepted in place of `ainvoke` is this object's own `invoke`. Nothing
    is invented, and nothing else is tried.
    """
    ainvoke = getattr(model, "ainvoke", None)
    if ainvoke is None:
        return await asyncio.to_thread(model.invoke, messages)
    return await ainvoke(messages)


__all__ = [
    "DOOR_ATTRIBUTE",
    "ainvoke_model",
    "declares",
    "install_doors",
    "to_completion",
]
