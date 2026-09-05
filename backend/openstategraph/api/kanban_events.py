"""The board learns a card moved — the fan-out behind `GET /api/kanban/events`.

**The problem, in the owner's own words (2026-09-04):** *"would it be possible
to have the live status of a card, while the agent is attending the ticket and
changing the status?"* A coding agent attends a card, reports red, then green,
then finished — three writes through `openstategraph kanban stage` or
`kanban_set_stage`, each one a **separate process** calling
`kanban_store.set_stage` on `kanban.sqlite` directly. The server that serves
the board is one more reader of that file, so nothing in it ever learns a row
changed and an open board shows yesterday until somebody presses Refresh
(`osg-agent-experience/36`).

## Why this is not a frame on the patrol stream

`GET /api/kanban/patrol/events` already exists and the board already listens to
it, so adding a `kanban.changed` frame there was the cheaper build and was
rejected for two reasons, one of them measurable:

- **The patrol stream is subscribed app-wide.** `AppShell` mounts
  `usePatrolStatus` unconditionally — deliberately, so a patrol that started
  before the board was opened is still knowable — and the toolbar's job chip
  reads the same subscription. A poll hung off *that* stream's subscriber count
  would run for the life of every editor tab, board open or not. Hung off this
  one, which only the open board opens, "somebody is connected" means "somebody
  is looking at cards", which is exactly the condition the poll should cost
  anything under.
- **`patrol.status` describes a patrol run's life**, and `PatrolEventKind` is a
  four-name `Literal` that says so. An agent's stage write is not a moment in a
  patrol; a fifth kind would make that type lie, which is the argument
  `patrol_events.py` itself used for not riding the catalogue's fan-out.

The queue underneath is shared rather than copied a third time —
`broadcast.Broadcaster`, extracted for this ticket on the trigger
`patrol_events.py` wrote down itself.

## Why a poll, and what it costs

There is no write to hook. The write paths are other processes and they must
stay that way (`kanban-patrol/19`: one write function, no second door), so the
server can only *observe*. `LiveWorkflows` observes a package the same way
(`scale-and-adopt/14`), and this is its shape: a digest, checked on an interval,
compared. `kanban_store.store_digest` is the digest — file `mtime_ns` and size
plus three aggregates — and the interval is a second.

**The cost is paid only while a board is open.** The poll task starts when the
first subscriber connects and is cancelled when the last one leaves; with no
board open, this module does nothing at all. A `watchdog`-style filesystem
notification was considered and set aside: it is a dependency and a platform
matrix for a signal that is one sqlite query per second, and sqlite's own
journal files make "a write happened" a noisier event on disk than in the
table.

**The frame is a hint, not a card.** It carries the digest and nothing else;
the board refetches `GET /api/kanban/cards`, so there is exactly one spelling
of a card and no cache built from events that could disagree with the store —
`catalogue_events.py`'s rule, unchanged. **No replay**: a client that connects
after a write sees nothing about it, and does not need to, because opening the
board fetches the cards anyway.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from openstategraph.api.broadcast import DEFAULT_BACKLOG_LIMIT, Broadcaster, Subscriber

logger = logging.getLogger(__name__)

#: The SSE `event:` name every frame of `GET /api/kanban/events` carries — one
#: name, spelled once, for `PATROL_EVENT`'s own reason: a rename cannot leave a
#: document describing an event nobody sends.
KANBAN_EVENT = "kanban.changed"

#: Seconds between digest checks, while at least one client is connected.
#:
#: A second is under the threshold at which a board watching an agent work
#: reads as live, and the check is one `stat` plus one aggregate query on a
#: table of tens of rows. Nothing is checked while nobody is connected, so the
#: idle cost of this module is zero rather than small.
POLL_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class KanbanChangedEvent:
    """Something in the store moved. Which card, and how, is not in here.

    One field, deliberately: the digest that changed. A frame naming the card
    would be a second spelling of a row the board is about to refetch anyway,
    and the watcher does not know *which* row moved — it compares a digest, not
    a table. The digest is opaque to the client and useful for exactly one
    thing, which is why it is on the wire at all: a client can tell a repeat
    from a new change without diffing cards.
    """

    digest: str

    def as_dict(self) -> dict[str, object]:
        return {"digest": self.digest}


#: What every frame of `GET /api/kanban/events` carries, published into
#: `docs/openapi.json` by `sse_contract.sse_responses`.
#:
#: Derived from `as_dict()` itself, never typed here — `kanban-patrol/31` and
#: `/34` measured what a hand-typed tuple costs on the two sibling streams: a
#: rename that changes not one byte of the contract while the editor goes on
#: reading a key nobody sends.
KANBAN_FRAME_FIELDS: tuple[str, ...] = tuple(KanbanChangedEvent(digest="").as_dict())


class KanbanChangeWatcher:
    """Polls the store's digest while somebody is watching, and only then.

    Five public members. `subscribe()` is an async context manager rather than
    the sync one its siblings use, because starting and stopping the poll task
    is part of subscribing: the task's lifetime *is* the set of subscribers,
    and making a caller remember to start it would be the orphan-task
    discipline this repo has already audited.
    """

    def __init__(
        self,
        db_path: Callable[[], Path],
        *,
        interval: float | None = None,
        backlog_limit: int = DEFAULT_BACKLOG_LIMIT,
    ) -> None:
        #: Resolved per poll rather than at construction: `kanban_store_path`
        #: reads an environment variable and the state directory, and asking
        #: for it never creates anything, so a watcher built at app assembly
        #: must not freeze an answer taken before the process was configured.
        self._db_path = db_path
        self._interval = POLL_INTERVAL_SECONDS if interval is None else interval
        self._backlog_limit = backlog_limit
        self._broadcaster: Broadcaster[KanbanChangedEvent] = Broadcaster(
            backlog_limit=backlog_limit, label="kanban"
        )
        self._task: asyncio.Task[None] | None = None
        self._last: str | None = None

    @property
    def subscriber_count(self) -> int:
        """How many boards are open on this process. Ops and tests."""
        return self._broadcaster.subscriber_count

    @property
    def running(self) -> bool:
        """Whether the store is being polled at all right now."""
        return self._task is not None and not self._task.done()

    def publish(self, event: KanbanChangedEvent) -> None:
        """Fan one change out. Public because a *known* change — a write this
        process itself made through the API — is worth announcing without
        waiting up to an interval for the digest to notice it."""
        self._broadcaster.publish(event)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[Subscriber[KanbanChangedEvent]]:
        """Register for changes, and keep the poll alive, for the block."""
        subscriber: Subscriber[KanbanChangedEvent] = Subscriber(
            asyncio.get_running_loop(), self._backlog_limit
        )
        try:
            async with self.attach(subscriber):
                yield subscriber
        finally:
            subscriber.close()

    @asynccontextmanager
    async def attach(self, subscriber: Subscriber[KanbanChangedEvent]) -> AsyncIterator[None]:
        """Keep the poll alive for a subscriber the caller owns.

        `subscribe()` minus the ownership — `osg-agent-experience/71`, where
        an editor tab folded four subjects onto the one connection it can
        afford. What matters here is that the *cost* model is unchanged: the
        poll still starts on the first watcher and stops when the last one
        leaves, so a board that is not open still costs nothing even though
        the connection carrying its frames is now the one every tab holds.
        That is the property this module's own docstring wrote down as the
        reason it is a sibling stream, and folding the frame must not spend
        it.
        """
        try:
            with self._broadcaster.attach(subscriber):
                self._start()
                yield
        finally:
            # *Outside* the `with`, not in its own `finally`: the broadcaster
            # discards the subscriber in its exit, so asking "is anybody left"
            # one frame earlier always counts this connection as still here —
            # and the poll would then outlive the last board.
            self._stop_if_idle()

    def _start(self) -> None:
        if self.running:
            return
        # The baseline is taken *now*, so the first tick reports what changed
        # since this client connected rather than replaying whatever the digest
        # happened to be when the process started.
        self._last = self._digest()
        self._task = asyncio.get_running_loop().create_task(self._poll())

    def _stop_if_idle(self) -> None:
        if self._broadcaster.subscriber_count > 0:
            return
        task, self._task = self._task, None
        self._last = None
        if task is not None:
            task.cancel()

    def _digest(self) -> str:
        from openstategraph.kanban_store import store_digest

        return store_digest(self._db_path())

    async def _poll(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                await asyncio.sleep(self._interval)
                # Off the event loop: it is a `stat` plus a sqlite read, small
                # but blocking, and a stream nobody is reading is still a
                # stream this loop is serving.
                digest = await loop.run_in_executor(None, self._digest)
                if digest == self._last:
                    continue
                self._last = digest
                self._broadcaster.publish(KanbanChangedEvent(digest=digest))
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - a watcher must not die quietly
            logger.exception("kanban change watcher stopped after an unexpected error")


# No `__all__` here on purpose — Tier 3, same as its two sibling fan-outs; see
# `openstategraph/api/__init__.py`.
