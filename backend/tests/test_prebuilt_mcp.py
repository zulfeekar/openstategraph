"""`tool.mcp` — the picker atom (mcp-connect ticket 02).

Nothing here touches the network. The one live run that proves the atom is
the smoke recorded in the ticket; these tests exist so that every *other*
question is answered without a socket, because a test that needs a server is
a test that will one day be skipped.

The six failure sentences of the ticket's dimension 5 each get a test, and
the one that would otherwise be reported as success — a filter naming a tool
the server does not have — gets the loudest one.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager

import httpx
import pytest

from openstategraph import prebuilt_mcp
from openstategraph.prebuilt_mcp import (
    AUTH_BEARER,
    AUTH_HEADER,
    AUTH_NONE,
    DEFAULT_MCP_SERVERS,
    KEY_AUTH_HEADER_NAME,
    KEY_AUTH_KIND,
    KEY_AUTH_TOKEN_ENV,
    KEY_SERVER,
    KEY_SERVERS,
    KEY_TOOLS,
    KEY_TRANSPORT,
    KEY_URL,
    STATUS_AUTH_REQUIRED,
    STATUS_NOT_INSTALLED,
    STATUS_NOT_MCP,
    STATUS_UNREACHABLE,
    TRANSPORT_HTTP,
    TRANSPORT_SSE,
    McpAuth,
    McpServerDefinition,
    McpTool,
    classify_mcp_failure,
    mcp_server_catalogue,
    resolve_auth_headers,
)

# `osg-agent-experience/79`: the remedy is composed for the installation it is
# printed on — `uv tool install --force` repairs a tool install, and a
# pre-release carries index flags — so every assertion below reaches it through
# `install_hint` rather than transcribing it. A literal here would pin one
# machine's answer and be wrong on every other; the command itself is asserted
# where it is composed, `test_the_install_hint_can_be_carried_out.py`.
from openstategraph.install_hint import install_hint


class FakeAsyncTool:
    """What `load_mcp_tools` hands back: a coroutine and no `func`."""

    def __init__(self, name: str, answer: str = "ok") -> None:
        self.name = name
        self.description = f"{name} description"
        self.args_schema = {"type": "object", "properties": {}}
        self.func = None
        self.response_format = "content_and_artifact"
        self.metadata = {"server": "fake"}
        self._answer = answer

    async def coroutine(self, **kwargs: object) -> tuple[str, dict[str, object]]:
        return (self._answer, dict(kwargs))


def fake_discovery(*names: str):
    """A stand-in for the one function in this module that uses a socket.

    A coroutine, because the seam is one since ticket 04: N rows on one card
    are discovered with `asyncio.gather`, so the per-server function has to be
    awaitable for the concurrency to exist at all.
    """

    async def _discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
        _discover.calls.append((definition, dict(headers), timeout))
        return [FakeAsyncTool(name) for name in names]

    _discover.calls = []
    return _discover


def failing_discovery(exc: BaseException):
    """A server that is down, as the library reports one."""

    async def _discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
        raise exc

    return _discover


def per_server_discovery(**by_url: object):
    """Different answers per row — a list of names, or an exception to raise."""

    async def _discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
        answer = by_url[definition.url]
        if isinstance(answer, BaseException):
            raise answer
        return [FakeAsyncTool(name) for name in answer]  # type: ignore[union-attr]

    return _discover


def rows(*servers: dict) -> dict:
    """A `tool.mcp` node's data, as the card writes it: N server rows."""
    return {
        KEY_SERVERS: [{"id": f"r{index}", **row} for index, row in enumerate(servers)]
    }


# --------------------------------------------------------------------- #
# The four canonical assertions (docs/building-an-atom.md)
# --------------------------------------------------------------------- #


class TestTheCanonicalFour:
    def test_happy_path_binds_the_servers_tools(self, monkeypatch) -> None:
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search", "fetch"))
        tool = McpTool().configure({KEY_SERVER: "LangChain docs"})

        bound = tool.as_langchain_tools()

        assert [t.name for t in bound] == ["search", "fetch"]

    def test_configuration_is_deterministic(self) -> None:
        data = {KEY_SERVER: "", KEY_URL: "https://example.test/mcp", KEY_TRANSPORT: TRANSPORT_HTTP}
        assert McpTool().configure(data).bindings == McpTool().configure(data).bindings

    def test_invalid_arguments_come_back_as_data(self) -> None:
        """Inherited from `BaseTool.run`, and asserted so nobody adds a raise."""
        result = McpTool().run(nonsense=1)
        assert not result.ok
        assert result.error

    def test_configure_returns_a_fresh_instance(self) -> None:
        base = McpTool()
        assert base.configure({KEY_SERVER: "LangChain docs"}) is not base


