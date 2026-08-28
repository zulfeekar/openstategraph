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

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
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
    def test_the_model_hooks_speak_once_where_they_know_something(self) -> None:
        # `launch-readiness/143`. Two lines became one, deliberately.
        # `before_model` genuinely has something to say — a model call is
        # about to take forty seconds. `after_model` does not: it knew only
        # that the line above it had stopped being true, which in `140`'s
        # stack the next line already says.
        events = _drive_hooks_through_a_real_graph(NarrationMiddleware())
        assert len(events) == 1

    def test_lands_on_the_streamed_channel_not_only_the_final_message(self) -> None:
        events = _drive_hooks_through_a_real_graph(NarrationMiddleware())
        reports = [progress_report(e) for e in events]
        assert all(r is not None for r in reports)
        assert [r.message for r in reports] == ["Thinking about the next step."]

    def test_the_after_line_is_declared_silence_not_deleted_code(self) -> None:
        # The `quiet` argument's own rule, applied to one line: a caller who
        # wants an after-line still gets one, so "nothing here narrates" stays
        # a decision on record rather than a hook somebody removed.
        events = _drive_hooks_through_a_real_graph(NarrationMiddleware(after_text="Done."))
        reports = [progress_report(e) for e in events]
        assert [r.message for r in reports if r] == ["Thinking about the next step.", "Done."]

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


def _drive_tool_hook_through_a_real_graph(
    middleware: NarrationMiddleware, *, tool_name: str, result: ToolMessage
) -> list[dict[str, Any]]:
    """Same proof as `_drive_hooks_through_a_real_graph`, for `wrap_tool_call`:
    runs it inside a real LangGraph run and collects what actually landed on
    `stream_mode="custom"` — the channel `api/streaming.py` turns into the
    `progress` SSE frame. A test that only asserts `report_progress` was
    *called* proves the call, not that anything downstream would ever see it;
    this drives the real custom-stream machinery instead, same as the
    model-hook tests above.
    """
    request = ToolCallRequest(
        tool_call={"name": tool_name, "args": {"value": "mongstad"}, "id": "call_abc123"},
        tool=None,
        state={},
        runtime=None,
    )

    order: list[str] = []

    def handler(_req: ToolCallRequest) -> ToolMessage:
        order.append("handler")
        return result

    def node(state: _State, runtime=None):
        order.append("before")
        out = middleware.wrap_tool_call(request, handler)
        assert out is result
        return {"step": state.get("step", 0) + 1}

    graph = StateGraph(_State).add_node("node", node).add_edge(START, "node").add_edge("node", END).compile()

    events: list[dict[str, Any]] = []
    for chunk in graph.stream({"step": 0}, stream_mode="custom"):
        events.append(chunk)
    # The before-line must be emitted (and therefore streamed) ahead of the
    # handler running, not flushed only once the tool has already returned —
    # a before-line that arrives after the call is a log entry, not progress.
    assert order[0] == "before"
    return events


