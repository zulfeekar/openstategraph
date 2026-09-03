"""Live patrol progress — the fan-out behind `GET /api/kanban/patrol/events`.

**The problem, in `kanban-patrol/07`'s own words.** The patrol used to run
synchronously inside `POST /api/kanban/patrol/run` and answer in the same
response — fine while it stayed sub-second, wrong on purpose from here on,
because the whole point of this ticket is that a patrol must survive the
board being closed and the tab that started it going away. Once the run
moves to a background task, every open surface needs a way to learn what it
is doing without polling: started, a card filed, finished, or died.

**Why this is a sibling of `catalogue_events.py` and not an extension of it.**
That module's own docstring draws its boundary in as many words: *"nothing
about workflows beyond a slug"*. A patrol event is not a catalogue change —
it carries no `slug`, no `surface_visible`, and cramming `kind: "started"`
into `ChangeReason` would make a `Literal` that is honest about workflows
lie about patrols. The alternative — one generic broadcaster both modules
share — was weighed and set aside for now: the two `_Subscriber` classes
below and in `catalogue_events.py` are identical in shape (bounded backlog,
`threading.Lock`, `call_soon_threadsafe` wakeup) but each is small, each is
fully covered by its own module's tests, and a shared base class today would
be one abstraction serving exactly two call sites — the wrong day to pay for
one. If a third kind of live event ever needs this shape, that is a real
reason to extract the base; it is not one yet.

**The transport is unchanged: SSE, framed by `streaming._sse`, the one
framer in this codebase.** This module does not invent a second wire format —
it reuses the same function `catalogue_events`'s own endpoint reuses, so a
client reading either stream sees the same `event: / data: / blank line`
shape it already knows how to parse.

**One event name, one payload shape, a `kind` field inside it** — the same
choice `catalogue_events.py` made for `workflows.changed`/`ChangeReason`,
rather than five distinct SSE event names. A client that has never heard of
a `kind` still parses every frame; five event names would mean five
`addEventListener` calls to keep in sync by hand.

## What `kind` may be, and why there are four rather than five

`07`'s own text lists five: started, progressed ("a session attended"), a
card created, finished, failed. In this patrol's actual shape (`patrol.py`,
built to close the ticket's *prerequisite*) there is no session separate
from a card: every thread is read once, classified once, and either skipped
(already filed) or filed. So "a session attended" and "a card created" are
the same moment here, and inventing two events for one occurrence would ask
a client to reconcile them. `progressed` **is** the card-filed event, and it
carries `task_id` and `title` — enough for a client to say "filed: X" without
a second read. `started` and `finished`/`failed` bracket the whole run.

## The limits, stated exactly as `catalogue_events.py` states its own

**One worker.** Same enforced ceiling, same reason: this fan-out is
in-process, `openstategraph.deployment.check_worker_count` refuses a second
worker outright, and a patrol event published on this process reaches only
this process's subscribers. There being exactly one patrol running at a time
for the one project a process serves (`patrol_registry.PatrolJobRegistry`)
is not a coincidence beside that ceiling — it is the same constraint read
from the job side.

**No replay.** A subscriber sees what happens while it is connected, nothing
before. A client opening the board mid-patrol must refetch
`GET /api/kanban/patrol/status` — the job registry, not this stream — for
"is one already running", exactly as `catalogue_events.py` documents for its
own subscribers: an event is a hint to go and look, never the record itself.
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

#: The SSE `event:` name every frame of `GET /api/kanban/patrol/events`
#: carries — one name, mirroring `CATALOGUE_EVENT`'s reasoning exactly: a
#: rename cannot leave a document describing an event nobody sends, because
#: there is exactly one place that spells it.
PATROL_EVENT = "patrol.status"

#: What moment in a patrol's life a frame reports.
PatrolEventKind = Literal["started", "progressed", "finished", "failed"]


@dataclass(frozen=True)
class PatrolEvent:
    """One moment in a patrol's life.

    Every field defaults empty/zero so one dataclass serves all four kinds
    without four subclasses — `started` sets nothing but `kind`,
    `progressed` sets `task_id`/`title`, `finished` sets the three counts,
    `failed` sets `reason`. A client reads the fields that matter for the
    `kind` it received and ignores the rest, the same discipline
    `CatalogueEvent`'s `as_dict()` already asks of its own readers.
    """

    kind: PatrolEventKind
    #: `progressed` — the card just filed.
    task_id: str = ""
    title: str = ""
    #: `finished` — the summary `patrol.PatrolResult` already carries.
    filed: int = 0
    skipped: int = 0
    total_findings: int = 0
    #: `failed` — plain, in the words `07` itself insists on: *"a patrol
    #: that dies silently is worse than one that never started"*.
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "task_id": self.task_id,
            "title": self.title,
            "filed": self.filed,
            "skipped": self.skipped,
            "total_findings": self.total_findings,
            "reason": self.reason,
        }


#: What every frame of `GET /api/kanban/patrol/events` carries, published into
#: `docs/openapi.json` by `sse_contract.sse_responses` — `kanban-patrol/31`.
#:
#: Derived from `as_dict()` itself rather than typed here, and that is the
#: whole point: the endpoint used to publish its event *name* and stop, so
#: renaming `task_id` changed not one byte of the contract while the editor
#: went on reading a key nobody sent. A hand-typed tuple would have been a
#: third spelling of one fact and would have drifted the same way; this one
#: cannot say anything the serialiser does not.
PATROL_FRAME_FIELDS: tuple[str, ...] = tuple(PatrolEvent(kind="started").as_dict())


#: Same bound, same reasoning as `catalogue_events.SUBSCRIBER_BACKLOG_LIMIT`:
#: a patrol fires a handful of events per run (one per card, plus the two
#: brackets), so a subscriber banking 32 unread patrol events is not slow,
#: it is gone.
SUBSCRIBER_BACKLOG_LIMIT = 32

#: Same value and the same proxy-timeout argument as
#: `catalogue_events.KEEPALIVE_SECONDS` — reused rather than re-derived,
#: because the constraint (the tightest common idle timeout in front of this
#: process) is a fact about the deployment, not about which stream it is.
KEEPALIVE_SECONDS = 15.0


class _Subscriber:
    """One connected surface, watching patrol progress — `catalogue_events
    ._Subscriber`'s own shape, unchanged: a bounded backlog under a
    `threading.Lock` (because `publish()` runs on whichever thread files the
    card — the patrol's own background task, dispatched to an executor
    thread, see `routes/kanban.py`), plus a wakeup that crosses the thread
    boundary through `loop.call_soon_threadsafe`. See that class's docstring
    for the full reasoning; it applies here without a word changed.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, limit: int) -> None:
        self._loop = loop
        self._limit = limit
        self._lock = threading.Lock()
        self._pending: deque[PatrolEvent] = deque()
        self._wakeup = asyncio.Event()
        self.overflowed = False
        self.closed = False

    def offer(self, event: PatrolEvent) -> bool:
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
        with self._lock:
            if self.closed:
                return
            self.closed = True
        self._wake()

    def _wake(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._wakeup.set)
        except RuntimeError:
            pass

    def _drain(self) -> tuple[list[PatrolEvent], bool]:
        with self._lock:
            batch = list(self._pending)
            self._pending.clear()
            return batch, self.closed

    async def events(
        self, *, idle_timeout: float | None = None
    ) -> AsyncIterator[PatrolEvent | None]:
        while True:
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