# --------------------------------------------------------------------- #
# Where a definition comes from
# --------------------------------------------------------------------- #


class TestResolvingTheServer:
    def test_a_registered_name_resolves_from_the_catalogue(self) -> None:
        [binding] = McpTool().configure({KEY_SERVER: "LangChain docs"}).bindings
        assert binding.definition is not None
        assert binding.definition.url == "https://docs.langchain.com/mcp"
        assert binding.definition.transport == TRANSPORT_HTTP

    def test_inline_configuration_needs_no_registered_server(self) -> None:
        [binding] = (
            McpTool()
            .configure(
                {KEY_SERVER: "", KEY_URL: "https://inline.test/mcp", KEY_TRANSPORT: TRANSPORT_SSE}
            )
            .bindings
        )
        assert binding.definition is not None
        assert binding.definition.url == "https://inline.test/mcp"
        assert binding.definition.transport == TRANSPORT_SSE

    def test_the_two_defaults_are_seeded_keyless_and_http(self) -> None:
        by_name = {server.name: server for server in DEFAULT_MCP_SERVERS}
        assert set(by_name) == {"LangChain docs", "LangChain API reference"}
        for server in DEFAULT_MCP_SERVERS:
            assert server.transport == TRANSPORT_HTTP
            assert server.auth.kind == AUTH_NONE

    def test_a_project_entry_overrides_a_default_by_name(self) -> None:
        mine = McpServerDefinition(name="LangChain docs", url="https://mirror.test/mcp")
        catalogue = mcp_server_catalogue([mine])
        assert catalogue["LangChain docs"].url == "https://mirror.test/mcp"
        # …and the one it did not name is still present.
        assert "LangChain API reference" in catalogue

    def test_an_unrecognised_transport_falls_back_to_http(self) -> None:
        [binding] = (
            McpTool()
            .configure(
                {KEY_SERVER: "", KEY_URL: "https://inline.test/mcp", KEY_TRANSPORT: "websocket"}
            )
            .bindings
        )
        assert binding.definition is not None
        assert binding.definition.transport == TRANSPORT_HTTP


# --------------------------------------------------------------------- #
# Secrets: the name, never the value
# --------------------------------------------------------------------- #


class TestTheSecretsRule:
    def test_bearer_auth_is_built_from_a_variable_name(self, monkeypatch) -> None:
        monkeypatch.setenv("MY_MCP_TOKEN", "sk-live-abcdef")
        headers, problem = resolve_auth_headers(
            McpAuth(kind=AUTH_BEARER, token_env="MY_MCP_TOKEN"), server_name="s"
        )
        assert problem is None
        assert headers == {"Authorization": "Bearer sk-live-abcdef"}

    def test_a_custom_header_is_built_from_a_variable_name(self, monkeypatch) -> None:
        monkeypatch.setenv("LANGSMITH_KEY", "ls-abc")
        headers, problem = resolve_auth_headers(
            McpAuth(kind=AUTH_HEADER, header_name="LANGSMITH-API-KEY", token_env="LANGSMITH_KEY"),
            server_name="s",
        )
        assert problem is None
        assert headers == {"LANGSMITH-API-KEY": "ls-abc"}

    def test_no_credential_ever_reaches_the_document(self, monkeypatch) -> None:
        """The map's rule, tested rather than asserted in prose.

        A document may name a variable; it may never carry its value. So the
        serialisable state of a configured node, with the variable set to a
        recognisable secret, must not contain that secret anywhere.
        """
        monkeypatch.setenv("MY_MCP_TOKEN", "sk-live-do-not-serialise-me")
        data = {
            KEY_SERVER: "",
            KEY_URL: "https://inline.test/mcp",
            KEY_AUTH_KIND: AUTH_BEARER,
            KEY_AUTH_TOKEN_ENV: "MY_MCP_TOKEN",
        }
        tool = McpTool().configure(data)

        serialised = json.dumps(data) + json.dumps(tool.document_state())
        assert "sk-live-do-not-serialise-me" not in serialised
        assert "MY_MCP_TOKEN" in serialised

    def test_a_token_value_typed_into_the_variable_field_is_refused(self) -> None:
        """The field wants a NAME. Somebody will paste a key into it."""
        tool = McpTool().configure(
            {
                KEY_SERVER: "",
                KEY_URL: "https://inline.test/mcp",
                KEY_AUTH_KIND: AUTH_BEARER,
                KEY_AUTH_TOKEN_ENV: "sk-live-pasted-by-mistake",
            }
        )
        warnings: list[str] = []
        assert tool.as_langchain_tools(warnings=warnings) == []
        assert len(warnings) == 1
        assert "sk-live-pasted-by-mistake" not in warnings[0]
        assert "environment variable holding its credential" in warnings[0]