class TestNarrationMiddlewareToolCalls:
    def test_fires_before_and_after(self) -> None:
        result = ToolMessage(content=[{"id": 1}, {"id": 2}], tool_call_id="call_abc123")
        events = _drive_tool_hook_through_a_real_graph(
            NarrationMiddleware(), tool_name="mcp_list_lenses", result=result
        )
        assert len(events) == 2

    def test_before_line_is_derived_from_the_call_known_tool(self) -> None:
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_abc123")
        events = _drive_tool_hook_through_a_real_graph(
            NarrationMiddleware(), tool_name="mcp_list_lenses", result=result
        )
        reports = [progress_report(e) for e in events]
        assert reports[0] is not None
        assert reports[0].message == "Looking up what is available."

    def test_after_line_counts_a_list_result(self) -> None:
        result = ToolMessage(content=[{"id": 1}, {"id": 2}, {"id": 3}], tool_call_id="call_abc123")
        events = _drive_tool_hook_through_a_real_graph(
            NarrationMiddleware(), tool_name="mcp_list_lenses", result=result
        )
        reports = [progress_report(e) for e in events]
        assert reports[1] is not None
        assert reports[1].message == "3 results."

    def test_after_line_reports_no_rows_on_empty_result(self) -> None:
        result = ToolMessage(content=[], tool_call_id="call_abc123")
        events = _drive_tool_hook_through_a_real_graph(
            NarrationMiddleware(), tool_name="mcp_query_chinook", result=result
        )
        reports = [progress_report(e) for e in events]
        assert reports[1] is not None
        assert reports[1].message == "No rows."

    def test_unknown_tool_falls_back_without_printing_its_id(self) -> None:
        result = ToolMessage(content="some free-text answer", tool_call_id="call_abc123")
        events = _drive_tool_hook_through_a_real_graph(
            NarrationMiddleware(), tool_name="totally_novel_mcp_tool_xyz", result=result
        )
        reports = [progress_report(e) for e in events]
        assert reports[0] is not None
        assert reports[0].message == "Calling a tool."
        # An unparseable-shape result (free text) is omitted rather than
        # guessed at, per the honesty clause — only the before-line lands.
        assert len(events) == 1

    def test_no_tool_id_or_internal_name_in_any_emitted_text(self) -> None:
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_abc123")
        events = _drive_tool_hook_through_a_real_graph(
            NarrationMiddleware(), tool_name="mcp_lookup_canonical_value", result=result
        )
        for e in events:
            report = progress_report(e)
            assert report is not None
            text = report.message
            assert "call_abc123" not in text
            assert "mcp_lookup_canonical_value" not in text
            assert "mongstad" not in text

    def test_narrate_off_emits_nothing_for_tools(self) -> None:
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_abc123")
        events = _drive_tool_hook_through_a_real_graph(
            NarrationMiddleware(quiet=True), tool_name="mcp_list_lenses", result=result
        )
        assert events == []

    def test_emitted_lines_stay_a_sane_length(self) -> None:
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_abc123")
        events = _drive_tool_hook_through_a_real_graph(
            NarrationMiddleware(), tool_name="mcp_list_lenses", result=result
        )
        for e in events:
            report = progress_report(e)
            assert report is not None
            assert len(report.message) <= 80


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

    def test_narration_stays_after_screening(self) -> None:
        # The one *hard* ordering constraint, and it is security-sensitive:
        # `injection-screening` runs `before_*` first-to-last and must act on
        # the text before anything else does.
        order = AbstractAgentNode.SLOT_ORDER
        assert order.index("narration") > order.index("injection-screening")

    def test_narration_sits_inside_the_offload_it_has_to_see_through(self) -> None:
        # `launch-readiness/143`, and the reason narration moved off the
        # second slot. `wrap_*` **nests**: the first middleware in the list
        # wraps all the others. Outside `filesystem`, what narration saw of a
        # large tool result was the pointer `OffloadMiddleware` had already
        # substituted, so the one hook that holds a real result was reading
        # another middleware's replacement for it. Later in the list is
        # further *in*.
        order = AbstractAgentNode.SLOT_ORDER
        assert order.index("narration") > order.index("filesystem")


class TestSlotTableNoneSilencing:
    def test_setting_none_removes_rather_than_flattens_a_none(self) -> None:
        table = MiddlewareSlotTable(order=("narration",))
        table.set("narration", "placeholder")
        table.set("narration", None)
        assert table.flatten() == []


class _FakeRuntime:
    """Stands in for `ToolRuntime` — only `.config` is read by the cache."""

    def __init__(self, thread_id: str | None) -> None:
        self.config = {"configurable": {"thread_id": thread_id}} if thread_id else {}


def _call(
    middleware: NarrationMiddleware,
    *,
    tool_name: str,
    args: dict[str, Any],
    thread_id: str | None,
    result: ToolMessage,
) -> tuple[Any, bool]:
    """Invokes `wrap_tool_call` once inside a real graph run (so
    `report_progress` has a stream to write to) and reports whether the
    underlying handler actually ran."""
    request = ToolCallRequest(
        tool_call={"name": tool_name, "args": args, "id": "call_x"},
        tool=None,
        state={},
        runtime=_FakeRuntime(thread_id),
    )
    invoked = {"handler": False}
    captured: dict[str, Any] = {}

    def handler(_req: ToolCallRequest) -> ToolMessage:
        invoked["handler"] = True
        return result

    def node(state: _State, runtime=None):
        captured["out"] = middleware.wrap_tool_call(request, handler)
        return {"step": state.get("step", 0) + 1}

    graph = StateGraph(_State).add_node("node", node).add_edge(START, "node").add_edge("node", END).compile()
    for _ in graph.stream({"step": 0}):
        pass
    return captured["out"], invoked["handler"]


