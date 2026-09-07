"""What a run's output leaves behind, so a replay does not have to invent it.

`memory-and-replay` 47. `token` and `progress` are the two frames that arrive
while a node is *still working* — the only two that can explain a forty-second
stall — and both survived nowhere once the connection closed. The settled
message reached the checkpoint's `messages` channel; the chunks, their order,
their `block` and their `withheld` went with the socket. So anything built on
the old store and given a play button would re-type a stored paragraph at a
made-up rate, and a viewer reads motion as duration.

## The grain, chosen against a measurement rather than a preference

The ticket named three answers and assumed a tradeoff between them. Four real
`ollama:gpt-oss:120b-cloud` runs of `stress-review` and a private 28-node package say the
tradeoff does not exist, and `docs/decisions/keeping-the-cadence-2026-08-29.md`
carries the table. The short version:

- a **row per chunk** costs 26-107 KiB per run, for 242 to 1014 rows;
- a **burst row** costs 5-8 KiB for *the same information*, because what the
  per-chunk row was paying for was never the cadence — it was repeating one
  node's identity, namespace, block and kind once per chunk;
- and a burst row that keeps only a first and last offset is **not** cheaper
  than one that keeps every offset, in two of the three runs measured, while
  being wrong by a p99 of 470 ms.

That last number is why this module packs rather than summarises. Inside one
burst the measured inter-chunk gaps run from 0 ms to 555 ms, so a replay
interpolating across a burst renders half a second of stall as smooth typing.

## Where it sits, and why the audience boundary cannot be crossed here

**On the wire, not in the graph.** `_stream_run` hands every frame it is about
to yield to `frame`, so this records exactly what the client received. That is
what makes the boundary structural rather than a filter somebody has to
maintain: `_token_frame` empties a withheld frame's content *before* the frame
is built, so on a customer's stream there is no withheld text to be recorded,
and on a developer's there are no withheld frames. `38` found a replay door
leaking across this boundary once; this one cannot, because it never holds the
bytes.

**Nothing here touches disk.** A chunk is a list append and an integer
addition. The one write happens at the end of the turn, in the sink that was
already writing the run's row, in the same transaction.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from openstategraph.run_sinks import RunBurst, _encode_cadence

#: How many bursts one run may record. **A bound on memory during a run, and
#: not a sweep of anything written** — nothing recorded is ever dropped, which
#: is the store's standing rule (*conversations are gold*, and `runs export` is
#: the answer to a large file). This bounds the accumulator a runaway loop
#: would otherwise grow without limit inside a single turn.
#:
#: 400 against a measured 6-30 bursts per real run, so it is two orders of
#: magnitude above ordinary traffic and is reached only by a graph cycling. The
#: last burst kept says `capped`, so a reader can tell *the recording ends
#: here* from *the run ends here*.
BURST_CAP = 400


class BurstRecorder:
    """One run's cadence, coalesced as the frames go past.

    Constructed per stream and read once, at the end of the turn. Every method
    is O(1) in the number of chunks seen so far — the object a token loop can
    afford to call on every frame.
    """

    __slots__ = (
        "_audience", "_bursts", "_first_ms", "_first_seq", "_key", "_last_ms",
        "_last_seq", "_lengths", "_previous", "_refused", "_steps", "_text",
    )

    def __init__(self, audience: str = "") -> None:
        self._audience = audience
        self._bursts: list[RunBurst] = []
        #: The open burst's identity, or `None` before the first chunk.
        self._key: tuple[str, str, str, str, str, bool] | None = None
        self._steps: list[int] = []
        self._lengths: list[int] = []
        self._text: list[str] = []
        self._previous = 0
        self._first_seq = self._last_seq = 0
        self._first_ms = self._last_ms = 0
        #: A chunk arrived and the ceiling had been reached. The only thing
        #: that may set `capped`, so a run that ends at exactly `BURST_CAP`
        #: bursts of its own accord does not claim to have been cut off.
        self._refused = False

    def chunk(self, payload: Mapping[str, Any]) -> None:
        """Fold one `token` frame's payload in.

        A burst breaks on the identity changing and on nothing else — not on a
        pause. A pause *inside* a burst is a measurement this record keeps
        exactly, which is the whole reason the offsets are stored rather than
        the span; breaking on one would cost a row to say what the offsets
        already say.
        """
        if len(self._bursts) >= BURST_CAP:
            self._refused = True
            return
        key = (
            str(payload.get("node") or ""),
            # The owner is part of the identity, not a label hung on it: two
            # agents' loops both run through a LangGraph node called `model`,
            # so folding on the loop name alone would make them one burst
            # attributed to whichever spoke first (`memory-and-replay` 74).
            str(payload.get("activeNode") or ""),
            json.dumps(payload.get("namespace") or []),
            str(payload.get("block") or ""),
            str(payload.get("kind") or ""),
            bool(payload.get("withheld")),
        )
        if key != self._key:
            self._close()
            if len(self._bursts) >= BURST_CAP:
                self._refused = True
                return
            self._key = key
            self._previous = int(payload.get("elapsedMs") or 0)
            self._steps, self._lengths, self._text = [], [], []
            self._first_seq = int(payload.get("seq") or 0)
            self._first_ms = self._previous
        elapsed = int(payload.get("elapsedMs") or 0)
        text = str(payload.get("content") or "")
        self._steps.append(max(0, elapsed - self._previous))
        self._lengths.append(len(text))
        self._text.append(text)
        self._previous = elapsed
        self._last_seq = int(payload.get("seq") or 0)
        self._last_ms = elapsed

    def bursts(self) -> list[RunBurst]:
        """Everything recorded, oldest first, with the open burst closed.

        Read once, by the door, after the stream has ended. Calling it twice is
        safe and returns the same list.
        """
        self._close()
        if self._refused and self._bursts:
            # Set here rather than at `_close`, because only the finished run
            # knows which burst was the last one — and only a *refusal* makes
            # it a cut-off rather than an ending.
            self._bursts[-1] = self._bursts[-1].model_copy(update={"capped": True})
        return list(self._bursts)

    def _close(self) -> None:
        if self._key is None:
            return
        node, active_node, namespace, block, kind, withheld = self._key
        self._bursts.append(
            RunBurst(
                node=node,
                active_node=active_node,
                namespace=json.loads(namespace),
                block=block,
                kind=kind,
                withheld=withheld,
                audience=self._audience,
                first_seq=self._first_seq,
                last_seq=self._last_seq,
                first_ms=self._first_ms,
                last_ms=self._last_ms,
                chunks=len(self._lengths),
                chars=sum(self._lengths),
                text="".join(self._text),
                cadence=_encode_cadence(self._steps, self._lengths),
            )
        )
        self._key = None
