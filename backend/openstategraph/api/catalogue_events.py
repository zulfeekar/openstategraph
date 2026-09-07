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

**One worker — and this module is now one of the two reasons why.** The fan-out
is in-process: a publish reaches the subscribers of *this* Python process and no
other. Since scale-and-adopt ticket 06 that is not a caveat but an enforced
limit: `openstategraph.deployment` refuses a second worker outright, naming this
queue alongside `SqliteSaver`'s per-instance write lock.

The distinction that ticket turned on is worth keeping here, because it decides
what a future change is allowed to do. The checkpointer half of the ceiling has
a shipped fix (`openstategraph/postgres.py`, the `[postgres]` extra); **this
half does not**. Raising the ceiling therefore means replacing this fan-out
*at the same time*: Redis pub/sub or Postgres `LISTEN`/`NOTIFY` behind this same
`publish`/`subscribe` pair, with the endpoint and both clients unchanged
(register RC-17). Doing only the checkpointer half and lifting the refusal would
produce a deployment that looks correct and silently drops catalogue updates for
half its users — a worse failure than the one it fixed. Both halves or neither.

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

import logging
from dataclasses import dataclass
from typing import Literal

from openstategraph.api.broadcast import (
    DEFAULT_BACKLOG_LIMIT,
)
from openstategraph.api.broadcast import KEEPALIVE_SECONDS as BROADCAST_KEEPALIVE_SECONDS
from openstategraph.api.broadcast import Broadcaster

logger = logging.getLogger(__name__)

#: The SSE `event:` name every frame of `GET /api/events` carries. One name,
#: named once: the endpoint frames with it and `docs/api.md` documents it, and
#: `backend/tests/test_api_guide.py` reads this constant rather than a literal
#: so a rename cannot leave the guide describing an event nobody sends.
CATALOGUE_EVENT = "workflows.changed"

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


#: What every frame of `GET /api/events` carries, published into
#: `docs/openapi.json` by `sse_contract.sse_responses` — `kanban-patrol/34`.
#:
#: Derived from `as_dict()` itself rather than typed here, for the reason
#: `patrol_events.PATROL_FRAME_FIELDS` gives: this endpoint used to publish its
#: event *name* and stop, so renaming `surface_visible` changed not one byte of
#: the contract while `WorkflowFileClient.watchCatalogue` went on reading a
#: wire key nobody sent. A hand-typed tuple would have been a third spelling of
#: one fact and would have drifted the same way; this one cannot say anything
#: the dataclass does not.
CATALOGUE_FRAME_FIELDS: tuple[str, ...] = tuple(
    CatalogueEvent(reason="saved", slug="", surface_visible=False).as_dict()
)


#: The backlog bound and the keepalive interval, from the one module that owns
#: them (`broadcast.py`) rather than re-derived here — both are facts about the
#: deployment (a dead subscriber, a proxy's idle timeout) rather than about
#: which stream carries them, and this module used to state the argument for
#: each a second time. Re-exported under their long-standing names so nothing
#: importing them has to move.
SUBSCRIBER_BACKLOG_LIMIT = DEFAULT_BACKLOG_LIMIT

#: Seconds between SSE keepalive comments on an otherwise idle stream — see
#: `broadcast.KEEPALIVE_SECONDS` for the 30-second-idle-timeout argument.
KEEPALIVE_SECONDS = BROADCAST_KEEPALIVE_SECONDS


class CatalogueBroadcaster(Broadcaster[CatalogueEvent]):
    """In-process fan-out of catalogue changes.

    The queue itself is `broadcast.Broadcaster`, shared with the patrol and
    kanban streams since `osg-agent-experience/36` — this subclass exists to
    bind the event type and the log label, and adds no member of its own. See
    that module for the backlog, the thread-safety and the one-worker ceiling.
    """

    def __init__(self, *, backlog_limit: int = SUBSCRIBER_BACKLOG_LIMIT) -> None:
        super().__init__(backlog_limit=backlog_limit, label="catalogue")


# No `__all__` here on purpose — this module is Tier 3 (internal, no stability
# guarantee); see `openstategraph/api/__init__.py`.
