"""One in-process SSE fan-out, generic over the event it carries.

**Why this module exists now and did not before.** `catalogue_events.py` and
`patrol_events.py` each carry a `_Subscriber` and a broadcaster that are
identical line for line — bounded backlog under a `threading.Lock`, a wakeup
across the thread boundary through `loop.call_soon_threadsafe`, a
context-managed `subscribe()`. `patrol_events.py`'s own docstring priced the
duplication and set the extraction aside in as many words: *"a shared base
class today would be one abstraction serving exactly two call sites — the
wrong day to pay for one. If a third kind of live event ever needs this shape,
that is a real reason to extract the base; it is not one yet."*

`osg-agent-experience/36` is the third — `kanban_events.KanbanChangeWatcher`,
the fan-out behind `GET /api/kanban/events` — so the condition that module
wrote down has been met, and a third copy of ninety lines would be duplicated
*knowledge* rather than duplicated shape.

**What stays in the three modules is what actually differs**: the event
dataclass, its `as_dict()`, the frame-field tuple derived from it, the event
name, and each module's own account of its limits. Nothing about the queue.

The parameters are `Generic[E]`, not a base class to inherit: a broadcaster
*has* subscribers rather than *is* one of them, and neither caller subclasses
anything — `Broadcaster[CatalogueEvent]` is a use, not a specialisation. The
`E` need only be an object; the queue never reads a field of it.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import AsyncIterator
from contextlib import contextmanager
from typing import Generic, Iterator, TypeVar

logger = logging.getLogger(__name__)

E = TypeVar("E")

#: How many unread events a subscriber may bank before it is dropped.
#:
#: The bound exists to detect a **dead** subscriber, not to save memory — every
#: event on every stream that uses this is a handful of small fields. The
#: events are human-paced or interval-paced: one click publishes, one patrol
#: files a card, one store write moves a column. A connection that has failed
#: to consume 32 distinct such moments is not slow, it is gone (a suspended
#: laptop, a half-closed socket a proxy never reaped), and the honest response
#: is to drop it rather than to grow its queue for the life of the process. Its
#: client is an `EventSource`, which reconnects on its own and refetches on
#: open — so a wrongly dropped subscriber costs one reconnect, not a stale page.
DEFAULT_BACKLOG_LIMIT = 32

#: Seconds between SSE keepalive comments on an otherwise idle stream.
#:
#: An idle `text/event-stream` looks exactly like a hung one to a proxy or load
#: balancer, and the tightest idle timeout in common infrastructure is 30s
#: (nginx `proxy_read_timeout` is 60s, but AWS ALB and several ingress defaults
#: sit at 30s). 15s keeps a *missed or late* tick still inside a 30s window,
#: which a 20s interval would not; it is also cheap — two bytes plus framing,
#: four times a minute, per open surface. A property of the deployment rather
#: than of which stream it is, which is why all three share this one.
KEEPALIVE_SECONDS = 15.0


class Subscriber(Generic[E]):
    """One connected surface: a bounded backlog plus a wakeup.

    A `deque` under a `threading.Lock` rather than an `asyncio.Queue`, because
    `publish()` is called from FastAPI's threadpool (the mutating endpoints are
    sync `def`), from a patrol's executor thread, or from a watcher task, while
    the consumer runs on the event loop. `Queue.put_nowait` from another thread
    is not safe — it resolves a future — whereas a locked `deque.append` is, and
    it keeps the **drop decision synchronous**: whether a subscriber was dropped
    is known the instant `publish()` returns, which is what makes it testable
    without scheduling anything.

    Only the wakeup crosses the thread boundary, through
    `loop.call_soon_threadsafe`.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, limit: int) -> None:
        self._loop = loop
        self._limit = limit
        self._lock = threading.Lock()
        self._pending: deque[E] = deque()
        self._wakeup = asyncio.Event()
        #: True when this subscriber was dropped for falling too far behind.
        #: Reported to the consumer so it can end its stream honestly rather
        #: than block forever on a queue nobody fills any more.
        self.overflowed = False
        self.closed = False

    def offer(self, event: E) -> bool:
        """Bank one event. False means "I am full — drop me."""
        with self._lock:
            if self.closed:
                return False
            if len(self._pending) >= self._limit:
                self.overflowed = True
                self.closed = True
                deliverable = False
            else:
                self._pending.append(event)
                deliverable = True
        self._wake()
        return deliverable

    def close(self) -> None:
        """End this subscriber's stream at the next tick. Idempotent."""
        with self._lock:
            if self.closed:
                return
            self.closed = True
        self._wake()

    def _wake(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._wakeup.set)
        except RuntimeError:
            # The loop is closed — the consumer is already gone, so there is
            # nothing to wake and nothing to report.
            pass

    def _drain(self) -> tuple[list[E], bool]:
        with self._lock:
            batch = list(self._pending)
            self._pending.clear()
            return batch, self.closed

    async def events(self, *, idle_timeout: float | None = None) -> AsyncIterator[E | None]:
        """Every banked event, then `None` each time `idle_timeout` elapses idle.

        The idle tick is yielded rather than produced by a background task on
        purpose: a keepalive task would outlive a disconnected connection unless
        something cancelled it, and "something must remember to cancel it" is
        exactly the orphan-task discipline this repo has already audited. A
        timeout on the wait cannot be orphaned — there is no second task to leak.

        Ends when the subscriber is closed (disconnect) or dropped (overflow).
        """
        while True:
            # Cleared *before* draining: an event banked between the drain and
            # the wait re-sets it, so the wait returns immediately instead of
            # sleeping on work that already arrived.
            self._wakeup.clear()
            batch, closed = self._drain()
            for event in batch:
                yield event
            if closed:
                return
            if idle_timeout is None:
                await self._wakeup.wait()
                continue
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                yield None


