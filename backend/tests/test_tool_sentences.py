"""`launch-readiness/112`: narration says what it is doing, not that it is.

The table in `abc/tool_sentences.py` is a pure function, so most of this is
ordinary unit testing. The three properties worth guarding are the ones the
ticket declared non-negotiable: no tool id ever reaches a reader, no model is
ever consulted, and an argument is shown only where somebody declared it safe.
"""

from __future__ import annotations

import inspect
import re

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from openstategraph.abc import tool_sentences
from openstategraph.abc.narration import NarrationMiddleware, build_narration_middleware
from openstategraph.abc.tool_sentences import TOOL_NAMES, describe_tool_call
from openstategraph.progress import progress_report


class TestTheTableCoversThisProjectsToolSurface:
    def test_covers_the_thirteen_mcp_tools_the_server_advertises(self) -> None:
        # Read off a running lens-serving MCP server, and the same 13 the
        # read-through cache's allowlist is sourced from.
        advertised = {
            "mcp_resolve_lens",
            "mcp_list_lenses",
            "mcp_skill_read",
            "mcp_skill_list",
            "mcp_skill_grep",
            "mcp_execute_sql",
            "mcp_fetch_result_page",
            "mcp_describe_lens_tables",
            "mcp_describe_table",
            "mcp_search_tables",
            "mcp_lookup_canonical_value",
            "mcp_lookup_few_shot",
            "mcp_prepare",
        }
        assert advertised <= set(TOOL_NAMES)

    def test_covers_every_built_in_tool_this_repository_ships(self) -> None:
        built_in = {
            "forget_memory",
            "save_memory",
            "search_memory",
            "code_grep",
            "code_ls",
            "code_read",
            "knowledge_lookup",
            "platform_describe_workflow",
            "platform_grep",
            "platform_list_workflows",
            "platform_ls",
            "platform_read_file",
            "send_email",
            "session_identity",
            "sql_get_table_schema",
            "sql_list_tables",
            "sql_query",
            "validate_workflow",
            "web_fetch",
            "web_search",
            "write_topic",
            "youtube_transcript",
        }
        assert built_in <= set(TOOL_NAMES)

    def test_covers_the_deep_agent_harness_stack(self) -> None:
        # `create_deep_agent` pre-assembles these, so every `DeepAgentNode`
        # has them whether or not its author added a tool. Measured on a live
        # MCP run: three of the fourteen lines in one card's stack were
        # `"Calling a tool."`, and all three were these.
        harness = {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "task", "write_todos"}
        assert harness <= set(TOOL_NAMES)

    def test_every_tool_has_a_sentence_that_is_a_sentence(self) -> None:
        for name in TOOL_NAMES:
            sentence = describe_tool_call(name, {})
            assert sentence is not None
            assert sentence[0].isupper(), name
            assert sentence.endswith("."), name
            # The panel's own ceiling — `_MAX_NARRATION_LEN` in `narration.py`.
            assert len(sentence) <= 80, name


class TestATooIsNeverNamedAloud:
    def test_no_sentence_contains_any_tool_id(self) -> None:
        # Word-boundary rather than substring: four of the names are ordinary
        # short words (`ls`, `grep`, `glob`, `task`) and a substring test
        # would be asking whether English contains them, not whether a
        # sentence names a tool.
        for name in TOOL_NAMES:
            sentence = describe_tool_call(name, {})
            assert sentence is not None
            for other in TOOL_NAMES:
                assert re.search(rf"\b{re.escape(other)}\b", sentence) is None, (name, other)

    def test_no_sentence_says_mcp_or_tool(self) -> None:
        for name in TOOL_NAMES:
            sentence = (describe_tool_call(name, {}) or "").lower()
            assert "mcp" not in sentence, name
            assert "tool" not in sentence, name
            assert "lens" not in sentence, name


class TestAnUnknownToolIsSaidToBeUnknown:
    def test_returns_none_rather_than_inventing(self) -> None:
        assert describe_tool_call("totally_novel_mcp_tool_xyz", {}) is None

    def test_an_empty_name_is_unknown(self) -> None:
        assert describe_tool_call("", {}) is None


