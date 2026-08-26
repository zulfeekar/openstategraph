"""One MCP session per server, kept open — instead of one per tool call.

## The defect this exists to answer

`langchain-mcp-adapters` is stateless by default: hand `load_mcp_tools` a
`connection` and every `tools/call` re-opens the socket and re-runs the whole
handshake — `initialize`, `notifications/initialized`, `tools/list` — before
the call it was asked to make. `prebuilt_mcp`'s own header measured the cost
honestly and then *documented* it rather than removing it: 1.2–1.5 s a call, of
which ≈0.8 s is reconnection. An agent that calls four tools in a turn pays the
handshake four times, and a workflow that calls twenty pays it twenty.

That number is not a property of MCP. It is a property of passing `connection=`
where a live `session` would do. The adapters' tool body has both arms
(`tools.py`: `if session is None: … async with create_session(...)` / `else:
await session.call_tool(...)`), so the fix is to hold the session rather than
to rebuild it.

## Why a background loop, and why that is not the antipattern it looks like

A `ClientSession` is **loop-bound**. Its transport is a pair of anyio memory
streams owned by the task group that created them, so a session opened under
`asyncio.run` dies with that call and cannot be awaited from any other loop.
The previous design leaned on exactly that — "loop lifetime *is* session
lifetime *is* one tool call" — which is a true sentence describing the cost.

So a session that outlives a call needs a loop that outlives a call. This
module owns exactly one: a daemon thread running a single event loop for the
life of the process. Every MCP coroutine is marshalled onto it with
`run_coroutine_threadsafe`, from a worker thread (`.result()`) or from another
loop (`asyncio.wrap_future`) — **async-first**, in that the async caller never
blocks a thread and the sync caller never nests a loop inside a running one.

This is deliberately *not* an ambient loop that graph code runs on. Nothing
awaits user code here; the loop's only job is to own MCP transports, which is
the one thing that genuinely requires a stable loop identity.

## Reconnect is the proxy's job, not the caller's

A live session is a thing that can die — a server restarts, a proxy times an
idle connection out, a laptop sleeps. Handing the adapters a raw session would
capture it inside every bound tool, so one dead socket would poison an agent
for the rest of the run with no way back.

`McpSessionProxy` is therefore what gets handed over. It is duck-typed to the
two methods the adapters actually call (`call_tool`, `list_tools`), it opens
the real session lazily, and on a *transport* failure it drops the session,
opens a new one and retries the call **once**. Protocol failures are not
retried: a tool that raises because its arguments were wrong will raise again,
and a silent second call is how a retry turns a wrong answer into two.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import logging
import threading
from contextlib import AsyncExitStack
from typing import Any, Awaitable, Coroutine, Mapping, TypeVar, cast

logger = logging.getLogger(__name__)

__all__ = [
    "McpSessionProxy",
    "close_all_sessions",
    "run_on_mcp_loop",
    "run_on_mcp_loop_async",
    "session_proxy",
]

T = TypeVar("T")


# --------------------------------------------------------------------- #
# The loop that outlives a call
# --------------------------------------------------------------------- #


class _McpLoop:
    """A single daemon-thread event loop, started the first time it is needed.

    Started lazily rather than at import, because importing this package must
    not spawn a thread in a process that never touches MCP — a CLI printing
    `--help`, a test collecting.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and not self._loop.is_closed():
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run, args=(loop,), name="openstategraph-mcp", daemon=True
            )
            thread.start()
            self._loop, self._thread = loop, thread
            return loop

    @staticmethod
    def _run(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
        return asyncio.run_coroutine_threadsafe(coro, self.loop())

    def shutdown(self) -> None:
        with self._lock:
            loop, self._loop, self._thread = self._loop, None, None
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(loop.stop)


_LOOP = _McpLoop()


def run_on_mcp_loop(coro: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
    """Block this thread until `coro` finishes on the MCP loop.

    The replacement for `asyncio.run` at every sync entry point in
    `prebuilt_mcp`. It is safe from a worker thread — which is where
    `graph.invoke()` runs — and, unlike `asyncio.run`, it does not destroy a
    loop that sessions are living on.
    """
    if _running_on_mcp_loop():
        msg = "run_on_mcp_loop() was called from the MCP loop itself; await the coroutine."
        raise RuntimeError(msg)
    return _LOOP.submit(coro).result(timeout)


def run_on_mcp_loop_async(coro: Coroutine[Any, Any, T]) -> Awaitable[T]:
    """Await `coro` on the MCP loop from a *different* loop, without blocking.

    `wrap_future` is the bridge: the caller's loop suspends on an ordinary
    future while the work happens on the loop that owns the transport.
    """
    return asyncio.wrap_future(_LOOP.submit(coro))


def _running_on_mcp_loop() -> bool:
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return current is _LOOP._loop


# --------------------------------------------------------------------- #
# Failure classification — what may be retried
# --------------------------------------------------------------------- #


def _flatten(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [cause for sub in exc.exceptions for cause in _flatten(sub)]
    causes = [exc]
    if exc.__cause__ is not None:
        causes.extend(_flatten(exc.__cause__))
    return causes


def is_transport_failure(exc: BaseException) -> bool:
    """Whether a call failed because the *pipe* broke, rather than the request.

    Only these are retried. An `McpError` from a server rejecting arguments is
    not here on purpose — retrying it would double every bad call.
    """
    for cause in _flatten(exc):
        name = type(cause).__name__
        if name in {
            "ClosedResourceError",
            "BrokenResourceError",
            "EndOfStream",
            "ConnectError",
            "ConnectTimeout",
            "ReadError",
            "RemoteProtocolError",
            "IncompleteRead",
        }:
            return True
        if isinstance(cause, (ConnectionError, asyncio.IncompleteReadError)):
            return True
        if isinstance(cause, RuntimeError) and "closed" in str(cause).lower():
            return True
    return False


# --------------------------------------------------------------------- #
# The proxy the adapters are handed
# --------------------------------------------------------------------- #


class McpSessionProxy:
    """A `ClientSession`-shaped object that keeps one real session alive.

    Duck-typed rather than a subclass: `ClientSession`'s constructor takes the
    transport streams, so there is no honest way to subclass it into something
    that reconnects. The adapters call exactly two methods on a session
    (`call_tool`, `list_tools`), which is a narrow enough surface to mirror —
    and narrower interfaces are the point (`I` in the layering rules).

    Every method here runs **on the MCP loop**; nothing calls them from
    anywhere else.
    """

    def __init__(self, key: str, connection: Mapping[str, Any], *, timeout: float) -> None:
        self.key = key
        self._connection = dict(connection)
        self._timeout = timeout
        self._session: Any | None = None
        self._stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()

    # -- lifecycle ------------------------------------------------------ #

    async def _open(self) -> Any:
        from langchain_mcp_adapters.sessions import create_session

        stack = AsyncExitStack()
        # `cast`, not a TypedDict of our own: `Connection` is a union of four
        # library shapes, and building one here would put a vendor type in our
        # vocabulary — which the portability guardrails forbid.
        session = await stack.enter_async_context(create_session(cast(Any, self._connection)))
        await asyncio.wait_for(session.initialize(), self._timeout)
        self._stack, self._session = stack, session
        logger.debug("MCP session opened for %s", self.key)
        return session

    async def _ensure(self) -> Any:
        async with self._lock:
            if self._session is not None:
                return self._session
            return await self._open()

    async def _drop(self) -> None:
        async with self._lock:
            stack, self._stack, self._session = self._stack, None, None
        if stack is None:
            return
        try:
            await stack.aclose()
        except BaseException:  # noqa: BLE001 — closing a broken pipe often raises
            logger.debug("MCP session for %s did not close cleanly", self.key, exc_info=True)

    async def aclose(self) -> None:
        await self._drop()

    # -- the surface the adapters use ----------------------------------- #

    async def _attempt(self, call: str, *args: Any, **kwargs: Any) -> Any:
        session = await self._ensure()
        try:
            return await getattr(session, call)(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — an ExceptionGroup is a BaseException
            if not is_transport_failure(exc):
                raise
            logger.info("MCP session for %s broke mid-%s; reconnecting once", self.key, call)
            await self._drop()
            session = await self._ensure()
            return await getattr(session, call)(*args, **kwargs)

    async def call_tool(self, name: str, arguments: Any = None, **kwargs: Any) -> Any:
        return await self._attempt("call_tool", name, arguments, **kwargs)

    async def list_tools(self, *args: Any, **kwargs: Any) -> Any:
        return await self._attempt("list_tools", *args, **kwargs)

    async def initialize(self) -> Any:
        await self._ensure()


# --------------------------------------------------------------------- #
# The pool
# --------------------------------------------------------------------- #

_POOL: dict[str, McpSessionProxy] = {}
_POOL_LOCK = threading.Lock()


def pool_key(connection: Mapping[str, Any]) -> str:
    """Identity of a connection — URL, transport and *header names*.

    Header **names** and not values: two rows differing only by credential
    must still be two sessions, but a key that carried the value would put a
    token in a dict key, and from there into a repr, a log line and a
    traceback. The name plus the URL is enough to tell two rows apart, and the
    value can change under a live session without changing who it is.
    """
    headers = connection.get("headers") or {}
    named = ",".join(sorted(headers)) if isinstance(headers, Mapping) else ""
    return f"{connection.get('transport', '')}|{connection.get('url', '')}|{named}"


def session_proxy(connection: Mapping[str, Any], *, timeout: float) -> McpSessionProxy:
    """The one proxy for this connection, created on first ask.

    Keyed rather than per-node, because two `tool.mcp` cards naming the same
    server are the expected case and there is no reason for them to hold two
    sockets open to it.
    """
    key = pool_key(connection)
    with _POOL_LOCK:
        proxy = _POOL.get(key)
        if proxy is None:
            proxy = McpSessionProxy(key, connection, timeout=timeout)
            _POOL[key] = proxy
        return proxy


def close_all_sessions() -> None:
    """Shut every session and stop the loop. Tests call it; so does exit."""
    with _POOL_LOCK:
        proxies = list(_POOL.values())
        _POOL.clear()
    for proxy in proxies:
        try:
            run_on_mcp_loop(proxy.aclose(), timeout=5.0)
        except BaseException:  # noqa: BLE001 — shutdown must not raise
            logger.debug("MCP session %s did not close cleanly", proxy.key, exc_info=True)
    _LOOP.shutdown()


atexit.register(close_all_sessions)