class TestReadThroughCache:
    def test_second_call_same_tool_same_args_same_thread_skips_the_handler(self) -> None:
        mw = NarrationMiddleware(quiet=True)
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_x")
        _, invoked1 = _call(
            mw, tool_name="mcp_list_lenses", args={"domain": "sm"}, thread_id="t1", result=result
        )
        out2, invoked2 = _call(
            mw, tool_name="mcp_list_lenses", args={"domain": "sm"}, thread_id="t1", result=result
        )
        assert invoked1 is True
        assert invoked2 is False
        assert out2 is result

    def test_non_allowlisted_tool_is_always_invoked(self) -> None:
        mw = NarrationMiddleware(quiet=True)
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_x")
        _call(mw, tool_name="mcp_execute_sql", args={"sql": "select 1"}, thread_id="t1", result=result)
        _, invoked2 = _call(
            mw, tool_name="mcp_execute_sql", args={"sql": "select 1"}, thread_id="t1", result=result
        )
        assert invoked2 is True

    def test_differing_arguments_miss(self) -> None:
        mw = NarrationMiddleware(quiet=True)
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_x")
        _call(mw, tool_name="mcp_list_lenses", args={"domain": "sm"}, thread_id="t1", result=result)
        _, invoked2 = _call(
            mw, tool_name="mcp_list_lenses", args={"domain": "gb"}, thread_id="t1", result=result
        )
        assert invoked2 is True

    def test_a_different_thread_misses(self) -> None:
        mw = NarrationMiddleware(quiet=True)
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_x")
        _call(mw, tool_name="mcp_list_lenses", args={"domain": "sm"}, thread_id="t1", result=result)
        _, invoked2 = _call(
            mw, tool_name="mcp_list_lenses", args={"domain": "sm"}, thread_id="t2", result=result
        )
        assert invoked2 is True

    def test_reuse_is_narrated(self) -> None:
        mw = NarrationMiddleware()
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_x")
        request = ToolCallRequest(
            tool_call={"name": "mcp_list_lenses", "args": {"domain": "sm"}, "id": "call_x"},
            tool=None,
            state={},
            runtime=_FakeRuntime("t1"),
        )

        def handler(_req: ToolCallRequest) -> ToolMessage:
            return result

        def node(state: _State, runtime=None):
            middleware_out = mw.wrap_tool_call(request, handler)
            assert middleware_out is result
            return {"step": state.get("step", 0) + 1}

        graph = (
            StateGraph(_State).add_node("node", node).add_edge(START, "node").add_edge("node", END).compile()
        )
        # Prime the cache first.
        for _ in graph.stream({"step": 0}, stream_mode="custom"):
            pass
        events = list(graph.stream({"step": 0}, stream_mode="custom"))
        reports = [progress_report(e) for e in events]
        messages = [r.message for r in reports if r is not None]
        assert "Reusing what I already looked up." in messages
        # A cache hit skips the handler and its normal before/after pair —
        # only the reuse line should have landed.
        assert messages == ["Reusing what I already looked up."]

    def test_no_thread_id_never_caches(self) -> None:
        mw = NarrationMiddleware(quiet=True)
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_x")
        _call(mw, tool_name="mcp_list_lenses", args={"domain": "sm"}, thread_id=None, result=result)
        _, invoked2 = _call(
            mw, tool_name="mcp_list_lenses", args={"domain": "sm"}, thread_id=None, result=result
        )
        assert invoked2 is True


class TestFindingsInventory:
    """`launch-readiness/106`: the retry-facing read of the same store."""

    def test_empty_thread_returns_nothing(self) -> None:
        mw = NarrationMiddleware(quiet=True)
        assert mw.findings_inventory("t1") == []

    def test_lists_what_was_cached_by_name(self) -> None:
        mw = NarrationMiddleware(quiet=True)
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_x")
        _call(mw, tool_name="mcp_describe_table", args={"table": "dim_vessel"}, thread_id="t1", result=result)
        entries = mw.findings_inventory("t1")
        assert len(entries) == 1
        assert entries[0].startswith("mcp_describe_table(")
        assert "table" in entries[0] and "dim_vessel" in entries[0]

    def test_a_measurement_tool_never_appears(self) -> None:
        """`mcp_execute_sql` is never cached at all (not on the allowlist),
        so it can never be offered back on a retry — the same allowlist that
        keeps it out of the store keeps it out of the inventory."""
        mw = NarrationMiddleware(quiet=True)
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_x")
        _call(mw, tool_name="mcp_execute_sql", args={"sql": "select 1"}, thread_id="t1", result=result)
        assert mw.findings_inventory("t1") == []

    def test_a_different_thread_sees_nothing(self) -> None:
        mw = NarrationMiddleware(quiet=True)
        result = ToolMessage(content=[{"id": 1}], tool_call_id="call_x")
        _call(mw, tool_name="mcp_list_lenses", args={"domain": "sm"}, thread_id="t1", result=result)
        assert mw.findings_inventory("t2") == []


# --------------------------------------------------------------------------- #
# The async twins (`async-first/06`).
#
# Phase D makes `_agent`'s node body `async def`, so the agent it builds is
# reached through `ainvoke` — and LangChain's own guidance is explicit that a
# middleware invoked that way must implement the async hooks: "custom
# middleware must use async hooks. Synchronous hooks remain supported with
# Deep Agents `invoke` and `stream`."
#
# The two halves fail differently, and the quiet one is the dangerous one:
# `awrap_tool_call` has no usable default and raises `NotImplementedError`
# naming the sync method (loud, and it killed the run), while `abefore_model`
# and `aafter_model` default to no-ops — so an un-migrated narration
# middleware on an async agent would have gone **silent**, which is a blank
# panel with a green suite: `launch-readiness/110` exactly.
# --------------------------------------------------------------------------- #


