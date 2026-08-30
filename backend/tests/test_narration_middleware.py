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

import json
from types import SimpleNamespace
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
    def test_the_model_hooks_say_nothing_because_neither_knows_anything(self) -> None:
        # `launch-readiness/143` then `145`. Two lines became one, and then
        # none. `after_model` knew only that the line above it had stopped
        # being true, which in `140`'s stack the next line already says;
        # `before_model` knew nothing at all, and said so identically every
        # lap until it was half the panel. Both are silent by default and
        # both are still *declarable* — see the two tests below.
        assert _drive_hooks_through_a_real_graph(NarrationMiddleware()) == []

    def test_the_before_line_is_declared_silence_not_deleted_code(self) -> None:
        # `launch-readiness/145`. The hook is intact and a caller who wants a
        # line still gets one; what changed is the default. "Nothing here
        # narrates" stays a decision on record rather than a hook somebody
        # removed — the `quiet` argument's own rule, applied to one line.
        events = _drive_hooks_through_a_real_graph(
            NarrationMiddleware(before_text="Thinking about the next step.")
        )
        reports = [progress_report(e) for e in events]
        assert all(r is not None for r in reports)
        assert [r.message for r in reports] == ["Thinking about the next step."]

    def test_the_after_line_is_declared_silence_not_deleted_code(self) -> None:
        events = _drive_hooks_through_a_real_graph(NarrationMiddleware(after_text="Done."))
        reports = [progress_report(e) for e in events]
        assert [r.message for r in reports if r] == ["Done."]

    def test_uses_the_existing_progress_envelope_not_a_second_channel(self) -> None:
        events = _drive_hooks_through_a_real_graph(
            NarrationMiddleware(before_text="Thinking about the next step.")
        )
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
    call_id: str = "call_x",
) -> tuple[Any, bool]:
    """Invokes `wrap_tool_call` once inside a real graph run (so
    `report_progress` has a stream to write to) and reports whether the
    underlying handler actually ran."""
    request = ToolCallRequest(
        tool_call={"name": tool_name, "args": args, "id": call_id},
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

    def test_a_hit_answers_the_call_that_asked_not_the_one_that_first_ran(self) -> None:
        """`launch-readiness/159`. The stored `ToolMessage` carries the *first*
        call's `tool_call_id`; a second call has its own id, and a provider
        refuses a `ToolMessage` that answers a call the preceding `AIMessage`
        never made. The stored `.id` has to go too — `add_messages` dedupes on
        it, which would overwrite the first answer instead of appending this
        one."""
        mw = NarrationMiddleware(quiet=True)
        stored = ToolMessage(content=[{"id": 1}], tool_call_id="call_1", id="msg_1")
        _call(
            mw,
            tool_name="mcp_list_lenses",
            args={"domain": "sm"},
            thread_id="t1",
            result=stored,
            call_id="call_1",
        )
        out2, invoked2 = _call(
            mw,
            tool_name="mcp_list_lenses",
            args={"domain": "sm"},
            thread_id="t1",
            result=stored,
            call_id="call_2",
        )
        assert invoked2 is False
        assert out2.tool_call_id == "call_2"
        assert out2.id is None
        assert out2.content == stored.content
        # The store itself is untouched — a third call must still find the
        # original to re-key, not a copy addressed to the second call.
        assert stored.tool_call_id == "call_1"

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
        events = _drive_hooks_through_an_async_graph(
            NarrationMiddleware(before_text="Thinking about the next step.")
        )
        reports = [progress_report(e) for e in events]
        assert [r.message for r in reports if r] == ["Thinking about the next step."]

    def test_the_two_defaults_are_silent_on_the_async_path_too(self) -> None:
        # `launch-readiness/145`. The async twins delegate to the sync hooks,
        # so this cannot drift — but it went silent once before with both
        # suites green (`110`), and the async default is the half nobody
        # watches.
        assert _drive_hooks_through_an_async_graph(NarrationMiddleware()) == []

    def test_the_after_line_stays_available_on_the_async_path_too(self) -> None:
        events = _drive_hooks_through_an_async_graph(NarrationMiddleware(after_text="Done."))
        reports = [progress_report(e) for e in events]
        assert [r.message for r in reports if r] == ["Done."]

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


class TestOneCallHasOneNarrator:
    """`launch-readiness/145`: the same sentence was being said twice.

    `prebuilt_mcp._wrap_async_tool` reports an MCP call's start from *inside*
    the tool, and this middleware reported it from *around* the tool — the
    identical line, composed from the identical table in
    `abc/tool_sentences.py`. Nobody saw it because every surface collapsed a
    line repeated back to back. `145` stopped the panel doing that, because a
    repeat is evidence (`146`), and a live MCP run then read
    `"Looking up which views of the data are available."` twice in a row.

    The fix is a declaration rather than a filter: a filter cannot tell one
    call announced twice from two calls, which is the whole reason collapsing
    was the wrong answer in the view.
    """

    @staticmethod
    def _drive(*, metadata: Any, result: ToolMessage) -> list[str]:
        request = ToolCallRequest(
            tool_call={"name": "mcp_list_lenses", "args": {}, "id": "call_abc123"},
            tool=SimpleNamespace(metadata=metadata),
            state={},
            runtime=None,
        )
        middleware = build_narration_middleware()

        def handler(_req: ToolCallRequest) -> ToolMessage:
            return result

        def node(state: _State, runtime=None):
            middleware.wrap_tool_call(request, handler)
            return {"step": 1}

        graph = (
            StateGraph(_State)
            .add_node("node", node)
            .add_edge(START, "node")
            .add_edge("node", END)
            .compile()
        )
        events = list(graph.stream({"step": 0}, stream_mode="custom"))
        return [r.message for r in (progress_report(e) for e in events) if r]

    def test_a_tool_that_speaks_for_itself_is_not_announced_twice(self) -> None:
        from openstategraph.progress import NARRATES_ITSELF

        lines = self._drive(
            metadata={NARRATES_ITSELF: True},
            result=ToolMessage(
                content=json.dumps({"ok": True, "data": {"lenses": [1, 2, 3]}}),
                tool_call_id="call_abc123",
            ),
        )
        # The finding survives — it is the one thing only this middleware
        # holds, because only it sees the result.
        assert lines == ["Found 3 views of the data."]

    def test_a_tool_that_says_nothing_is_still_announced(self) -> None:
        lines = self._drive(
            metadata=None,
            result=ToolMessage(
                content=json.dumps({"ok": True, "data": {"lenses": [1, 2, 3]}}),
                tool_call_id="call_abc123",
            ),
        )
        assert lines == [
            "Looking up which views of the data are available.",
            "Found 3 views of the data.",
        ]

    def test_the_declaration_is_one_constant_shared_by_both_sides(self) -> None:
        # A literal in two files is the drift this key exists to prevent.
        from pydantic import BaseModel

        from openstategraph.prebuilt_mcp import _wrap_async_tool
        from openstategraph.progress import NARRATES_ITSELF

        class _Args(BaseModel):
            q: str = ""

        async def _coroutine(**_kwargs: Any) -> Any:
            return ("ok", None)

        wrapped = _wrap_async_tool(
            SimpleNamespace(
                name="mcp_list_lenses",
                description="",
                args_schema=_Args,
                coroutine=_coroutine,
                response_format="content_and_artifact",
                metadata={"server": "lenses"},
            ),
            "lenses",
        )
        assert wrapped.metadata[NARRATES_ITSELF] is True
        # Whatever the original carried is kept, never replaced.
        assert wrapped.metadata["server"] == "lenses"