class TestArgumentsAreDeclaredNeverGuessed:
    def test_a_declared_argument_is_shown(self) -> None:
        assert describe_tool_call("web_search", {"query": "salmon prices"}) == (
            'Searching the web for "salmon prices".'
        )

    def test_a_missing_argument_costs_the_value_and_nothing_else(self) -> None:
        assert describe_tool_call("web_search", {}) == "Searching the web."

    def test_an_undeclared_key_is_ignored_even_when_it_looks_useful(self) -> None:
        # `send_email` declares no argument on purpose: a recipient is
        # personal data and this line is shown to customers.
        assert describe_tool_call("send_email", {"to": "a@example.com"}) == "Sending the email."

    def test_a_recipient_never_appears(self) -> None:
        sentence = describe_tool_call("send_email", {"to": "a@example.com", "subject": "Hi"})
        assert "a@example.com" not in (sentence or "")
        assert "Hi" not in (sentence or "")

    def test_an_over_long_value_is_dropped_never_truncated(self) -> None:
        long = "x" * 200
        sentence = describe_tool_call("web_search", {"query": long})
        assert sentence == "Searching the web."
        assert "…" not in sentence and "..." not in sentence

    def test_a_multi_line_value_is_dropped(self) -> None:
        assert describe_tool_call("sql_query", {"query": "SELECT 1\nFROM t"}) == (
            "Running a query against the database."
        )

    def test_a_non_string_value_is_dropped(self) -> None:
        assert describe_tool_call("code_read", {"path": 7}) == "Reading a file."

    def test_a_blank_value_is_dropped(self) -> None:
        assert describe_tool_call("code_grep", {"pattern": "   "}) == "Searching the code."

    def test_candidate_keys_are_tried_in_order(self) -> None:
        # A published parameter name is not always known for the MCP surface,
        # so several are accepted — tolerant in reading (CLAUDE.md).
        assert describe_tool_call("mcp_search_tables", {"q": "vessel"}) == (
            'Searching the catalogue for tables about "vessel".'
        )
        assert describe_tool_call("mcp_search_tables", {"query": "vessel"}) == (
            'Searching the catalogue for tables about "vessel".'
        )


class TestItIsDeterministicAndCostsNothing:
    def test_the_same_call_always_reads_the_same(self) -> None:
        args = {"table_name": "Invoice"}
        first = describe_tool_call("sql_get_table_schema", args)
        for _ in range(50):
            assert describe_tool_call("sql_get_table_schema", args) == first

    def test_the_module_imports_no_model_and_no_transport(self) -> None:
        # The header's first non-negotiable, asserted rather than asserted in
        # prose: a model asked to narrate leaked its scratchpad once already.
        source = inspect.getsource(tool_sentences)
        for forbidden in ("langchain", "openai", "requests", "httpx", "invoke("):
            assert forbidden not in source


class _State(TypedDict, total=False):
    step: int


def _narrate(middleware: NarrationMiddleware, *, tool_name: str, args: dict) -> list[str]:
    """The before-line as it actually reaches a streaming consumer."""
    request = ToolCallRequest(
        tool_call={"name": tool_name, "args": args, "id": "call_abc123"},
        tool=None,
        state={},
        runtime=None,
    )
    result = ToolMessage(content="text", tool_call_id="call_abc123")

    def node(state: _State, runtime=None):
        middleware.wrap_tool_call(request, lambda _r: result)
        return {"step": 1}

    graph = (
        StateGraph(_State).add_node("node", node).add_edge(START, "node").add_edge("node", END)
    ).compile()
    lines = []
    for chunk in graph.stream({"step": 0}, stream_mode="custom"):
        report = progress_report(chunk)
        if report is not None:
            lines.append(report.message)
    return lines


