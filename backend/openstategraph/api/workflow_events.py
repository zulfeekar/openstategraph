"""One package's file moved — the fan-out behind `GET /api/workflows/{slug}/events`.

**The problem, in the owner's own words (2026-09-05):** *"a user opens three
tabs on the same workflow, how does each get the latest changes?"*
(`osg-agent-experience/69`.)

A `workflow.json` has four kinds of writer — an editor tab, a *second* editor
tab, `openstategraph` on the command line, and a coding agent through the MCP
server — and until this module only the first of them told anybody. A tab that
was not the writer learned nothing until its user reloaded, and
`osg-agent-experience/68` is the ticket about what a reload can cost.

## Why not a fifth `CatalogueEvent.reason`

**These frames do ride `/api/events` now** — `osg-agent-experience/71` folded
every live subject onto the one connection a browser tab can afford, and
`api/live_stream.py` is the table that says so. What follows is the argument
against making this a *catalogue* event, which that fold did not touch and
must not be read as having settled: the subject is still its own, the watcher
is still this one, and the frame is still `workflow.changed`.

`catalogue_events.py` already fans out a `CatalogueEvent`, and adding a fifth
`reason` to it was the cheaper build and is wrong for the reason that module
writes down itself:

> **Only writes through the API emit.** `publish()` is called from the
> endpoints that change the catalogue […] A `workflow.json` edited **by hand
> on disk**, or created by `git pull`, emits nothing.

That is precisely the half this ticket is about. The CLI and the MCP server do
not go through `save_workflow`, so an event raised *from the save route* is an
event three of the four writers never fire. This watcher observes the file
instead, so every writer is covered by construction and none of them has to
remember to announce itself — the same argument `kanban_events.py` made about
an agent's `openstategraph kanban stage`, and this module is deliberately that
module's shape rather than a third invention.

A catalogue event is also a different *subject*. It says a package appeared,
vanished or changed visibility, and every open surface listens to it; this says
one package's document has new bytes, and only the tabs editing that package
care. Sharing a connection did not make them one subject: a connection asks for
this one by naming a slug, the sweep still reads only what somebody named, and
a connection that asked about one package is never handed traffic about
another. That is the app-wide subscription `kanban_events.py` refused, still
refused.

## What a revision is, and why there is not a new one

**The digest already in force** — `workflow_store.package_digest`, the sha256
of `workflow.json`'s bytes, the same string a save quotes back as `base_digest`
and a summary publishes as `digest`. A monotonic counter was considered and
rejected: it would be a second version stamp for one file, it would have to be
persisted somewhere (a counter that resets when the process does is not
monotonic), and a client would then hold two answers to *which version is
this*, of which only one is checked by the 409. One seam, `osg-agent-experience
/45`'s, reused.

## What it costs, and only while somebody is looking

Per-slug interest, not a scan. `subscribe(slug)` says which package this
connection is editing, the poll digests only the slugs somebody is subscribed
to, and with no editor open the task does not exist. One `read_bytes` per
watched slug per interval — a `workflow.json` is tens of kilobytes — off the
event loop, exactly as its sibling does it.

**The frame is a hint, not a document.** It carries the slug and the digest and
nothing else; the client refetches `GET /api/workflows/{slug}`, so there is one
spelling of a document and no cache built from events that could disagree with
the file. **No replay**: a client that connects after a write sees nothing
about it, and does not need to, because opening a workflow reads it anyway.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from openstategraph.api.broadcast import DEFAULT_BACKLOG_LIMIT, Broadcaster, Subscriber

logger = logging.getLogger(__name__)

#: The SSE `event:` name every frame of `GET /api/workflows/{slug}/events`
#: carries — one name, spelled once, for `KANBAN_EVENT`'s own reason: a rename
#: cannot leave a document describing an event nobody sends.
WORKFLOW_EVENT = "workflow.changed"

#: Seconds between digest checks, while at least one editor is connected.
#:
#: Half its sibling's, and argued rather than picked. The kanban board watches
#: an agent narrate its own work, where a second reads as live. This one is
#: racing a *keystroke*: the editor's disk autosave debounces at one second, so
#: a second tab that learns of a change a second late can already have written
#: over it. Two seconds of polling plus the round trip is still slower than
#: `BroadcastChannel` for same-browser tabs, which is why the editor has both.
POLL_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True)
class WorkflowChangedEvent:
    """One package's `workflow.json` holds different bytes than it did.

    Two fields. The slug, because one stream serves every watched package and
    a client must be able to ignore a frame about a slug it is not editing;
    and the digest, which is the **revision** — the same string the client
    quotes as `base_digest` on its next save, so a tab can tell a frame about
    its own write from a frame about somebody else's without diffing
    documents. What changed *inside* the document is deliberately absent: that
    is a second spelling of a file the client is about to refetch.
    """

    slug: str
    digest: str

    def as_dict(self) -> dict[str, object]:
        return {"slug": self.slug, "digest": self.digest}


#: What every frame of `GET /api/workflows/{slug}/events` carries, published
#: into `docs/openapi.json` by `sse_contract.sse_responses`.
#:
#: Derived from `as_dict()` itself, never typed here — `kanban-patrol/31` and
#: `/34` measured what a hand-typed tuple costs on the sibling streams: a
#: rename that changes not one byte of the contract while the editor goes on
#: reading a key nobody sends.
WORKFLOW_FRAME_FIELDS: tuple[str, ...] = tuple(
    WorkflowChangedEvent(slug="", digest="").as_dict()
)


class WorkflowChangeWatcher:
    """Polls the packages somebody is editing, and only those.

    Six public members. `subscribe(slug)` is an async context manager rather
    than a sync one, because starting and stopping the poll task is part of
    subscribing: the task's lifetime *is* the set of subscribers, and making a
    caller remember to start it would be the orphan-task discipline this repo
    has already audited.
    """

    def __init__(
        self,
        digest_for: Callable[[str], str],
        *,
        interval: float | None = None,
        backlog_limit: int = DEFAULT_BACKLOG_LIMIT,
    ) -> None:
        #: Resolved per poll rather than at construction, its sibling's rule:
        #: the workflows root comes from an environment variable and a state
        #: directory, so a watcher built at app assembly must not freeze an
        #: answer taken before the process was configured.
        self._digest_for = digest_for
        self._interval = POLL_INTERVAL_SECONDS if interval is None else interval
        self._backlog_limit = backlog_limit
        self._broadcaster: Broadcaster[WorkflowChangedEvent] = Broadcaster(
            backlog_limit=backlog_limit, label="workflow"
        )
        self._task: asyncio.Task[None] | None = None
        #: How many connections are watching each slug, so the last one leaving
        #: stops it being polled. A `Counter` rather than a set because three
        #: tabs on one workflow is the case this whole ticket is named after.
        self._watching: Counter[str] = Counter()
        self._last: dict[str, str] = {}

    @property
    def subscriber_count(self) -> int:
        """How many editors are connected to this process. Ops and tests."""
        return self._broadcaster.subscriber_count

    @property
    def running(self) -> bool:
        """Whether anything is being polled at all right now."""
        return self._task is not None and not self._task.done()

    @property
    def watched_slugs(self) -> tuple[str, ...]:
        """Which packages are being polled, sorted. Ops and tests."""
        return tuple(sorted(self._watching))

    def publish(self, event: WorkflowChangedEvent) -> None:
        """Fan one change out, and adopt it as the baseline.

        Public for its sibling's reason — a change this process *knows* about
        need not wait up to an interval to be noticed — and it records the
        digest as seen so the next poll does not report the same change twice.
        """
        self._last[event.slug] = event.digest
        self._broadcaster.publish(event)

    @asynccontextmanager
    async def subscribe(self, slug: str) -> AsyncIterator[Subscriber[WorkflowChangedEvent]]:
        """Watch one package, and keep the poll alive, for the block."""
        subscriber: Subscriber[WorkflowChangedEvent] = Subscriber(
            asyncio.get_running_loop(), self._backlog_limit
        )
        try:
            async with self.attach(slug, subscriber):
                yield subscriber
        finally:
            subscriber.close()

    @asynccontextmanager
    async def attach(
        self, slug: str, subscriber: Subscriber[WorkflowChangedEvent]
    ) -> AsyncIterator[None]:
        """Watch one package for a subscriber the caller owns.

        `subscribe(slug)` minus the ownership — `osg-agent-experience/71`.
        The editor could not afford this stream's own socket (six connections
        per origin, two already spent, so *two* tabs saturated the budget), so
        its frames ride the connection the tab already holds and the caller
        brings one `Subscriber` for all four subjects. The per-slug cost model
        this module was built around is untouched: interest is still counted
        per slug, the sweep still reads only what somebody named, and the poll
        still exists only while an editor is connected.
        """
        try:
            with self._broadcaster.attach(subscriber):
                self._enter(slug)
                yield
        finally:
            # *Outside* the `with`, not in its own `finally`: the broadcaster
            # discards the subscriber in its exit, so asking "is anybody left"
            # one frame earlier always counts this connection as still here —
            # and the poll would then outlive the last editor.
            self._leave(slug)

    def _enter(self, slug: str) -> None:
        first = self._watching[slug] == 0
        self._watching[slug] += 1
        if first:
            # The baseline is taken *now*, so the first tick reports what
            # changed since this client connected rather than replaying
            # whatever the file happened to hold when the process started.
            self._last[slug] = self._digest_for(slug)
        if self.running:
            return
        self._task = asyncio.get_running_loop().create_task(self._poll())

    def _leave(self, slug: str) -> None:
        remaining = self._watching[slug] - 1
        if remaining > 0:
            self._watching[slug] = remaining
        else:
            del self._watching[slug]
            self._last.pop(slug, None)
        if self._watching:
            return
        task, self._task = self._task, None
        if task is not None:
            task.cancel()

    def _sweep(self) -> list[WorkflowChangedEvent]:
        changed: list[WorkflowChangedEvent] = []
        for slug in tuple(self._watching):
            digest = self._digest_for(slug)
            if self._last.get(slug) == digest:
                continue
            self._last[slug] = digest
            changed.append(WorkflowChangedEvent(slug=slug, digest=digest))
        return changed

    async def _poll(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                await asyncio.sleep(self._interval)
                # Off the event loop: it is a `stat` plus a file read per
                # watched package, small but blocking, and a stream nobody is
                # reading is still a stream this loop is serving.
                for event in await loop.run_in_executor(None, self._sweep):
                    self._broadcaster.publish(event)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - a watcher must not die quietly
            logger.exception("workflow change watcher stopped after an unexpected error")


def digest_reader(directory_for: Callable[[str], Path]) -> Callable[[str], str]:
    """Bind a store's directory lookup to the one digest the 409 already uses.

    A function rather than the watcher importing `WorkflowStore`: the watcher
    knows nothing about packages beyond a slug and a string, which is what lets
    its tests drive it with a dict, and this is the one place that says a
    revision *is* `package_digest(<dir>/workflow.json)`. A slug the store
    refuses to resolve digests as `""`, the same answer the store gives for a
    package that is not there — "nothing here to conflict with".
    """
    from openstategraph.api.workflow_store import package_digest

    def read(slug: str) -> str:
        try:
            return package_digest(directory_for(slug) / "workflow.json")
        except Exception:
            return ""

    return read


# No `__all__` here on purpose — Tier 3, same as its three sibling fan-outs;
# see `openstategraph/api/__init__.py`.
