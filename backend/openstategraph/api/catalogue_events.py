"""Live catalogue changes — the fan-out behind `GET /api/events`.

**The problem.** `/chat` fetches its workflow picker once, on load. A customer
sitting on the page when someone publishes a workflow in the editor never sees
it; only a manual reload does. The editor's Workflows panel has the same blind
spot with respect to a second tab.

**The transport is SSE, deliberately.** This process already speaks SSE for run
streaming (`streaming.py`), the flow is one-way server → client, and
`EventSource` reconnects by itself with no client-side retry code. A WebSocket
would add a second protocol for a strictly weaker need; polling would add
latency and a request per client per interval for a signal that fires a few
times a day.

**This module is the fan-out only.** It knows nothing about SSE framing (that
stays `streaming._sse` — there is one framer), nothing about FastAPI, and
nothing about workflows beyond a slug. It is a collaborator hung on
`WorkflowServices`, not a base class and not a god object: subscribe, publish,
and the subscriber count for tests.

---

## Limits, stated rather than discovered

**One worker.** The fan-out is in-process: a publish reaches the subscribers of
*this* Python process and no other. That is not a regression, because the
deployment ceiling is already one worker — `docs/decisions/memory-architecture.md`
records why (`SqliteSaver`'s only write serialisation is a `threading.Lock` held
per instance, which two OS processes do not share), and `uvicorn --workers 1` is
what `Dockerfile` and `scripts/dev.sh` actually run. Raising the ceiling means
replacing this fan-out at the same time as the checkpointer: Redis pub/sub or
Postgres `LISTEN`/`NOTIFY` behind this same `publish`/`subscribe` pair, with the
endpoint and both clients unchanged. That is the named upgrade path.

**Only writes through the API emit.** `publish()` is called from the endpoints
that change the catalogue — save, publish/unpublish, delete. A `workflow.json`
edited **by hand on disk**, or created by `git pull`, emits nothing, so an open
surface will not learn about it until it refetches for some other reason. The
editor writes through the API, so this covers the editor; it does not cover a
text editor. A filesystem watch (`watchfiles`) would close that gap and is
recorded here as future work rather than implied to already work. (The editor
separately polls `savedAt` every 5s for the *document* it has open —
`src/app/workflowFileWatch.ts` — which is a different question from the
catalogue.)

**No replay.** A subscriber receives changes that happen while it is connected.
Anything it missed while disconnected is recovered by the refetch its client
does on (re)connect, which is the only correct answer anyway: the catalogue is
the source of truth, an event is just a hint to go and look.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import AsyncIterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Literal

logger = logging.getLogger(__name__)

#: Why a surface should refetch. One value per real mutation the API performs;
#: a read never produces one.
ChangeReason = Literal["published", "unpublished", "saved", "deleted"]


@dataclass(frozen=True)
class CatalogueEvent:
    """One change to the set of workflows a surface can see.

    Carries a *hint*, never a payload: `slug` says what moved and
    `surface_visible` says whether that slug is on the customer surface
    (`/api/workflows?surface=chat`) **after** the change. A client still
    refetches — sending the row itself would mean two spellings of the
    catalogue and one of them going stale.
    """

    reason: ChangeReason
    slug: str
    surface_visible: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "slug": self.slug,
            "surface_visible": self.surface_visible,
        }


#: How many unread events a subscriber may bank before it is dropped.
#:
#: The bound exists to detect a **dead** subscriber, not to save memory — each
#: event is three small fields. Catalogue changes are human-paced: one click
#: publishes, one save writes. A connection that has failed to consume 32
#: distinct human actions is not slow, it is gone (a suspended laptop, a
#: half-closed socket a proxy never reaped), and the honest response is to drop
#: it rather than to grow its queue for the life of the process. Its client is
#: an `EventSource`, which reconnects on its own and refetches on open — so a
#: wrongly dropped subscriber costs one reconnect, not a stale page.
SUBSCRIBER_BACKLOG_LIMIT = 32

#: Seconds between SSE keepalive comments on an otherwise idle stream.
#:
#: An idle `text/event-stream` looks exactly like a hung one to a proxy or load
#: balancer, and the tightest idle timeout in common infrastructure is 30s
#: (nginx `proxy_read_timeout` is 60s, but AWS ALB and several ingress defaults
#: sit at 30s). 15s keeps a *missed or late* tick still inside a 30s window,
#: which a 20s interval would not; it is also cheap — two bytes plus framing,
#: four times a minute, per open surface.
KEEPALIVE_SECONDS = 15.0


class _Subscriber:
    """One connected surface: a bounded backlog plus a wakeup.

    A `deque` under a `threading.Lock` rather than an `asyncio.Queue`, because
    `publish()` is called from FastAPI's threadpool (the mutating endpoints are
    sync `def`) while the consumer runs on the event loop. `Queue.put_nowait`
    from another thread is not safe — it resolves a future — whereas a locked
    `deque.append` is, and it keeps the **drop decision synchronous**: whether a
    subscriber was dropped is known the instant `publish()` returns, which is
    what makes it testable without scheduling anything.

    Only the wakeup crosses the thread boundary, through
    `loop.call_soon_threadsafe`.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, limit: int) -> None:
        self._loop = loop
        self._limit = limit
        self._lock = threading.Lock()
        self._pending: deque[CatalogueEvent] = deque()
        self._wakeup = asyncio.Event()
        #: True when this subscriber was dropped for falling too far behind.
        #: Reported to the consumer so it can end its stream honestly rather
        #: than block forever on a queue nobody fills any more.
        self.overflowed = False
        self.closed = False

    def offer(self, event: CatalogueEvent) -> bool:
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

    def _drain(self) -> tuple[list[CatalogueEvent], bool]:
        with self._lock:
            batch = list(self._pending)
            self._pending.clear()
            return batch, self.closed

    async def events(
        self, *, idle_timeout: float | None = None
    ) -> AsyncIterator[CatalogueEvent | None]:
        """Every banked event, then `None` each time `idle_timeout` elapses idle.

        The idle tick is yielded rather than produced by a background task on
        purpose: a keepalive task would outlive a disconnected connection unless
        something cancelled it, and "something must remember to cancel it" is
        exactly the orphan-task discipline this repo just audited. A timeout on
        the wait cannot be orphaned — there is no second task to leak.

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


class CatalogueBroadcaster:
    """In-process fan-out of catalogue changes. Three public members.

    `subscribe()` is a context manager, so unsubscription is structural rather
    than remembered: the endpoint's `with` block removes the subscriber whether
    it ended normally, was cancelled by a disconnect, or raised.
    """

    def __init__(self, *, backlog_limit: int = SUBSCRIBER_BACKLOG_LIMIT) -> None:
        self._backlog_limit = backlog_limit
        self._lock = threading.Lock()
        self._subscribers: set[_Subscriber] = set()

    @property
    def subscriber_count(self) -> int:
        """How many surfaces are currently connected. Ops and tests."""
        with self._lock:
            return len(self._subscribers)

    @contextmanager
    def subscribe(
        self, *, loop: asyncio.AbstractEventLoop | None = None
    ) -> Iterator[_Subscriber]:
        """Register for changes for the duration of the block."""
        subscriber = _Subscriber(loop or asyncio.get_event_loop(), self._backlog_limit)
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            yield subscriber
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)
            subscriber.close()

    def publish(self, event: CatalogueEvent) -> None:
        """Fan one change out. Drops any subscriber that has fallen behind.

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
            "dropped %d catalogue subscriber(s) that fell more than %d events behind",
            len(dropped),
            self._backlog_limit,
        )


# No `__all__` here on purpose — this module is Tier 3 (internal, no stability
# guarantee); see `openstategraph/api/__init__.py`.
