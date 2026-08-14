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

from openstategraph.api.streaming import TERMINAL_EVENTS

#: Named once, because it is the sentence a custom client is most likely to
#: get wrong and OpenAPI has nowhere to put it.
STREAM_GUIDE = "docs/api.md"


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
                f"The full frame vocabulary, and the guarantee that every "
                f"stream ends with one of "
                f"{', '.join(f'`{n}`' for n in TERMINAL_EVENTS)}, are in "
                f"`{STREAM_GUIDE}` — OpenAPI cannot express either."
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
