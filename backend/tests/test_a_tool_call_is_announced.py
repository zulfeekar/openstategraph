"""An ordinary tool call says so before it runs — `memory-and-replay` 55.

`_SPAWNING_TOOLS` maps two names onto a `spawn` frame and the watcher infers
two more kinds structurally. Every **other** tool — a SQL query, an HTTP call,
anything a package puts in `tools/` — was announced by nothing at all. Its
*output* arrived later as a `token` frame with `kind: "tool"`. So this
installation had a tool-**result** vocabulary and no tool-**invocation** one.

**Measured, not estimated.** `stress-review` on `ollama:gpt-oss:120b-cloud`
with its `service_registry` tool slowed to 8 s: 680 frames, and the six longest
silences in a 91-second run were all the same shape — a `progress` line, then
**8.0 seconds of nothing**, then the result. The `updates` frame that reveals
the call arrives at the *start* of that window (the agent's internal `model`
step completing), which is why this reads the same seam `spawn` already reads
rather than inventing a live one.

## The three decisions

**A new frame kind, not a widened `spawn`.** `spawn`'s own guide row reads
*"the run created a child worker or subagent"*, and a SQL query creates no
child. Adding `kind: "tool"` would have been cheaper — no new name, and
`settled` would have closed it for free — and that is precisely the trade this
map keeps refusing: `loop`, `template` and `taskId` are three words this
repository has had to un-collide, and a fourth bought for one saved enum value
is not a saving.

**No close frame, because one already exists.** 54 needed `settled` because a
`subagent` and an `async` child produce *no frames at all*; here the end of the
bar is already on the wire — a `token` frame carrying `kind: "tool"` and the
very `callId` this frame mints. A second ending would be the duplication 54
refused, and it would double the cost measured above.

**No arguments, and no `TOOL_CALL_ARGS`.** AG-UI streams argument deltas. An
argument is a lens id a user never met, a file path this platform invented, or
a credential — `abc/tool_sentences.py` reaches the same conclusion from the
other side and states the rule outright: *"a tool is never named aloud"*, and
arguments are declared per tool, never guessed. A frame that carried them would
be the one surface where that rule did not hold.

## The audience

A tool's *name* is its own leak (ticket 25: QA read `music_store` on the
customer surface). So a customer's `invoked` frame is blanked exactly as a
customer's `token.tool` already is — `name` and `callId` emptied, `withheld:
true` — rather than withheld entirely. Emitting nothing would make "this
audience does not get it" and "no tool ran" the same wire shape, which is the
distinction `progress.detail` already exists to draw, and it would break 46's
pin that a customer's frames are numbered exactly as a developer's.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from conftest import ScriptedGraph, drive_fold

from openstategraph.compile.diagnostics import CompileDiagnostics

from openstategraph.api.streaming import (
    FRAME_FIELDS,
    PROGRESS_EVENTS,
    RUN_EVENTS,
    TERMINAL_EVENTS,
    ToolWatcher,
    _stream_run,
)


# --------------------------------------------------------------------------
# The vocabulary


def test_the_invocation_frame_is_declared_beside_the_result_it_precedes() -> None:
    assert "invoked" in RUN_EVENTS
    assert "invoked" in PROGRESS_EVENTS
    assert "invoked" not in TERMINAL_EVENTS


def test_the_invocation_frame_carries_an_identity_and_never_an_argument() -> None:
    assert FRAME_FIELDS["invoked"] == (
        "node", "namespace", "name", "callId",
        "activeNode", "path", "pathSlugs", "withheld",
        "seq", "elapsedMs",
    )
    for forbidden in ("args", "arguments", "instruction", "delta", "input"):
        assert forbidden not in FRAME_FIELDS["invoked"]


def test_the_join_is_the_field_the_result_frame_already_carries() -> None:
    """No close frame is added, so the join has to be one that already exists
    on the other end: `token.tool.callId`."""
    assert "callId" in FRAME_FIELDS["invoked"]
    assert "tool" in FRAME_FIELDS["token"]


# --------------------------------------------------------------------------
# The watcher


def _calling(*calls: tuple[str, str]) -> Any:
    return SimpleNamespace(
        tool_calls=[{"name": name, "id": call_id, "args": {"q": "secret"}}
                    for name, call_id in calls]
    )


def test_an_ordinary_tool_call_is_seen() -> None:
    watcher = ToolWatcher()

    assert watcher.inspect({"messages": [_calling(("service_registry", "c1"))]}) == [
        ("service_registry", "c1")
    ]


def test_a_spawning_tool_is_left_to_the_spawn_frame() -> None:
    """The two vocabularies must not both claim one call. `task` and
    `start_async_task` are announced as children; announcing them again here
    would put one tool call on the wire twice under two different words."""
    watcher = ToolWatcher()

    assert watcher.inspect({"messages": [_calling(("task", "c1"),
                                                  ("start_async_task", "c2"))]}) == []


def test_one_call_is_announced_once_however_often_the_message_is_re_read() -> None:
    """LangGraph replays a node's message list on more than one update frame;
    an agent that loops sees its own earlier calls again."""
    watcher = ToolWatcher()
    update = {"messages": [_calling(("query", "c1"))]}

    assert watcher.inspect(update) == [("query", "c1")]
    assert watcher.inspect(update) == []


def test_two_calls_to_the_same_tool_are_two_announcements() -> None:
    """`get_table_schema` on Invoice then on InvoiceLine — the case
    `token.tool.callId` exists for, read from the other end."""
    watcher = ToolWatcher()

    assert watcher.inspect(
        {"messages": [_calling(("get_table_schema", "c1"), ("get_table_schema", "c2"))]}
    ) == [("get_table_schema", "c1"), ("get_table_schema", "c2")]


def test_a_frame_with_no_messages_reveals_nothing() -> None:
    assert ToolWatcher().inspect({}) == []
    assert ToolWatcher().inspect({"messages": [SimpleNamespace()]}) == []


def test_a_nameless_call_is_not_announced() -> None:
    """Strict in trusting: a tool call whose name a provider did not send
    names nothing, and a frame saying so would be a row a reader cannot act
    on."""
    assert ToolWatcher().inspect({"messages": [_calling(("", "c1"))]}) == []


# --------------------------------------------------------------------------
# On the wire


class _Graph:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        return iter(self._chunks)

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _frames(chunks: list[Any], audience: Any = None) -> list[tuple[str, dict[str, Any]]]:
    from openstategraph.api.audience import Audience

    raw = drive_fold(
        _stream_run(
            ScriptedGraph(_Graph(chunks)),
            {"question": "q"},
            {"configurable": {"thread_id": "t"}},
            SimpleNamespace(warnings=[]),
            {"agent": "agent"},
            SimpleNamespace(diagnostics=CompileDiagnostics()),
            "t",
            audience or Audience.DEVELOPER,
        )
    )
    out: list[tuple[str, dict[str, Any]]] = []
    for frame in raw:
        name = frame.split("event: ", 1)[1].split("\n", 1)[0]
        out.append((name, json.loads(frame.split("data: ", 1)[1])))
    return out


_CALLS = [((), "updates", {"agent": {"messages": [_calling(("service_registry", "call-1"))]}})]


def test_the_frame_reaches_the_wire_before_the_step_reports() -> None:
    frames = _frames(_CALLS)
    names = [name for name, _ in frames]

    assert "invoked" in names
    assert names.index("invoked") < names.index("update")

    payload = next(p for name, p in frames if name == "invoked")
    assert payload["name"] == "service_registry"
    assert payload["callId"] == "call-1"
    assert payload["node"] == "agent"
    assert "withheld" not in payload


def test_a_customer_is_told_a_tool_ran_and_never_which_one() -> None:
    from openstategraph.api.audience import Audience

    customer = _frames(_CALLS, Audience.CUSTOMER)
    payload = next(p for name, p in customer if name == "invoked")

    assert payload["name"] == ""
    assert payload["callId"] == ""
    assert payload["withheld"] is True
    assert "secret" not in json.dumps(payload)


def test_the_two_audiences_still_carry_the_same_frames_in_the_same_order() -> None:
    """46's pin, restated where it could break: a frame emitted for one
    audience and not the other would make the cadence itself a channel."""
    from openstategraph.api.audience import Audience

    assert [name for name, _ in _frames(_CALLS, Audience.CUSTOMER)] == [
        name for name, _ in _frames(_CALLS, Audience.DEVELOPER)
    ]
