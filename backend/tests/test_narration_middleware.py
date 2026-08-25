"""`launch-readiness/104`: a one-line "what is happening" narration around
every model call, on the base so every agent-family node gets it — not one
package's document.

No network, no model: these assert the hook fires, the text is generic (no
tool ids), it reaches a streaming consumer via the existing
`openstategraph.progress` seam (`report_progress` -> `custom` channel ->
`PROGRESS_KEY` envelope, per `docs-langchain`'s "Custom updates"), it sits in
the declared slot position, and it can be silenced without deleting it.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from openstategraph.abc.agent import AbstractAgentNode, ReactAgentNode
from openstategraph.abc.middleware import MiddlewareSlotTable
from openstategraph.abc.narration import NarrationMiddleware, build_narration_middleware
from openstategraph.progress import PROGRESS_KEY, progress_report


class _State(TypedDict, total=False):
    step: int


def _drive_hooks_through_a_real_graph(middleware: NarrationMiddleware) -> list[dict[str, Any]]:
    """Runs `before_model`/`after_model` inside an actual LangGraph run, the
    only place `get_stream_writer()` resolves to something real, and collects
    what streamed out on `stream_mode="custom"`."""

    def node(state: _State, runtime=None):
        middleware.before_model(state, runtime)
        middleware.after_model(state, runtime)
        return {"step": state.get("step", 0) + 1}

    graph = StateGraph(_State).add_node("node", node).add_edge(START, "node").add_edge("node", END).compile()

    events: list[dict[str, Any]] = []
    for chunk in graph.stream({"step": 0}, stream_mode="custom"):
        events.append(chunk)
    return events


class TestNarrationMiddleware:
    def test_fires_before_and_after(self) -> None:
        events = _drive_hooks_through_a_real_graph(NarrationMiddleware())
        assert len(events) == 2

    def test_lands_on_the_streamed_channel_not_only_the_final_message(self) -> None:
        events = _drive_hooks_through_a_real_graph(NarrationMiddleware())
        reports = [progress_report(e) for e in events]
        assert all(r is not None for r in reports)
        assert [r.message for r in reports] == [
            "Thinking about the next step.",
            "Finished thinking.",
        ]

    def test_uses_the_existing_progress_envelope_not_a_second_channel(self) -> None:
        events = _drive_hooks_through_a_real_graph(NarrationMiddleware())
        assert all(PROGRESS_KEY in e for e in events)

    def test_text_carries_no_tool_id_or_internals(self) -> None:
        events = _drive_hooks_through_a_real_graph(NarrationMiddleware())
        for e in events:
            report = progress_report(e)
            assert report is not None
            text = report.message.lower()
            assert "tool" not in text
            assert "id=" not in text
            assert "token" not in text

    def test_quiet_emits_nothing(self) -> None:
        events = _drive_hooks_through_a_real_graph(NarrationMiddleware(quiet=True))
        assert events == []

    def test_builder_is_the_bases_default_filler(self) -> None:
        mw = build_narration_middleware()
        assert isinstance(mw, NarrationMiddleware)


class TestSlotWiring:
    def test_narration_is_a_declared_slot(self) -> None:
        assert "narration" in AbstractAgentNode.SLOT_ORDER

    def test_default_on_every_agent(self) -> None:
        node = ReactAgentNode(name="a1", model=object())
        table = node.resolve_middleware()
        assert isinstance(table.get("narration"), NarrationMiddleware)

    def test_narrate_false_leaves_the_slot_empty(self) -> None:
        node = ReactAgentNode(name="a1", model=object(), narrate=False)
        table = node.resolve_middleware()
        assert table.get("narration") is None

    def test_a_config_contribution_of_none_silences_the_default(self) -> None:
        node = ReactAgentNode(name="a1", model=object(), middleware={"narration": None})
        table = node.resolve_middleware()
        assert table.get("narration") is None

    def test_a_config_contribution_replaces_the_default_narrator(self) -> None:
        sharper = NarrationMiddleware(before_text="Looking that up.")
        node = ReactAgentNode(name="a1", model=object(), middleware={"narration": sharper})
        table = node.resolve_middleware()
        assert table.get("narration") is sharper

    def test_narration_sits_right_after_screening(self) -> None:
        # Ordering contract, not behaviour: `injection-screening` must stay
        # first (security-sensitive — CLAUDE.md, `before_*` runs
        # first-to-last). Narration has nothing to order against it, so it
        # takes the very next slot: early enough that its `after_model` line
        # (after_* runs last-to-first) lands late, close to last.
        order = AbstractAgentNode.SLOT_ORDER
        assert order.index("narration") == order.index("injection-screening") + 1


class TestSlotTableNoneSilencing:
    def test_setting_none_removes_rather_than_flattens_a_none(self) -> None:
        table = MiddlewareSlotTable(order=("narration",))
        table.set("narration", "placeholder")
        table.set("narration", None)
        assert table.flatten() == []