# --------------------------------------------------------------------- #
# The six failure sentences
# --------------------------------------------------------------------- #


class TestFailureModes:
    def _warn(self, tool: McpTool) -> list[str]:
        warnings: list[str] = []
        assert tool.as_langchain_tools(warnings=warnings) == []
        return warnings

    def test_1_unreachable(self, monkeypatch) -> None:
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            failing_discovery(
                ExceptionGroup("tg", [httpx.ConnectError("nodename nor servname provided")])
            ),
        )
        warnings = self._warn(McpTool().configure({KEY_SERVER: "LangChain docs"}))
        assert "could not be reached" in warnings[0]
        assert "https://docs.langchain.com/mcp" in warnings[0]

    def test_2_credential_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("MY_MCP_TOKEN", "nope")

        response = httpx.Response(401, request=httpx.Request("POST", "https://x.test/mcp"))
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            failing_discovery(
                ExceptionGroup(
                    "tg",
                    [httpx.HTTPStatusError("401", request=response.request, response=response)],
                )
            ),
        )
        warnings = self._warn(
            McpTool().configure(
                {
                    KEY_SERVER: "",
                    KEY_URL: "https://x.test/mcp",
                    KEY_AUTH_KIND: AUTH_BEARER,
                    KEY_AUTH_TOKEN_ENV: "MY_MCP_TOKEN",
                }
            )
        )
        assert "rejected the credential" in warnings[0]
        assert "MY_MCP_TOKEN" in warnings[0]
        assert "nope" not in warnings[0]

    def test_3_does_not_speak_mcp(self, monkeypatch) -> None:
        response = httpx.Response(405, request=httpx.Request("POST", "https://x.test/"))
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            failing_discovery(
                ExceptionGroup(
                    "tg",
                    [httpx.HTTPStatusError("405", request=response.request, response=response)],
                )
            ),
        )
        warnings = self._warn(
            McpTool().configure({KEY_SERVER: "", KEY_URL: "https://x.test/"})
        )
        assert "does not speak MCP" in warnings[0]

    def test_4_the_named_variable_is_not_set(self, monkeypatch) -> None:
        monkeypatch.delenv("ABSENT_MCP_TOKEN", raising=False)
        warnings = self._warn(
            McpTool().configure(
                {
                    KEY_SERVER: "",
                    KEY_URL: "https://x.test/mcp",
                    KEY_AUTH_KIND: AUTH_BEARER,
                    KEY_AUTH_TOKEN_ENV: "ABSENT_MCP_TOKEN",
                }
            )
        )
        assert "ABSENT_MCP_TOKEN" in warnings[0]
        assert "not set in this environment" in warnings[0]

    def test_5_a_filter_naming_a_tool_the_server_does_not_have(self, monkeypatch) -> None:
        """The failure that would otherwise be reported as success."""
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search", "fetch"))
        tool = McpTool().configure(
            {
                KEY_SERVER: "LangChain docs",
                KEY_TOOLS: [{"name": "search"}, {"name": "summarise"}],
            }
        )
        warnings: list[str] = []
        bound = tool.as_langchain_tools(warnings=warnings)

        # It binds what it can — the run is not lost over one bad name…
        assert [t.name for t in bound] == ["search"]
        # …and it says so, which is the whole point of this test.
        assert len(warnings) == 1
        assert "summarise" in warnings[0]
        assert "Bound 1 of the 2 tools" in warnings[0]

    def test_6_a_tool_error_is_content_not_an_exception(self, monkeypatch) -> None:
        """G6: `handle_tool_errors` defaults to True on >=0.3.0.

        Verified live against 0.3.2 (research 01, amendment): a bad argument
        comes back as `MCP error -32602: …` content. The atom must not undo
        that by wrapping the call in something that re-raises.
        """

        class Failing(FakeAsyncTool):
            async def coroutine(self, **kwargs: object) -> tuple[str, dict[str, object]]:
                return ("MCP error -32602: Input validation error", {})

        async def discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
            return [Failing("search")]

        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", discover)
        bound = McpTool().configure({KEY_SERVER: "LangChain docs"}).as_langchain_tools()

        content, _artifact = bound[0].func(query="x")
        assert "MCP error -32602" in content


# --------------------------------------------------------------------- #
# The filter
# --------------------------------------------------------------------- #


