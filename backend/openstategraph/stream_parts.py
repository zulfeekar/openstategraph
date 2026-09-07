"""One LangGraph stream chunk, decoded, whichever shape it arrives in.

Its own module because there are two readers now, and there was nearly a
second spelling. `api/streaming.py` has decoded chunks since the SSE fold
existed; `run_stream.py` — the framework-free surface an adopter iterates —
has to decode exactly the same thing, and a fold that read the tuple while the
other read the envelope would disagree about a run the day LangGraph moved
either. `_stream_parts` said as much about its own two loops before it had a
sibling: *"two spellings of the chunk vocabulary, and the second one is the
one that goes stale."*

Core rather than `api/`, because nothing about a stream chunk is a web
concern, and `run_stream.py` may not import the API layer.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["stream_part", "stream_parts"]


def stream_part(chunk: Any) -> tuple[Any, str, Any] | None:
    """One chunk as `(namespace, mode, payload)`, or `None` if unreadable.

    We ask LangGraph for **`version="v2"`**, whose every chunk is a
    `StreamPart` — `{"type", "ns", "data"}` — regardless of how many modes were
    requested or whether `subgraphs=True` is set. v1, the default, yields a
    bare payload for one mode, a `(mode, payload)` pair for several, and a
    `(ns, mode, payload)` triple once subgraphs are on. Unpacking the triple
    was correct for exactly the combination we happened to pass and would have
    become wrong on the day a third mode was added — stable by accident rather
    than by contract.

    The v1 tuple is still accepted, and that is deliberate rather than
    leftover: nine test files script the SSE fold with hand-written chunks, and
    a decode change that can only be demonstrated by rewriting its own callers
    has not been isolated. `tests/test_stream_version_v2.py` pins the two
    shapes to identical frames and pins the `version="v2"` we actually send.

    `None` rather than a raise: a fold is the one place a run can die without a
    terminal frame reaching the consumer, so an unreadable chunk costs one
    frame, never the stream.
    """
    if isinstance(chunk, dict):
        mode = chunk.get("type")
        if isinstance(mode, str):
            return tuple(chunk.get("ns") or ()), mode, chunk.get("data")
        logger.warning("skipping an unreadable stream chunk: %r", sorted(chunk))
        return None
    if isinstance(chunk, tuple) and len(chunk) == 3:
        namespace, mode, payload = chunk
        return namespace, mode, payload
    logger.warning("skipping an unreadable stream chunk of type %s", type(chunk).__name__)
    return None


def stream_parts(stream: Any) -> Any:
    """`(namespace, mode, payload)` for each chunk of a **synchronous** stream.

    The async readers iterate with `async for` and call `stream_part` a chunk
    at a time; this exists for the scripted sync generators the SSE fold's
    tests drive it with.
    """
    for chunk in stream:
        decoded = stream_part(chunk)
        if decoded is not None:
            yield decoded
