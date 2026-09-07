"""The clock `memory-and-replay` 46 minted reaches exactly one frame in a real run.

`launch-readiness` 108, and it is the *wire* half of that ticket.

46's own tests drive the fold with `drive_fold` — a bare `async for`, one
context for the whole stream — and under that driver every frame is stamped.
The transport is not a bare `async for`. `stop_when_client_leaves` races each
frame against the disconnect, which means each frame is pulled inside its own
`asyncio.ensure_future(stream.__anext__())`, and **a Task runs on a copy of the
context it was created in**. `open_frame_clock()`'s `ContextVar.set` happens
while the generator is resumed by the *first* such task, so the binding dies
with that task and every frame after the first is built with no clock open —
where `frame_stamp()` correctly returns nothing rather than fabricating a zero.

Captured on a live run before the fix (chinook-assistant, `gpt-oss:120b-cloud`,
through `/api/runs/stream`): **1 of 282 frames carried `seq` and `elapsedMs`.**
Not the terminal `done`, not the `error` frame on the credential-refused run —
one frame, the first.

That is not a cosmetic gap. 108 exists because the run timeline shows a
duration that cannot be true, and the only clock that could replace the
browser's arrival gaps is this one, so a clock that does not arrive is the
same defect one layer down.

**Driven through the transport, not around it**, because that is the whole
finding: the fold was never wrong, the driver was, and a test that drives it
the easy way cannot see it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ScriptedGraph  # noqa: E402

from openstategraph.api.audience import Audience  # noqa: E402
from openstategraph.api.frame_clock import FRAME_CLOCK_FIELDS  # noqa: E402
from openstategraph.api.streaming import (  # noqa: E402
    _stream_run,
    stop_when_client_leaves,
)
from openstategraph.compile.diagnostics import CompileDiagnostics  # noqa: E402

KNOWN = {"in1": "in1", "agent_sql": "agent-sql", "out1": "out1"}


def _ai(content: str, **extra: Any) -> Any:
    return SimpleNamespace(type="AIMessageChunk", content=content, **extra)


def _chunks() -> list[dict[str, Any]]:
    from openstategraph.progress import PROGRESS_KEY, Progress

    return [
        {"type": "updates", "ns": (), "data": {"in1": {"outputs": {"in1": "hello"}}}},
        {
            "type": "custom",
            "ns": (),
            "data": {
                PROGRESS_KEY: Progress(message="Read 40 of 100", node="agent_sql").model_dump()
            },
        },
        {
            "type": "messages",
            "ns": ("agent_sql:task-1",),
            "data": (_ai("Checking."), {"langgraph_node": "agent_sql"}),
        },
        {"type": "updates", "ns": (), "data": {"agent_sql": {"answer": "347."}}},
        {"type": "updates", "ns": (), "data": {"out1": {"answer": "There are 347 albums."}}},
    ]


class _Graph:
    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        return iter(_chunks())

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _run() -> Any:
    return _stream_run(
        ScriptedGraph(_Graph()),
        {},
        {},
        SimpleNamespace(warnings=[]),
        KNOWN,
        SimpleNamespace(diagnostics=CompileDiagnostics()),
        "t1",
        Audience.DEVELOPER,
    )


async def _still_here() -> dict:
    """An ASGI `receive` from a client that never says anything."""
    await asyncio.sleep(3600)
    return {"type": "http.request"}


def _through_the_transport() -> list[tuple[str, dict[str, Any]]]:
    async def go() -> list[str]:
        return [frame async for frame in stop_when_client_leaves(_run(), _still_here)]

    read: list[tuple[str, dict[str, Any]]] = []
    for frame in asyncio.run(go()):
        head, _, body = frame.partition("\ndata: ")
        read.append((head[len("event: ") :], json.loads(body.rstrip("\n"))))
    return read


class TestTheClockReachesTheWire:
    def test_the_run_produced_several_frames(self) -> None:
        """Anti-vacuity: a one-frame run would pass the next test by accident,
        which is exactly the shape of the bug."""
        assert len(_through_the_transport()) > 5

    def test_every_frame_is_dated_not_only_the_first(self) -> None:
        undated = [
            (index, name)
            for index, (name, payload) in enumerate(_through_the_transport())
            if any(field not in payload for field in FRAME_CLOCK_FIELDS)
        ]

        assert not undated, f"{len(undated)} frames arrived with no clock: {undated}"

    def test_the_sequence_is_still_dense_from_zero(self) -> None:
        payloads = _through_the_transport()

        assert [p["seq"] for _, p in payloads] == list(range(len(payloads)))

    def test_the_clock_never_runs_backwards(self) -> None:
        elapsed = [p["elapsedMs"] for _, p in _through_the_transport()]

        assert all(isinstance(value, int) and value >= 0 for value in elapsed), elapsed
        assert elapsed == sorted(elapsed)

    def test_the_terminal_frame_is_dated_too(self) -> None:
        """The frame a scrubber needs most: it is what says how long the whole
        run took."""
        name, payload = _through_the_transport()[-1]

        assert name in {"done", "interrupt", "error"}
        assert payload.get("elapsedMs") is not None