class TestTheToolFilter:
    def test_an_absent_filter_means_all_now_and_later(self, monkeypatch) -> None:
        """G7. Storing the resolved list would freeze the server's surface."""
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("a", "b"))
        tool = McpTool().configure({KEY_SERVER: "LangChain docs"})
        assert [t.name for t in tool.as_langchain_tools()] == ["a", "b"]

        # The server grows a tool. The same document binds it, with no edit.
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("a", "b", "c"))
        assert [t.name for t in tool.as_langchain_tools()] == ["a", "b", "c"]

    def test_a_filter_selects_and_preserves_the_servers_order(self, monkeypatch) -> None:
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("a", "b", "c"))
        tool = McpTool().configure(
            {KEY_SERVER: "LangChain docs", KEY_TOOLS: [{"name": "c"}, {"name": "a"}]}
        )
        assert [t.name for t in tool.as_langchain_tools()] == ["a", "c"]

    def test_blank_rows_in_the_filter_are_not_a_filter(self, monkeypatch) -> None:
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("a", "b"))
        tool = McpTool().configure({KEY_SERVER: "LangChain docs", KEY_TOOLS: [{"name": "  "}]})
        warnings: list[str] = []
        assert [t.name for t in tool.as_langchain_tools(warnings=warnings)] == ["a", "b"]
        assert warnings == []


# --------------------------------------------------------------------- #
# N servers on one card (ticket 04)
# --------------------------------------------------------------------- #

DOCS = "https://docs.langchain.com/mcp"
REFERENCE = "https://reference.langchain.com/mcp"