def _drive_hooks_through_an_async_graph(middleware: NarrationMiddleware) -> list[dict[str, Any]]:
    import asyncio

    async def node(state: _State, runtime=None):
        await middleware.abefore_model(state, runtime)
        await middleware.aafter_model(state, runtime)
        return {"step": state.get("step", 0) + 1}

    graph = StateGraph(_State).add_node("node", node).add_edge(START, "node").add_edge("node", END).compile()

    async def collect() -> list[dict[str, Any]]:
        return [chunk async for chunk in graph.astream({"step": 0}, stream_mode="custom")]

    return asyncio.run(collect())


def _drive_tool_hook_through_an_async_graph(
    middleware: NarrationMiddleware, *, tool_name: str, result: ToolMessage
) -> list[dict[str, Any]]:
    import asyncio

    request = ToolCallRequest(
        tool_call={"name": tool_name, "args": {"value": "mongstad"}, "id": "call_abc123"},
        tool=None,
        state={},
        runtime=None,
    )
    order: list[str] = []

    async def handler(_req: ToolCallRequest) -> ToolMessage:
        order.append("handler")
        return result

    async def node(state: _State, runtime=None):
        order.append("before")
        out = await middleware.awrap_tool_call(request, handler)
        assert out is result
        return {"step": state.get("step", 0) + 1}

    graph = StateGraph(_State).add_node("node", node).add_edge(START, "node").add_edge("node", END).compile()

    async def collect() -> list[dict[str, Any]]:
        return [chunk async for chunk in graph.astream({"step": 0}, stream_mode="custom")]

    events = asyncio.run(collect())
    assert order[0] == "before"
    return events


class TestNarrationOnTheAsyncPath:
    def test_the_model_hooks_still_reach_the_custom_channel(self) -> None:
        events = _drive_hooks_through_an_async_graph(NarrationMiddleware())
        reports = [progress_report(e) for e in events]
        assert [r.message for r in reports if r] == ["Thinking about the next step."]

    def test_the_after_line_stays_available_on_the_async_path_too(self) -> None:
        events = _drive_hooks_through_an_async_graph(NarrationMiddleware(after_text="Done."))
        reports = [progress_report(e) for e in events]
        assert [r.message for r in reports if r] == ["Thinking about the next step.", "Done."]

    def test_quiet_is_still_quiet(self) -> None:
        assert _drive_hooks_through_an_async_graph(NarrationMiddleware(quiet=True)) == []

    def test_the_tool_hook_still_narrates(self) -> None:
        result = ToolMessage(content=[{"id": 1}, {"id": 2}], tool_call_id="call_abc123")
        events = _drive_tool_hook_through_an_async_graph(
            NarrationMiddleware(), tool_name="query", result=result
        )
        assert len(events) == 2

    def test_the_read_through_cache_is_the_same_store_on_both_paths(self) -> None:
        """One body, two spellings of the `await`. A second cache reached only
        by one path would make a reuse depend on which door the run came
        through — and `findings_inventory` feeds a retry's prompt."""
        import asyncio

        middleware = NarrationMiddleware()
        request = ToolCallRequest(
            tool_call={"name": "mcp_list_lenses", "args": {}, "id": "c1"},
            tool=None,
            state={},
            runtime=_FakeRuntime("one-thread"),
        )
        calls: list[str] = []

        def sync_handler(_req: ToolCallRequest) -> ToolMessage:
            calls.append("sync")
            return ToolMessage(content="albums", tool_call_id="c1")

        async def async_handler(_req: ToolCallRequest) -> ToolMessage:
            calls.append("async")
            return ToolMessage(content="albums", tool_call_id="c1")

        def node(state: _State, runtime=None):
            middleware.wrap_tool_call(request, sync_handler)
            return {"step": 1}

        async def anode(state: _State, runtime=None):
            await middleware.awrap_tool_call(request, async_handler)
            return {"step": 2}

        config = {"configurable": {"thread_id": "one-thread"}}
        sync_graph = (
            StateGraph(_State).add_node("n", node).add_edge(START, "n").add_edge("n", END).compile()
        )
        async_graph = (
            StateGraph(_State).add_node("n", anode).add_edge(START, "n").add_edge("n", END).compile()
        )
        sync_graph.invoke({"step": 0}, config)
        asyncio.run(async_graph.ainvoke({"step": 0}, config))

        # The second call never reached a handler: it was served from the
        # store the first one wrote.
        assert calls == ["sync"]
        assert middleware.findings_inventory("one-thread") == ["mcp_list_lenses"]