class Broadcaster(Generic[E]):
    """In-process fan-out of one kind of event. Four public members.

    `subscribe()` and `attach()` are context managers, so unsubscription is
    structural rather than remembered: the endpoint's `with` block removes the
    subscriber whether it ended normally, was cancelled by a disconnect, or
    raised. They differ in one thing only, and it is ownership — see
    `attach()`.

    **In-process is the ceiling, and it is the documented one**:
    `openstategraph.deployment.check_worker_count` refuses a second worker
    outright (sqlite's per-instance write lock), so an event published on this
    process reaching only this process's subscribers costs nothing today. A
    multi-worker deployment needs Redis pub/sub or Postgres LISTEN/NOTIFY
    behind this same publish/subscribe pair.
    """

    def __init__(self, *, backlog_limit: int = DEFAULT_BACKLOG_LIMIT, label: str = "event") -> None:
        self._backlog_limit = backlog_limit
        self._label = label
        self._lock = threading.Lock()
        self._subscribers: set[Subscriber[E]] = set()

    @property
    def subscriber_count(self) -> int:
        """How many surfaces are currently connected. Ops and tests — and, for
        `kanban_events.KanbanChangeWatcher`, the thing that decides whether
        anybody is looking, so a store poll costs nothing while nobody is."""
        with self._lock:
            return len(self._subscribers)

    @contextmanager
    def subscribe(
        self, *, loop: asyncio.AbstractEventLoop | None = None
    ) -> Iterator[Subscriber[E]]:
        """Register for events for the duration of the block.

        Owns the subscriber it makes, which is what lets it end the stream on
        the way out. A caller that brings its own uses `attach`.
        """
        subscriber: Subscriber[E] = Subscriber(loop or asyncio.get_event_loop(), self._backlog_limit)
        try:
            with self.attach(subscriber):
                yield subscriber
        finally:
            subscriber.close()

    @contextmanager
    def attach(self, subscriber: Subscriber[E]) -> Iterator[Subscriber[E]]:
        """Register a subscriber somebody else owns, for the block.

        `subscribe()` minus the ownership, and the difference is the whole
        point: **it does not close the subscriber on the way out**
        (`osg-agent-experience/71`). One browser tab now holds a single
        connection carrying four subjects, so one `Subscriber` is registered
        with four fan-outs at once, and a `close()` from the first detach
        would end the other three mid-sentence. The connection that made the
        subscriber is the one that closes it.

        The registration itself is unchanged — same lock, same set — so a
        subscriber attached here is dropped on overflow exactly as one that
        subscribed, and `subscriber_count` counts it, which is what keeps a
        watcher's "is anybody looking" answer true.
        """
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            yield subscriber
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)

    def publish(self, event: E) -> None:
        """Fan one event out. Drops any subscriber that has fallen behind.

        Safe to call from a threadpool worker (which is where every mutating
        endpoint runs) as well as from the event loop.
        """
        with self._lock:
            targets = list(self._subscribers)
        dropped = [s for s in targets if not s.offer(event)]
        if not dropped:
            return
        with self._lock:
            for subscriber in dropped:
                self._subscribers.discard(subscriber)
        logger.warning(
            "dropped %d %s subscriber(s) that fell more than %d events behind",
            len(dropped),
            self._label,
            self._backlog_limit,
        )


# No `__all__` here on purpose — Tier 3, same as the three modules that use it;
# see `openstategraph/api/__init__.py`.