class TestManyServersOnOneCard:
    """One card carries N server rows; they share a consumer, not a fate.

    The ticket's grill settled the trade: N servers on one node lose per-server
    *routing*, and the owner's case — several services, one agent choosing per
    task — is exactly where that costs nothing. What it must not lose is
    *isolation*: three servers behind one card must fail one at a time, and a
    warning nobody can trace to a row is a warning nobody can act on.
    """

    def test_two_rows_bind_both_servers_tools(self, monkeypatch) -> None:
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            per_server_discovery(**{DOCS: ["search_docs"], REFERENCE: ["get_symbol", "list_api"]}),
        )
        tool = McpTool().configure(
            rows({KEY_SERVER: "LangChain docs"}, {KEY_SERVER: "LangChain API reference"})
        )

        warnings: list[str] = []
        bound = tool.as_langchain_tools(warnings=warnings)

        assert [t.name for t in bound] == ["search_docs", "get_symbol", "list_api"]
        assert warnings == []

    def test_a_registry_pick_and_an_inline_url_coexist_on_one_card(self, monkeypatch) -> None:
        """The atom supports both, so a card must not force one style per node."""
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            per_server_discovery(**{DOCS: ["search_docs"], "https://inline.test/mcp": ["ask"]}),
        )
        tool = McpTool().configure(
            rows({KEY_SERVER: "LangChain docs"}, {KEY_URL: "https://inline.test/mcp"})
        )

        assert [t.name for t in tool.as_langchain_tools()] == ["search_docs", "ask"]

    def test_a_sick_row_names_itself_and_the_healthy_rows_still_bind(
        self, monkeypatch
    ) -> None:
        """The ticket's whole point: degrade to a warning naming WHICH row."""
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            per_server_discovery(
                **{
                    DOCS: ["search_docs"],
                    "https://down.test/mcp": ExceptionGroup(
                        "tg", [httpx.ConnectError("All connection attempts failed")]
                    ),
                    REFERENCE: ["get_symbol"],
                }
            ),
        )
        tool = McpTool().configure(
            rows(
                {KEY_SERVER: "LangChain docs"},
                {KEY_URL: "https://down.test/mcp"},
                {KEY_SERVER: "LangChain API reference"},
            )
        )

        warnings: list[str] = []
        bound = tool.as_langchain_tools(warnings=warnings)

        assert [t.name for t in bound] == ["search_docs", "get_symbol"]
        assert len(warnings) == 1
        # WHICH row, in the two ways a developer can look it up: the ordinal
        # they can count down the card, and the server the row names.
        assert "Row 2 of 3" in warnings[0]
        assert "https://down.test/mcp" in warnings[0]

    def test_a_rows_missing_credential_costs_only_that_row(self, monkeypatch) -> None:
        monkeypatch.delenv("ABSENT_MCP_TOKEN", raising=False)
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search_docs"))
        tool = McpTool().configure(
            rows(
                {KEY_SERVER: "LangChain docs"},
                {
                    KEY_URL: "https://vendor.test/mcp",
                    KEY_AUTH_KIND: AUTH_BEARER,
                    KEY_AUTH_TOKEN_ENV: "ABSENT_MCP_TOKEN",
                },
            )
        )

        warnings: list[str] = []
        bound = tool.as_langchain_tools(warnings=warnings)

        assert [t.name for t in bound] == ["search_docs"]
        assert "Row 2 of 2" in warnings[0]
        assert "ABSENT_MCP_TOKEN" in warnings[0]

    def test_a_row_that_names_no_server_at_all_is_the_only_row_that_suffers(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search_docs"))
        tool = McpTool().configure(rows({KEY_SERVER: "LangChain docs"}, {KEY_URL: "  "}))

        warnings: list[str] = []
        assert [t.name for t in tool.as_langchain_tools(warnings=warnings)] == ["search_docs"]
        assert "Row 2 of 2" in warnings[0]

    def test_each_row_filters_its_own_server(self, monkeypatch) -> None:
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            per_server_discovery(
                **{DOCS: ["search_docs", "fetch_page"], REFERENCE: ["get_symbol", "list_api"]}
            ),
        )
        tool = McpTool().configure(
            rows(
                {KEY_SERVER: "LangChain docs", KEY_TOOLS: "search_docs"},
                {KEY_SERVER: "LangChain API reference"},
            )
        )

        # Row 1 is narrowed to one of its two; row 2's empty filter still means
        # every tool that server offers, now and later.
        assert [t.name for t in tool.as_langchain_tools()] == [
            "search_docs",
            "get_symbol",
            "list_api",
        ]

    def test_a_rows_filter_is_one_line_and_the_old_row_list_still_reads(
        self, monkeypatch
    ) -> None:
        """Two containers, one meaning — a row has no room for a sub-table."""
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("a", "b", "c"))

        typed = McpTool().configure(rows({KEY_SERVER: "LangChain docs", KEY_TOOLS: "c, a"}))
        listed = McpTool().configure(
            {KEY_SERVER: "LangChain docs", KEY_TOOLS: [{"name": "c"}, {"name": "a"}]}
        )

        assert [t.name for t in typed.as_langchain_tools()] == ["a", "c"]
        assert [t.name for t in listed.as_langchain_tools()] == ["a", "c"]

    def test_the_rows_are_reached_concurrently_rather_than_one_after_another(
        self, monkeypatch
    ) -> None:
        """`asyncio.gather`, as research 01 measured — not a loop of round trips.

        Proved by deadlock rather than by a clock: each row waits for the other
        to arrive. Run one after the other, the first waits for something that
        has not started and times out, and this test fails with no server, no
        sleep and no flakiness.
        """
        first, second = asyncio.Event(), asyncio.Event()

        async def discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
            here, there = (first, second) if definition.url == DOCS else (second, first)
            here.set()
            await asyncio.wait_for(there.wait(), 2)
            return [FakeAsyncTool(definition.url.rsplit("/", 2)[1])]

        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", discover)
        tool = McpTool().configure(
            rows({KEY_SERVER: "LangChain docs"}, {KEY_SERVER: "LangChain API reference"})
        )

        warnings: list[str] = []
        bound = tool.as_langchain_tools(warnings=warnings)

        assert warnings == [], "a row waited for the one before it to finish"
        assert [t.name for t in bound] == ["docs.langchain.com", "reference.langchain.com"]

    def test_two_rows_offering_the_same_tool_name_bind_once_and_say_so(
        self, monkeypatch
    ) -> None:
        """One card is one namespace, and the model sees names only.

        Silently binding both is the worst option: `ToolNode` keys tools by
        name, so the second would shadow the first with nothing said and an
        agent would call a server nobody chose.
        """
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            per_server_discovery(**{DOCS: ["search"], "https://mirror.test/mcp": ["search"]}),
        )
        tool = McpTool().configure(
            rows({KEY_SERVER: "LangChain docs"}, {KEY_URL: "https://mirror.test/mcp"})
        )

        warnings: list[str] = []
        bound = tool.as_langchain_tools(warnings=warnings)

        assert [t.name for t in bound] == ["search"]
        assert len(warnings) == 1
        assert "search" in warnings[0]
        assert "Row 2 of 2" in warnings[0] and "row 1" in warnings[0]

    def test_a_card_with_no_rows_at_all_says_so_once(self) -> None:
        warnings: list[str] = []
        assert McpTool().configure({KEY_SERVERS: []}).as_langchain_tools(warnings=warnings) == []
        assert len(warnings) == 1
        assert "no servers" in warnings[0].lower()

    def test_a_document_written_before_rows_binds_its_one_server_unchanged(
        self, monkeypatch
    ) -> None:
        """A card's shape changed; a saved workflow did not.

        The flat keys are read as one row rather than migrated, so nothing
        rewrites a committed document to open it — and a single-row card keeps
        the unprefixed sentences, because "Row 1 of 1" tells nobody anything.
        """
        monkeypatch.setattr(
            prebuilt_mcp, "_discover_tools", failing_discovery(httpx.ConnectError("x"))
        )
        tool = McpTool().configure({KEY_SERVER: "LangChain docs"})

        warnings: list[str] = []
        assert tool.as_langchain_tools(warnings=warnings) == []
        assert warnings[0].startswith("MCP server")

    def test_an_old_document_opened_in_a_new_editor_keeps_its_server(
        self, monkeypatch
    ) -> None:
        """The case a fallback keyed on absence would have lost.

        A new card seeds one empty row, so an old workflow opened in a new
        editor carries an empty row list *and* its flat fields. Falling back
        only when the list is missing would bind nothing and blame nobody.
        """
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search_docs"))
        tool = McpTool().configure(
            {
                KEY_SERVERS: [{"id": "mcp1", KEY_SERVER: "", KEY_URL: ""}],
                KEY_SERVER: "LangChain docs",
            }
        )

        assert [t.name for t in tool.as_langchain_tools()] == ["search_docs"]

    def test_no_credential_value_reaches_the_document_however_many_rows(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("ROW_TOKEN", "sk-live-do-not-serialise-me")
        data = rows(
            {KEY_SERVER: "LangChain docs"},
            {
                KEY_URL: "https://vendor.test/mcp",
                KEY_AUTH_KIND: AUTH_BEARER,
                KEY_AUTH_HEADER_NAME: "",
                KEY_AUTH_TOKEN_ENV: "ROW_TOKEN",
            },
        )
        tool = McpTool().configure(data)

        serialised = json.dumps(data) + json.dumps(tool.document_state())
        assert "sk-live-do-not-serialise-me" not in serialised
        assert "ROW_TOKEN" in serialised


# --------------------------------------------------------------------- #
# The sync seam
# --------------------------------------------------------------------- #


class TestTheSyncSeam:
    def test_the_wrapper_carries_both_a_func_and_the_original_coroutine(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search"))
        bound = McpTool().configure({KEY_SERVER: "LangChain docs"}).as_langchain_tools()[0]

        assert bound.func is not None, "no func means NotImplementedError mid-run"
        assert bound.coroutine is not None, "the async path must survive untouched"

    def test_the_wrapper_keeps_content_and_artifact(self, monkeypatch) -> None:
        """A wrapper defaulting to `content` hands the model its own artifact."""
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search"))
        bound = McpTool().configure({KEY_SERVER: "LangChain docs"}).as_langchain_tools()[0]
        assert bound.response_format == "content_and_artifact"

    def test_the_shim_runs_the_coroutine_on_a_thread_with_no_loop(self, monkeypatch) -> None:
        """The seam's whole legality: the graph runs where no loop is running."""
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search"))
        bound = McpTool().configure({KEY_SERVER: "LangChain docs"}).as_langchain_tools()[0]

        async def outer() -> tuple[str, dict[str, object]]:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: bound.func(query="q"))

        content, artifact = asyncio.run(outer())
        assert content == "ok"
        assert artifact == {"query": "q"}


# --------------------------------------------------------------------- #
# The plural seam
# --------------------------------------------------------------------- #


class TestThePluralSeam:
    def test_the_base_contributes_exactly_one_tool(self) -> None:
        """Every existing atom keeps working: singular is plural with one."""
        from openstategraph.prebuilt_web import WEB_TOOLS

        one = WEB_TOOLS[0]
        assert [t.name for t in one.as_langchain_tools()] == [one.as_langchain_tool().name]

    def test_the_singular_seam_refuses_rather_than_guessing(self) -> None:
        """"Which one of my server's tools am I?" has no true answer."""
        refusing = McpTool().as_langchain_tool()
        answer = refusing.func()
        assert "as_langchain_tools" in answer or "contributes" in answer

    def test_binding_never_raises_whatever_the_server_does(self, monkeypatch) -> None:
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            failing_discovery(RuntimeError("something nobody predicted")),
        )
        warnings: list[str] = []
        assert McpTool().configure({KEY_SERVER: "LangChain docs"}).as_langchain_tools(
            warnings=warnings
        ) == []
        assert warnings and "LangChain docs" in warnings[0]


