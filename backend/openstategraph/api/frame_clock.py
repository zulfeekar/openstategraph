"""When a run frame was produced, and in what order — `memory-and-replay` 46.

One clock per stream, minted where the frame is built. The two fields it
produces ride on every run frame, and the reasoning for each is in
`docs/decisions/a-frame-says-when-2026-08-29.md`; the short version:

- **`seq`** — a dense counter from zero. Two frames can share a millisecond,
  so recorded order is a separate question from recorded time, and the cheaper
  of the two: a counter makes order recoverable without trusting a clock, and
  makes a dropped frame visible as a gap.
- **`elapsedMs`** — milliseconds since this stream opened, from
  `time.monotonic()`. Monotonic because a run crossing an NTP correction must
  not appear to go backwards. **Relative**, because an offset is what a
  scrubber needs, is smaller on the wire, and cannot say *when* the run
  happened — the wall anchor a reader needs to line a run up against a log
  file is `RunRecord.at`, which the same turn already writes in ISO wall time
  and which agrees with the checkpoints. Nothing here restates it, so nothing
  here can disagree with it.

**A server clock, and the surface has to say so.** This measures the moment
the backend produced the frame, not the moment a browser received it. The
browser's own arrival clock (`ExecutionEngine`, `performance.now()`) is still
there and still answers a different, legitimate question — what the *user*
experienced, a stalled network included. Neither replaces the other; a surface
showing one must not label it as the other.

**Bound to the stream, not to the process.** `open_frame_clock()` is entered
once by `_stream_run`, which is the single wrapper every run stream goes
through, so the counter belongs to one run. A module-level counter would make
the second run of a server's life start at forty. The catalogue stream
(`GET /api/events`) opens no clock and its frames carry no stamp: it is not a
run, its frames are not run frames, and it publishes no field list to widen.

**And re-bound on every resumption, which is the part that was missing**
(`launch-readiness` 108). A `ContextVar.set` inside a generator belongs to the
context of whoever resumed it, and the transport resumes this generator from a
*different* context every time: `stop_when_client_leaves` races each frame
against the disconnect, so each frame is pulled inside its own
`asyncio.ensure_future(stream.__anext__())`, and a Task runs on a **copy** of
the context that created it. The `set` performed while the first task drove the
generator therefore died with that task, and every frame after it was built with
no clock open. Measured on a live run before the fix: **1 of 282 frames carried
a stamp.**

So `open_frame_clock()` returns the clock and `bind_frame_clock()` re-attaches
it, once per resumption, from inside the generator being resumed — which is the
only place that runs in the context the frame will be built in. Pinned by
`backend/tests/test_the_frame_clock_survives_the_transport.py`, which drives the
fold *through* the transport rather than around it, because that is the whole
finding: the fold was never wrong, the driver was.
"""

from __future__ import annotations

import contextvars
import time
from contextlib import contextmanager
from collections.abc import Iterator

#: The fields a stamp adds, named once so `FRAME_FIELDS` can compose them into
#: every frame's declaration rather than each row repeating them.
FRAME_CLOCK_FIELDS: tuple[str, ...] = ("seq", "elapsedMs")

#: The clock of the stream this context is inside, if any.
_open_clock: contextvars.ContextVar["FrameClock | None"] = contextvars.ContextVar(
    "openstategraph_open_frame_clock", default=None
)


class FrameClock:
    """One stream's cadence: how many frames so far, and how long since it
    opened."""

    __slots__ = ("_origin", "_seq")

    def __init__(self) -> None:
        self._origin = time.monotonic()
        self._seq = 0

    def stamp(self) -> dict[str, int]:
        """The next frame's `seq` and `elapsedMs`. Advances the counter, so it
        is called exactly once per frame — by `_sse` and by nothing else."""
        seq = self._seq
        self._seq += 1
        return {"seq": seq, "elapsedMs": int((time.monotonic() - self._origin) * 1000)}


@contextmanager
def open_frame_clock() -> Iterator[FrameClock]:
    """Start a clock for one stream and bind it for the frames built inside.

    A clock opened inside another one is that one, unchanged: a nested door
    must not restart the numbering of the stream a client is reading — the
    same rule, and for the same reason, as `run_turn`'s silent nesting.
    """
    existing = _open_clock.get()
    if existing is not None:
        yield existing
        return

    clock = FrameClock()
    token = _open_clock.set(clock)
    try:
        yield clock
    finally:
        # Best effort, exactly as `run_journal.run_turn` documents: an async
        # generator gets no context of its own, so a streaming door's clock is
        # opened and closed from whichever context ASGI drove it in, and a
        # token reset across contexts raises. A context that never saw the
        # `set` has nothing to reset.
        try:
            _open_clock.reset(token)
        except ValueError:  # pragma: no cover - depends on the ASGI driver
            _open_clock.set(None)


def bind_frame_clock(clock: FrameClock) -> None:
    """Attach `clock` to *this* context, so frames built here are stamped.

    Called once per resumption of the streaming generator rather than once per
    stream — see the module docstring for why once is not enough. Idempotent
    and cheap: it re-sets a context variable to a value it may already hold,
    and it never starts a second clock, so the sequence stays dense.
    """
    _open_clock.set(clock)


def frame_stamp() -> dict[str, int]:
    """This frame's stamp, or nothing at all outside a stream.

    Empty rather than fabricated: a frame built with no clock open — the
    catalogue feed, or a test rebuilding a payload — has no run to be
    early or late in, and `{"seq": 0, "elapsedMs": 0}` would be a claim
    rather than an absence.
    """
    clock = _open_clock.get()
    return clock.stamp() if clock is not None else {}