class PatrolBroadcaster:
    """In-process fan-out of patrol events — `CatalogueBroadcaster`'s own
    shape, for a different kind of event. See that class for the full
    reasoning; `subscribe()` is a context manager for the same reason: the
    endpoint's `with` block unsubscribes on a normal end, a disconnect, or a
    raise, so nothing has to remember to.
    """

    def __init__(self, *, backlog_limit: int = SUBSCRIBER_BACKLOG_LIMIT) -> None:
        self._backlog_limit = backlog_limit
        self._lock = threading.Lock()
        self._subscribers: set[_Subscriber] = set()

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    @contextmanager
    def subscribe(
        self, *, loop: asyncio.AbstractEventLoop | None = None
    ) -> Iterator[_Subscriber]:
        subscriber = _Subscriber(loop or asyncio.get_event_loop(), self._backlog_limit)
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            yield subscriber
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)
            subscriber.close()

    def publish(self, event: PatrolEvent) -> None:
        """Fan one event out. Safe from a threadpool worker or an executor
        thread — where the patrol's background task actually runs, since
        `patrol.run_patrol` is a blocking, sqlite-writing function driven
        through `loop.run_in_executor` rather than on the event loop itself
        (`routes/kanban.py` documents why)."""
        with self._lock:
            targets = list(self._subscribers)
        dropped = [s for s in targets if not s.offer(event)]
        if not dropped:
            return
        with self._lock:
            for subscriber in dropped:
                self._subscribers.discard(subscriber)
        logger.warning(
            "dropped %d patrol subscriber(s) that fell more than %d events behind",
            len(dropped),
            self._backlog_limit,
        )


# No `__all__` here on purpose — Tier 3, same as `catalogue_events.py`; see
# `openstategraph/api/__init__.py`.