# --------------------------------------------------------------------- #
# Classification — the ExceptionGroup taxonomy, with no socket
# --------------------------------------------------------------------- #


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://x.test/mcp")
    return httpx.HTTPStatusError(
        f"{code}", request=request, response=httpx.Response(code, request=request)
    )


class _Absent:
    """A meta-path finder that makes one package unimportable.

    Returning `None` is the import system's own "I do not have it", so the
    failure raised is the genuine `ModuleNotFoundError` a user without the
    extra gets — not an approximation of it.
    """

    def __init__(self, package: str) -> None:
        self.package = package

    def find_module(self, fullname: str, path: object = None) -> None:  # pragma: no cover - legacy
        return None

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname == self.package or fullname.startswith(f"{self.package}."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


@contextmanager
def _extra_uninstalled(package: str):
    """Stand where a user without `[mcp]` stands, for the length of a `with`."""
    import sys

    cached = {name: mod for name, mod in sys.modules.items() if name.split(".")[0] == package}
    for name in cached:
        del sys.modules[name]
    finder = _Absent(package)
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        sys.modules.update(cached)


class TestClassification:
    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (httpx.ConnectError("nodename nor servname provided"), STATUS_UNREACHABLE),
            (httpx.ConnectError("All connection attempts failed"), STATUS_UNREACHABLE),
            (asyncio.TimeoutError(), STATUS_UNREACHABLE),
            (_status_error(401), STATUS_AUTH_REQUIRED),
            (_status_error(403), STATUS_AUTH_REQUIRED),
            (_status_error(405), STATUS_NOT_MCP),
            (_status_error(404), STATUS_NOT_MCP),
            (_status_error(500), STATUS_NOT_MCP),
            (RuntimeError("handshake went sideways"), STATUS_NOT_MCP),
        ],
    )
    def test_each_cause_lands_on_its_own_status(self, exc: BaseException, expected: str) -> None:
        status, _message = classify_mcp_failure(exc)
        assert status == expected

    def test_an_exception_group_is_unwrapped(self) -> None:
        """Catching `Exception` and printing it gives the developer nothing."""
        wrapped = ExceptionGroup("unhandled errors in a TaskGroup", [_status_error(401)])
        assert classify_mcp_failure(wrapped)[0] == STATUS_AUTH_REQUIRED

    def test_a_nested_exception_group_is_unwrapped_too(self) -> None:
        nested = ExceptionGroup("outer", [ExceptionGroup("inner", [httpx.ConnectError("x")])])
        assert classify_mcp_failure(nested)[0] == STATUS_UNREACHABLE

    def test_a_cause_chain_is_followed(self) -> None:
        outer = RuntimeError("wrapper")
        outer.__cause__ = _status_error(401)
        assert classify_mcp_failure(ExceptionGroup("tg", [outer]))[0] == STATUS_AUTH_REQUIRED

    def test_the_three_messages_stay_three(self) -> None:
        """Two failures sharing a sentence are one failure."""
        messages = {
            classify_mcp_failure(exc)[1]
            for exc in (httpx.ConnectError("x"), _status_error(401), _status_error(405))
        }
        assert len(messages) == 3

    def test_no_message_ever_carries_the_credential(self, monkeypatch) -> None:
        error = _status_error(401)
        error.request.headers["Authorization"] = "Bearer sk-live-secret"
        assert "sk-live-secret" not in classify_mcp_failure(error)[1]


