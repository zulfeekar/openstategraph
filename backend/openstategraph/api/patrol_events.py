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

import logging
from dataclasses import dataclass
from typing import Literal

from openstategraph.api.broadcast import (
    DEFAULT_BACKLOG_LIMIT,
)
from openstategraph.api.broadcast import KEEPALIVE_SECONDS as BROADCAST_KEEPALIVE_SECONDS
from openstategraph.api.broadcast import Broadcaster

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


#: Same bound and same keepalive as every other stream, taken from the module
#: that owns both (`broadcast.py`) rather than restated: a patrol fires a
#: handful of events per run, so a subscriber banking 32 unread patrol events
#: is not slow, it is gone, and an idle stream still has to look alive to a
#: proxy. Re-exported under the names this module has always published.
SUBSCRIBER_BACKLOG_LIMIT = DEFAULT_BACKLOG_LIMIT

#: Seconds between SSE keepalive comments on an otherwise idle stream — the
#: constraint is a fact about the deployment, not about which stream it is,
#: which is why it now has exactly one home.
KEEPALIVE_SECONDS = BROADCAST_KEEPALIVE_SECONDS


class PatrolBroadcaster(Broadcaster[PatrolEvent]):
    """In-process fan-out of patrol events.

    The queue is `broadcast.Broadcaster`, shared with the catalogue and kanban
    streams since `osg-agent-experience/36` — the extraction this module's own
    docstring asked for on the day a third stream needed the shape. This
    subclass binds the event type and the log label and adds no member.

    `publish()` is safe from a threadpool worker or an executor thread — where
    the patrol's background task actually runs, since `patrol.run_patrol` is a
    blocking, sqlite-writing function driven through `loop.run_in_executor`
    rather than on the event loop itself (`routes/kanban.py` documents why).
    """

    def __init__(self, *, backlog_limit: int = SUBSCRIBER_BACKLOG_LIMIT) -> None:
        super().__init__(backlog_limit=backlog_limit, label="patrol")


# No `__all__` here on purpose — Tier 3, same as `catalogue_events.py`; see
# `openstategraph/api/__init__.py`.
