"""A token frame says whether the model or a tool produced it (ticket 02).

LangGraph's `messages` stream mode carries every message a node emits, not
only model tokens, so a `ToolMessage` rides the same frames as the model's
prose. Untagged, the editor concatenated the two into one blob and rendered
the pair as Markdown — which collapsed `list_all_tables`' eleven-row table
onto a single line, making a tool result unreadable precisely because it was
long.

**Whose stream, though** (ticket 25). Tagging a tool result correctly is a
*developer's* need — the editor's trace tree folds these frames into per-call
result cards. A customer has no trace and no use for a schema dump, and read
one in the answer area for tens of seconds per run. So the frames below are
driven at `DEVELOPER`, which is what `AskPanel` sends, and the customer's
side of the same frame is asserted at the bottom of this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.api.audience import Audience  # noqa: E402
from openstategraph.api.streaming import _is_tool_message, _stream_run  # noqa: E402

KNOWN = {"agent_llm_1": "node:agent.llm-1"}


def _frames(chunks, audience: Audience = Audience.DEVELOPER):
    class _Graph:
        def stream(self, *_args, **_kwargs):
            return iter(chunks)

        def get_state(self, _config):
            return SimpleNamespace(next=(), tasks=())

        def get_graph(self, **_kwargs):
            return SimpleNamespace(draw_mermaid=lambda: "graph TD;")

    runtime = SimpleNamespace(
        diagnostics=CompileDiagnostics()
    )
    out = []
    for frame in _stream_run(
        _Graph(), {}, {}, SimpleNamespace(warnings=[]), KNOWN, runtime, "t1", audience
    ):
        name = frame.split("\n")[0][len("event: ") :]
        out.append((name, json.loads(frame.split("\n")[1][len("data: ") :])))
    return out


def _message(kind: str, content: str, **extra):
    return SimpleNamespace(type=kind, content=content, **extra)


def test_a_tool_message_is_recognised_by_its_type_discriminator() -> None:
    # Duck-typed on `type` so `ToolMessageChunk` counts too, without importing
    # the class hierarchy into the streaming layer.
    assert _is_tool_message(_message("tool", "x")) is True
    assert _is_tool_message(_message("AIMessageChunk", "x")) is False
    assert _is_tool_message(object()) is False


def test_a_tool_result_frame_names_the_tool_and_the_call_it_answers() -> None:
    events = _frames(
        [
            (
                (),
                "messages",
                (
                    _message(
                        "tool",
                        "| Table | Rows |\n| Album | 347 |",
                        name="chinook_list_tables",
                        tool_call_id="call_1",
                    ),
                    {"langgraph_node": "tools"},
                ),
            )
        ]
    )
    token = next(d for name, d in events if name == "token")

    assert token["kind"] == "tool"
    assert token["tool"] == {"name": "chinook_list_tables", "callId": "call_1"}
    # The content is passed through untouched — the line breaks ARE the result.
    assert token["content"] == "| Table | Rows |\n| Album | 347 |"


def test_model_text_stays_model_text() -> None:
    events = _frames(
        [
            (
                (),
                "messages",
                (_message("AIMessageChunk", "Rock"), {"langgraph_node": "agent_llm_1"}),
            )
        ]
    )
    token = next(d for name, d in events if name == "token")

    assert token["kind"] == "ai"
    assert token["tool"] == {"name": "", "callId": ""}
    # Additive only: everything an older client reads is unchanged.
    assert token["node"] == "node:agent.llm-1"
    assert token["content"] == "Rock"


def test_the_same_frame_reaches_a_customer_with_nothing_in_it() -> None:
    """Ticket 25's half of the same frame.

    QA watched this exact payload — an eleven-row Markdown schema dump —
    render inside the answer bubble of `/chat`, mid-run, for tens of seconds.
    A tool result is addressed to a model; a customer's stream keeps the
    frame (so the live diagram still knows where the run is) and drops its
    text and its identity.
    """
    events = _frames(
        [
            (
                (),
                "messages",
                (
                    _message(
                        "tool",
                        "| Table | Rows |\n| Album | 347 |",
                        name="chinook_list_tables",
                        tool_call_id="call_1",
                    ),
                    {"langgraph_node": "tools"},
                ),
            )
        ],
        Audience.CUSTOMER,
    )
    token = next(d for name, d in events if name == "token")

    assert token["content"] == ""
    assert token["withheld"] is True
    # The tool's NAME is developer material too — the ticket names it.
    assert token["tool"] == {"name": "", "callId": ""}