class TestTheExtraIsOurGapNotTheServers:
    """A missing `[mcp]` extra is a local fact, and used to be blamed on the host.

    On `pip install "openstategraph[server,ollama]"` both seeded defaults came
    back *"not an MCP server — Connected, but the MCP handshake failed"* in
    16 ms: false in both halves, and pointing at a machine that was answering
    fine. `ImportError` matched none of the arms, so it fell through the
    terminal line that assumes the socket opened.
    """

    def test_a_missing_module_is_its_own_status(self) -> None:
        status, message = classify_mcp_failure(
            ModuleNotFoundError("No module named 'langchain_mcp_adapters'")
        )
        assert status == STATUS_NOT_INSTALLED
        assert install_hint("mcp") in message

    def test_the_message_never_blames_the_server(self) -> None:
        _status, message = classify_mcp_failure(ModuleNotFoundError("langchain_mcp_adapters"))
        for blame in ("answered", "handshake", "Connected", "that address"):
            assert blame not in message, f"{blame!r} points at the remote host"

    def test_it_survives_the_task_group_wrapper_like_every_other_arm(self) -> None:
        wrapped = ExceptionGroup("unhandled errors in a TaskGroup", [ImportError("mcp")])
        assert classify_mcp_failure(wrapped)[0] == STATUS_NOT_INSTALLED

    def test_validate_says_so_with_the_module_absent(self, monkeypatch) -> None:
        """The panel's answer, reproduced without uninstalling anything.

        The dev environment always has the extra, which is exactly why this
        shipped: an import hook is the only way to have a test stand where the
        user stood.
        """
        with _extra_uninstalled("langchain_mcp_adapters"):
            verdict = prebuilt_mcp.validate_mcp_server(DEFAULT_MCP_SERVERS[0])

        assert verdict.status == STATUS_NOT_INSTALLED
        assert install_hint("mcp") in verdict.message
        assert not verdict.ok

    def test_a_nameless_row_names_its_address_once(self) -> None:
        """Ticket 51's adjacent cosmetic bug, and it is not only cosmetic.

        An inline row has no registered name, so `McpTool.configure` fills the
        name slot with the URL — the only honest identity it has. Every
        sentence below then printed that identity twice:

            MCP server "https://…/mcp" could not be reached at https://…/mcp.

        A reader who meets that sentence in a run's warnings reasonably
        concludes the product has confused two servers, which is exactly the
        wrong doubt to plant in the one message whose whole job is to be
        believed.
        """
        url = "https://qa-not-a-real-host-98765.example.com/mcp"
        inline = McpServerDefinition(name=url, url=url, origin="inline")

        for status in (prebuilt_mcp.STATUS_UNREACHABLE, STATUS_NOT_MCP):
            sentence = prebuilt_mcp._bind_sentence(status, inline)
            assert sentence.count(url) == 1, sentence
            # …and the address is still in there. Deduplicating by dropping
            # the URL would leave a warning nobody could act on.
            assert url in sentence

    def test_a_named_row_still_says_both(self) -> None:
        """The name and the address are two different facts for a registered
        server, and a developer needs both: the name is what they typed into
        `openstategraph.yaml`, the URL is what was actually dialled."""
        named = McpServerDefinition(
            name="LangChain docs", url="https://docs.langchain.com/mcp", origin="project"
        )
        sentence = prebuilt_mcp._bind_sentence(prebuilt_mcp.STATUS_UNREACHABLE, named)

        assert "LangChain docs" in sentence
        assert "https://docs.langchain.com/mcp" in sentence

    def test_the_compile_path_degrades_with_the_same_answer(self) -> None:
        """`_bind_sentence`, not "could not be reached" — a run says one thing."""
        sentence = prebuilt_mcp._bind_sentence(STATUS_NOT_INSTALLED, DEFAULT_MCP_SERVERS[0])
        assert install_hint("mcp") in sentence
        assert "could not be reached" not in sentence

    def test_a_document_binding_a_server_warns_about_the_extra(self) -> None:
        node = McpTool()
        warnings: list[str] = []
        node = node.configure({KEY_SERVER: DEFAULT_MCP_SERVERS[0].name})
        with _extra_uninstalled("langchain_mcp_adapters"):
            bound = node.as_langchain_tools(warnings=warnings)

        assert bound == []
        assert warnings and install_hint("mcp") in warnings[0]


