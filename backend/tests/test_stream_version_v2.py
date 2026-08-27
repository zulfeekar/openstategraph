"""The stream chunk shape is stable by contract, not by accident (ticket 21).

`graph.stream()` defaults to `version="v1"`, whose chunk shape — the docs say
so outright — changes "based on your streaming options": a bare tuple for one
mode, `(mode, payload)` for several, `(ns, mode, payload)` once
`subgraphs=True`. We asked for two modes and subgraphs and unpacked a
three-tuple, which was right for exactly that combination and would have
silently become wrong the moment a third mode was added. `version="v2"`
normalises every chunk to `{"type", "ns", "data"}` whatever was asked for.

**Verified against the installed LangGraph 1.2.10, not only the page.**
`Pregel.stream`'s signature carries `version: Literal["v1", "v2"] = "v1"`, and
`langgraph/pregel/_messages.py` states the part that decides whether this is a
decode change or a contract change:

> Pregel attaches this class instead of the v1 handler only when
> `StreamingHandler` opts in via the internal `CONFIG_KEY_STREAM_MESSAGES_V2`
> config key; **direct `graph.stream(stream_mode="messages")` callers keep the
> v1 `AIMessageChunk` shape.**

So `version="v2"` moves the *envelope* and leaves the `messages` payload
exactly as it was. `RUN_EVENTS`, `docs/api.md` and `RuntimeClient.ts` are
untouched by this ticket, and the equivalence test below is what proves it.
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
from openstategraph.api.streaming import _stream_parts, _stream_run  # noqa: E402
from openstategraph.compile.diagnostics import CompileDiagnostics  # noqa: E402

KNOWN = {"agent_llm_1": "node:agent.llm-1", "in1": "in1"}


def _message(kind: str, content: str, **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(type=kind, content=content, **extra)


class _Graph:
    """A graph that records how it was asked to stream."""

    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks
        self.stream_kwargs: dict[str, Any] = {}

    def stream(self, *_args: Any, **kwargs: Any) -> Any:
        self.stream_kwargs = kwargs
        return iter(self._chunks)

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _frames(chunks: list[Any]) -> tuple[list[tuple[str, Any]], _Graph]:
    graph = _Graph(chunks)
    runtime = SimpleNamespace(diagnostics=CompileDiagnostics())
    out: list[tuple[str, Any]] = []
    for frame in drive_fold(_stream_run(
        ScriptedGraph(graph),
        {},
        {},
        SimpleNamespace(warnings=[]),
        KNOWN,
        runtime,
        "t1",
        Audience.DEVELOPER,
    )):
        name = frame.split("\n")[0][len("event: ") :]
        out.append((name, json.loads(frame.split("\n")[1][len("data: ") :])))
    return out, graph


class TestTheVersionWeAskFor:
    def test_the_fold_asks_for_v2(self) -> None:
        # The whole ticket in one assertion. Without it the fold is correct by
        # coincidence — it unpacks the shape v1 happens to produce for the two
        # modes and the subgraph flag it happens to pass.
        _, graph = _frames([])

        assert graph.stream_kwargs["version"] == "v2"

    def test_subgraphs_stay_on(self) -> None:
        # Verbatim from the doc, and not to be disturbed by this ticket:
        # without `subgraphs=True`, `stream_mode="messages"` on the parent
        # graph will not emit token chunks from the inner agent's LLM calls.
        _, graph = _frames([])

        assert graph.stream_kwargs["subgraphs"] is True


class TestTheDecoderReadsBothShapes:
    """The fold reads a part, not a tuple.

    The nine test files that script this fold express a chunk as the v1 tuple,
    and they are unchanged by this ticket on purpose — a decode change that
    needs its own callers rewritten to prove itself has not been isolated. So
    the normaliser accepts both and this class pins the equivalence directly.
    """

    def test_a_v2_part_decodes_to_the_same_frame_as_a_v1_tuple(self) -> None:
        v1 = [((), "updates", {"in1": {"outputs": {"in1": "hello"}}})]
        v2 = [{"type": "updates", "ns": (), "data": {"in1": {"outputs": {"in1": "hello"}}}}]

        assert _frames(v1)[0] == _frames(v2)[0]

    def test_a_namespaced_v2_part_keeps_its_namespace(self) -> None:
        events, _ = _frames(
            [
                {
                    "type": "messages",
                    "ns": ("wf_music:abc",),
                    "data": (
                        _message("AIMessageChunk", "Rock"),
                        {"langgraph_node": "agent_llm_1"},
                    ),
                }
            ]
        )
        token = next(data for name, data in events if name == "token")

        assert token["namespace"] == ["wf_music:abc"]
        assert token["content"] == "Rock"

    def test_an_unknown_part_shape_is_skipped_rather_than_crashing(self) -> None:
        # A part with no `type` is not something this version emits; the fold
        # is the one place a run can die without a terminal frame, so it steps
        # over what it cannot read instead of raising through the whole stream.
        events, _ = _frames([{"nonsense": 1}, ((), "updates", {"in1": {}})])

        assert [name for name, _ in events] == ["update", "done"]

    def test_the_normaliser_reports_each_shape_the_same_way(self) -> None:
        assert list(_stream_parts(iter([((), "updates", {"a": 1})]))) == [
            ((), "updates", {"a": 1})
        ]
        assert list(_stream_parts(iter([{"type": "updates", "ns": (), "data": {"a": 1}}]))) == [
            ((), "updates", {"a": 1})
        ]
