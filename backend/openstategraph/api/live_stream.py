"""What one connection may carry — the registry behind `GET /api/events`.

**The problem, measured rather than anticipated** (`osg-agent-experience/71`,
staged on 2026-09-05 against the running editor). A browser allows **six
concurrent HTTP/1.1 connections per origin**. An editor tab held two long-lived
ones — `/api/events` for the catalogue and `/api/kanban/patrol/events` for the
job chip — before `69` was written, and `69`'s per-package watcher would have
been a third: with **two** tabs on one workflow the budget was gone, the last
`EventSource` sat at `readyState 0` for minutes, and an ordinary `fetch` in
that tab did not complete in 45 seconds. Two tabs on one workflow is `69`'s own
scenario, so a mechanism that fails there is not a mechanism, and `69` shipped
its endpoint with the editor deliberately not opening it.

HTTP/2 raises the limit to about a hundred and is **not** the answer: it is a
property of whatever proxy somebody put in front of this process, and this
project ships a `Caddyfile` and an `nginx.conf` as *examples*. A fix that works
only behind the right deployment is a fix that reads as intermittent.

**So a subject is a frame, not a socket.** `GET /api/events` carries every live
subject a surface asks for, and this module is the one place that says which
subjects exist, what each one's SSE `event:` name is, which query parameter
asks for it, and which dataclass serialises it.

## Four subjects, and the two halves they fall into

| Subject | Asked for by | Costs |
| --- | --- | --- |
| the catalogue | nothing — always on | an in-process fan-out |
| a patrol's progress | `patrol=1` | an in-process fan-out |
| card writes | `kanban=1` | a sqlite digest poll |
| one package's document | `slug=<slug>` | a `workflow.json` digest poll |

The first two are pure fan-outs: a publish reaches whoever is connected and
nothing runs in between. The last two own **poll tasks whose lifetime is the
set of subscribers**, which is the property `kanban_events.py` wrote down as
its reason for being a sibling stream rather than a frame on the patrol one:

> A poll hung off *that* stream's subscriber count would run for the life of
> every editor tab, board open or not.

That argument survives this fold intact, and it is why the extra subjects are
**opt-in** rather than merged unconditionally. A connection that never says
`kanban=1` is not attached to the kanban watcher, so it does not start the
poll; a plain `GET /api/events` — which is what `/chat` opens — sees exactly
the catalogue frames it saw before this ticket, and costs exactly what it cost.

## Why the frames are not renamed

Each subject keeps the `event:` name its own endpoint already gives it, so
`workflows.changed`, `patrol.status`, `kanban.changed` and `workflow.changed`
mean one thing each wherever they arrive. A client that reads one of the
sibling endpoints and a client that reads the merged stream parse the same
frame — there is one wire vocabulary, not a second one for the multiplexed
door. The sibling endpoints stay: the CLI, a custom client and anything with
connections to spare are the callers they were built for. It is the *editor*
that stops opening them.

## What this module is not

It is not a dispatcher and it holds no bodies. `LIVE_TOPICS` is a table the
route reads to decide what to attach and what to call each frame, and the
fields it publishes are taken from each event's own `as_dict()` — never typed
here, for the reason `kanban-patrol/31` and `/34` measured on two of these
streams already: a hand-typed tuple is a second spelling of a contract, and it
drifts the day somebody renames a field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openstategraph.api.catalogue_events import (
    CATALOGUE_EVENT,
    CATALOGUE_FRAME_FIELDS,
    CatalogueEvent,
)
from openstategraph.api.kanban_events import (
    KANBAN_EVENT,
    KANBAN_FRAME_FIELDS,
    KanbanChangedEvent,
)
from openstategraph.api.patrol_events import (
    PATROL_EVENT,
    PATROL_FRAME_FIELDS,
    PatrolEvent,
)
from openstategraph.api.workflow_events import (
    WORKFLOW_EVENT,
    WORKFLOW_FRAME_FIELDS,
    WorkflowChangedEvent,
)


@dataclass(frozen=True)
class LiveTopic:
    """One subject `GET /api/events` can carry.

    `asked_for` is the query parameter a client sets to receive it, and it is
    empty for the catalogue, which is what this endpoint has always carried
    and what every existing caller expects with no parameters at all.
    """

    asked_for: str
    event: str
    fields: tuple[str, ...]
    payload: type


#: Every subject the merged stream knows, in the order the guide lists them.
#:
#: A tuple rather than four `if` branches in the route: a fifth subject is a
#: row here plus the attachment that keeps its watcher alive, and the published
#: contract, the frame naming and the guide all move with it. This is
#: `CLAUDE.md`'s **O** at the smallest scale it is worth having — extend by
#: registering, never by editing the framer.
LIVE_TOPICS: tuple[LiveTopic, ...] = (
    LiveTopic("", CATALOGUE_EVENT, CATALOGUE_FRAME_FIELDS, CatalogueEvent),
    LiveTopic("patrol", PATROL_EVENT, PATROL_FRAME_FIELDS, PatrolEvent),
    LiveTopic("kanban", KANBAN_EVENT, KANBAN_FRAME_FIELDS, KanbanChangedEvent),
    LiveTopic("slug", WORKFLOW_EVENT, WORKFLOW_FRAME_FIELDS, WorkflowChangedEvent),
)

#: The `event:` names the merged stream may send, for `sse_contract`.
LIVE_EVENT_NAMES: tuple[str, ...] = tuple(topic.event for topic in LIVE_TOPICS)


def live_frame_fields() -> dict[str, tuple[str, ...]]:
    """What each frame carries, keyed by event name — for the published contract."""
    return {topic.event: topic.fields for topic in LIVE_TOPICS}


def live_frame_name(event: Any) -> str:
    """The SSE `event:` name for one event object.

    Resolved by type against the table above rather than by a field on the
    event, because none of the four carries one and adding one would be a
    fifth field on the wire that exists only to say what the `event:` line
    already says. A payload no topic claims is a programming error here, not a
    frame to guess at: it raises rather than reaching a client under a name
    nobody documented.
    """
    for topic in LIVE_TOPICS:
        if isinstance(event, topic.payload):
            return topic.event
    raise TypeError(f"no live topic carries {type(event).__name__}")


# No `__all__` here on purpose — Tier 3, like the four fan-outs it indexes; see
# `openstategraph/api/__init__.py`.
