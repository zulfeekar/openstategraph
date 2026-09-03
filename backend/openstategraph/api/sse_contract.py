"""How an SSE endpoint describes itself in OpenAPI.

Lived in `api/main.py` until the route handlers moved onto routers
(reviews-2026-08-14 ticket 15). A router module decorates its own streaming
endpoints, so it needs this — and importing it back from `main` would make the
dependency a cycle, since `main` imports the routers.

The reasoning is unchanged and is the point of the module: OpenAPI 3.1 has no
way to describe "an unbounded sequence of frames, each tagged with one of these
event names, exactly one of which is last".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openstategraph.api.streaming import FRAME_FIELDS, TERMINAL_EVENTS

#: Named once, because it is the sentence a custom client is most likely to
#: get wrong and OpenAPI has nowhere to put it.
STREAM_GUIDE = "docs/api.md"


def _frame_fields_sentence(
    events: tuple[str, ...], frame_fields: Mapping[str, tuple[str, ...]] | None
) -> str:
    """What each named frame carries, in a grammar a pin can read.

    OpenAPI cannot type a sequence of frames, but it can be told the
    vocabulary — and the level below the names is where the drift was
    (framework-packaging ticket 10). Written from `FRAME_FIELDS` rather than
    typed here, so `docs/openapi.json` publishes what the emitters carry and
    `src/core/runtime/contractDrift.test.ts` reads it from the artifact rather
    than from a second list somebody keeps in step by attention.

    A stream whose frames are not run frames brings its own table through
    `frame_fields`, and the rule that mattered is unchanged rather than
    relaxed: the argument this docstring used to make was against **inventing**
    a table so the sentence is never blank, not against publishing one a
    serialiser already declares. `kanban-patrol/31` measured the difference —
    renaming a field on `patrol_events.PatrolEvent` changed not one byte of
    `docs/openapi.json`, so seven wire fields the editor reads by hand were
    outside the contract entirely, which is the mirror-without-a-pin
    `CLAUDE.md` names. `PATROL_FRAME_FIELDS` is derived from `as_dict()`
    itself; a caller that hand-types a tuple here has re-opened the defect.

    Still empty for an endpoint that supplies neither — `GET /api/events`
    carries one catalogue hint and has no table on either side, and that gap
    is `kanban-patrol/34` rather than something to paper over here.
    """
    known: dict[str, tuple[str, ...]] = {**FRAME_FIELDS, **(frame_fields or {})}
    described = [name for name in events if name in known]
    if not described:
        return ""
    per_frame = "; ".join(
        f"`{name}`: " + ", ".join(f"`{field}`" for field in known[name]) for name in described
    )
    return f"Frame fields: {per_frame}. "


def sse_responses(
    events: tuple[str, ...],
    summary: str,
    frame_fields: Mapping[str, tuple[str, ...]] | None = None,
) -> dict[int | str, Any]:
    """The OpenAPI `responses` entry for an endpoint that returns SSE.

    OpenAPI 3.1 has no way to describe "an unbounded sequence of frames, each
    tagged with one of these event names, exactly one of which is last". The
    honest move is therefore to declare the media type, name the vocabulary in
    the description, and send the reader to the prose — **not** to advertise a
    JSON body a client would then call `.json()` on and hang forever.
    """
    names = ", ".join(f"`{name}`" for name in events)
    return {
        200: {
            "description": (
                f"{summary}\n\nA `text/event-stream`. Event names: {names}. "
                f"{_frame_fields_sentence(events, frame_fields)}"
                f"The guarantee that every stream ends with one of "
                f"{', '.join(f'`{n}`' for n in TERMINAL_EVENTS)} is in "
                f"`{STREAM_GUIDE}` — OpenAPI cannot express it."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "title": "Server-sent event frames",
                        "description": (
                            "`event: <name>` and `data: <json>` lines, blank-line "
                            f"separated. See `{STREAM_GUIDE}`."
                        ),
                    }
                }
            },
        }
    }
