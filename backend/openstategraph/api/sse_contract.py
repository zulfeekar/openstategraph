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

from typing import Any

from openstategraph.api.streaming import FRAME_FIELDS, TERMINAL_EVENTS

#: Named once, because it is the sentence a custom client is most likely to
#: get wrong and OpenAPI has nowhere to put it.
STREAM_GUIDE = "docs/api.md"


def _frame_fields_sentence(events: tuple[str, ...]) -> str:
    """What each named frame carries, in a grammar a pin can read.

    OpenAPI cannot type a sequence of frames, but it can be told the
    vocabulary — and the level below the names is where the drift was
    (framework-packaging ticket 10). Written from `FRAME_FIELDS` rather than
    typed here, so `docs/openapi.json` publishes what the emitters carry and
    `src/core/runtime/contractDrift.test.ts` reads it from the artifact rather
    than from a second list somebody keeps in step by attention.

    Empty for an endpoint whose events are not run frames — `GET /api/events`
    carries one catalogue hint and has no entry, and inventing one so this
    sentence is never blank would be the mirror this exists to remove.
    """
    described = [name for name in events if name in FRAME_FIELDS]
    if not described:
        return ""
    per_frame = "; ".join(
        f"`{name}`: " + ", ".join(f"`{field}`" for field in FRAME_FIELDS[name])
        for name in described
    )
    return f"Frame fields: {per_frame}. "


def sse_responses(events: tuple[str, ...], summary: str) -> dict[int | str, Any]:
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
                f"{_frame_fields_sentence(events)}"
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
