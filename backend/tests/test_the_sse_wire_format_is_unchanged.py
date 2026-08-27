"""The bytes on the wire did not move when the fold went async.

`async-first/02` turns `_run_frames` and `_stream_run` into async generators
driving `graph.astream()`. Nothing about that is supposed to be visible to a
client — and "supposed to be" is the part this file replaces with a fact.

**Byte-identical, not shape-identical.** The golden beside this file
(`data/sse_wire_format_golden.json`) was captured from the *synchronous* fold
before the migration and committed unchanged, so a green run here is the
before-and-after comparison the ticket asks for rather than a fresh snapshot
of whatever the code now does. It is compared as whole frame strings: the
`event:` line, the `data:` line, the blank line, the key order `json.dumps`
produced, every escape. A field renamed, reordered or dropped fails here.

That matters more than usual right now. `launch-readiness/110` is open about
narration frames not reaching the screen, and a second suspect on the same
seam would cost that investigation a session.

Both audiences are pinned, because the audience split decides what the
terminal frame carries and a customer's stream is the one nobody is watching
in a browser while they work.

Regenerating the golden is **not** the fix for a failure here. It records a
published contract (`docs/api.md`, `FRAME_FIELDS`); if a change genuinely
means to move it, that is a deliberate edit with its own ticket.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ScriptedGraph, drive_fold  # noqa: E402

from openstategraph.api.audience import Audience  # noqa: E402
from openstategraph.api.streaming import _stream_run  # noqa: E402
from openstategraph.compile.diagnostics import CompileDiagnostics  # noqa: E402

GOLDEN = Path(__file__).parent / "data" / "sse_wire_format_golden.json"

#: The canvas this scripted run belongs to. Four nodes, because the frames
#: worth pinning are the ones that carry a *resolved* canvas id.
KNOWN = {
    "in1": "in1",
    "router1": "node:router.1",
    "agent_sql": "agent-sql",
    "out1": "out1",
}


def _ai(content: str, **extra: Any) -> Any:
    return SimpleNamespace(type="AIMessageChunk", content=content, **extra)


def _tool(content: str, **extra: Any) -> Any:
    return SimpleNamespace(type="tool", content=content, **extra)


def _chunks() -> list[dict[str, Any]]:
    """One run touching every channel the fold reads.

    `updates`, `messages` (a model's tokens *and* a tool's result, which take
    different branches), and `custom` (a progress report) — the three modes
    `_run_frames` asks LangGraph for. In `version="v2"`'s `StreamPart` shape,
    which is the one we actually send.
    """
    from openstategraph.progress import PROGRESS_KEY, Progress

    return [
        {"type": "updates", "ns": (), "data": {"in1": {"answer": "", "outputs": {"in1": "hello"}}}},
        {"type": "updates", "ns": (), "data": {"router1": {"decisions": {"router1": "music"}}}},
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
            "data": (_ai("Let me "), {"langgraph_node": "agent_sql"}),
        },
        {
            "type": "messages",
            "ns": ("agent_sql:task-1",),
            "data": (_ai("check.\n"), {"langgraph_node": "agent_sql"}),
        },
        {
            "type": "messages",
            "ns": ("agent_sql:task-1",),
            "data": (
                _tool(
                    "| Table | Rows |\n| Album | 347 |",
                    name="list_tables",
                    tool_call_id="call_1",
                ),
                {"langgraph_node": "agent_sql"},
            ),
        },
        {
            "type": "updates",
            "ns": (),
            "data": {"agent_sql": {"outputs": {"agent_sql": "347 albums"}}},
        },
        {"type": "updates", "ns": (), "data": {"out1": {"answer": "There are 347 albums."}}},
    ]


class _Graph:
    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        return iter(_chunks())

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _frames(audience: Audience) -> list[str]:
    runtime = SimpleNamespace(diagnostics=CompileDiagnostics())
    return drive_fold(
        _stream_run(
            ScriptedGraph(_Graph()),
            {},
            {},
            SimpleNamespace(warnings=[]),
            KNOWN,
            runtime,
            "t1",
            audience,
        )
    )


def _golden() -> dict[str, list[str]]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_a_developers_stream_is_byte_for_byte_what_it_was() -> None:
    assert _frames(Audience.DEVELOPER) == _golden()["developer"]


def test_a_customers_stream_is_byte_for_byte_what_it_was() -> None:
    assert _frames(Audience.CUSTOMER) == _golden()["customer"]


def test_the_golden_covers_more_than_one_kind_of_frame() -> None:
    """A golden that only ever saw `done` would pass while proving nothing."""
    names = {frame.split("\n")[0][len("event: ") :] for frame in _golden()["developer"]}

    assert names >= {"update", "token", "progress", "done"}