class TestTheShippedSlotCarriesTheTable:
    def test_the_default_filler_narrates_the_action(self) -> None:
        lines = _narrate(
            build_narration_middleware(),
            tool_name="mcp_list_lenses",
            args={},
        )
        assert lines[0] == "Looking up which views of the data are available."

    def test_the_users_own_word_is_shown_where_a_tool_declares_it(self) -> None:
        # Deliberately the opposite of what the bare class does with the same
        # call: `NarrationMiddleware()` alone cannot tell a user's word from a
        # lens id, so it shows neither. The table knows which parameter this
        # tool canonicalises, and that word is one the user typed.
        lines = _narrate(
            build_narration_middleware(),
            tool_name="mcp_lookup_canonical_value",
            args={"value": "mongstad"},
        )
        assert lines[0] == 'Checking how "mongstad" is spelled in the data.'

    def test_an_unknown_tool_still_gets_the_keyword_floor(self) -> None:
        lines = _narrate(
            build_narration_middleware(),
            tool_name="acme_search_widgets",
            args={},
        )
        assert lines[0] == "Searching the data."

    def test_a_tool_the_floor_cannot_read_either_is_still_generic(self) -> None:
        lines = _narrate(
            build_narration_middleware(),
            tool_name="totally_novel_xyz",
            args={},
        )
        assert lines[0] == "Calling a tool."

    def test_the_bare_class_is_unchanged(self) -> None:
        # The floor is not a fallback that replaced the old behaviour — it IS
        # the old behaviour, and a middleware built without a describer must
        # still be exactly what `launch-readiness/105` shipped.
        lines = _narrate(NarrationMiddleware(), tool_name="mcp_list_lenses", args={})
        assert lines[0] == "Looking up what is available."

    def test_a_describer_that_raises_never_fails_the_run(self) -> None:
        def boom(_name: str, _args: dict) -> str:
            raise RuntimeError("no")

        lines = _narrate(
            NarrationMiddleware(describe=boom), tool_name="mcp_list_lenses", args={}
        )
        assert lines[0] == "Looking up what is available."

    def test_quiet_still_silences_the_sharper_line(self) -> None:
        assert _narrate(build_narration_middleware(quiet=True), tool_name="web_search", args={}) == []


class TestTheSentenceFitsThePanel:
    def test_the_harness_filesystem_never_names_a_path(self) -> None:
        # The defect this caught, live: a customer chat read
        # `Reading /offload/mcp_list_lenses/call_eeR8/3LoOli2BeA5Cqk4p6ik.txt.`
        # A path on the deep-agent filesystem is the harness's own scratch
        # space or this platform's offload envelope — never a value anybody
        # named — so these tools declare no argument at all.
        for name in ("ls", "read_file", "write_file", "edit_file", "glob", "grep"):
            sentence = describe_tool_call(name, {"file_path": "/offload/x/y.txt", "path": "/a/b"})
            assert sentence is not None
            assert "/" not in sentence, (name, sentence)

    def test_a_long_but_legal_value_falls_back_rather_than_overflowing(self) -> None:
        # 55 characters: a usable value by `_MAX_VALUE_LEN`, but it would push
        # this particular sentence past the panel's 80-character ceiling. The
        # bare form is the answer — it says less and all of it is true.
        value = "a" * 55
        sentence = describe_tool_call("mcp_search_tables", {"query": value})
        assert sentence == "Searching the catalogue for a matching table."

    def test_a_value_that_does_fit_is_still_shown(self) -> None:
        assert describe_tool_call("mcp_search_tables", {"query": "vessel"}) == (
            'Searching the catalogue for tables about "vessel".'
        )

    def test_no_sentence_can_exceed_the_ceiling_whatever_the_arguments(self) -> None:
        keys = ("query", "q", "search", "text", "term", "name", "table", "table_name",
                "path", "file", "file_path", "filename", "url", "topic", "value",
                "lens", "skill", "pattern", "glob", "slug", "workflow", "directory",
                "dir", "link", "href", "video_url", "video_id", "question", "title")
        args = {k: "z" * 60 for k in keys}
        for name in TOOL_NAMES:
            sentence = describe_tool_call(name, args)
            assert sentence is not None
            assert len(sentence) <= 80, (name, sentence)