# --------------------------------------------------------------------- #
# Honesty gates that can be tested
# --------------------------------------------------------------------- #


class TestHonestyGates:
    def test_the_extras_table_says_the_extra_is_needed_to_consume_mcp(self) -> None:
        """Every mention used to describe `[mcp]` as us *serving* MCP.

        So a user who wanted MCP tools on an agent — the whole point of this
        module — had no documented reason to install it, and met the panel's
        red badges instead of a sentence.
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        table = (root / "docs" / "what-is-this.md").read_text()
        entry = next(line for line in table.splitlines() if line.startswith("[mcp]"))
        # The description wraps, so take the entry and its continuation lines.
        lines = table.splitlines()
        start = lines.index(entry)
        described = " ".join(
            [entry] + [line for line in lines[start + 1 :] if line.startswith(" " * 8)][:3]
        )
        assert "use" in described, described
        assert "tool.mcp" in described or "panel" in described, described

    def test_gate_8_nothing_in_this_path_can_call_a_model(self) -> None:
        """The card claims latency, not tokens. This is why that is true.

        Read off the import graph rather than the text, so the module's own
        prose about `graph.invoke()` does not fail its own gate — a guard that
        trips on a docstring is a guard people delete.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(prebuilt_mcp))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{alias.name}" for alias in node.names)

        for name in sorted(imported):
            assert "chat_model" not in name, f"{name} can build a model"
            assert not name.startswith("openstategraph.providers"), name
            assert not name.startswith(
                ("langchain_openai", "langchain_anthropic", "langchain_ollama")
            ), name

    def test_gate_3_no_non_finite_number_crosses_the_wire(self) -> None:
        for server in DEFAULT_MCP_SERVERS:
            json.dumps(server.as_payload())  # raises on Infinity/NaN under allow_nan=False
            assert "Infinity" not in json.dumps(server.as_payload(), allow_nan=False)

    def test_gate_7_every_key_the_tool_reads_is_a_declared_field(self) -> None:
        """Checked against the TypeScript schema in test_mcp_field_contract.py.

        Here we only pin that the constants are the literal spellings, so the
        cross-boundary test has something stable to compare against.
        """
        assert (KEY_SERVER, KEY_URL, KEY_TRANSPORT) == ("server", "url", "transport")
        assert (KEY_AUTH_KIND, KEY_AUTH_HEADER_NAME, KEY_AUTH_TOKEN_ENV) == (
            "authKind",
            "authHeaderName",
            "authTokenEnv",
        )
        assert KEY_TOOLS == "tools"
        # The node-level key, added by ticket 04. Everything above became a
        # key *within* a row when the card went plural; this is the only one
        # `defaultsFrom` puts on the node itself.
        assert KEY_SERVERS == "servers"
