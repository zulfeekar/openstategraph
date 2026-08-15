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
    KEY_TOOLS,
    KEY_TRANSPORT,
    KEY_URL,
    STATUS_AUTH_REQUIRED,
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
    """A stand-in for the one function in this module that uses a socket."""

    def _discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
        _discover.calls.append((definition, dict(headers), timeout))
        return [FakeAsyncTool(name) for name in names]

    _discover.calls = []
    return _discover


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
        assert McpTool().configure(data).definition == McpTool().configure(data).definition

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
        tool = McpTool().configure({KEY_SERVER: "LangChain docs"})
        assert tool.definition is not None
        assert tool.definition.url == "https://docs.langchain.com/mcp"
        assert tool.definition.transport == TRANSPORT_HTTP

    def test_inline_configuration_needs_no_registered_server(self) -> None:
        tool = McpTool().configure(
            {KEY_SERVER: "", KEY_URL: "https://inline.test/mcp", KEY_TRANSPORT: TRANSPORT_SSE}
        )
        assert tool.definition is not None
        assert tool.definition.url == "https://inline.test/mcp"
        assert tool.definition.transport == TRANSPORT_SSE

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
        tool = McpTool().configure(
            {KEY_SERVER: "", KEY_URL: "https://inline.test/mcp", KEY_TRANSPORT: "websocket"}
        )
        assert tool.definition is not None
        assert tool.definition.transport == TRANSPORT_HTTP


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
        def boom(definition, headers, *, timeout):  # noqa: ANN001, ANN202
            raise ExceptionGroup("tg", [httpx.ConnectError("nodename nor servname provided")])

        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", boom)
        warnings = self._warn(McpTool().configure({KEY_SERVER: "LangChain docs"}))
        assert "could not be reached" in warnings[0]
        assert "https://docs.langchain.com/mcp" in warnings[0]

    def test_2_credential_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("MY_MCP_TOKEN", "nope")

        def boom(definition, headers, *, timeout):  # noqa: ANN001, ANN202
            response = httpx.Response(401, request=httpx.Request("POST", "https://x.test/mcp"))
            raise ExceptionGroup(
                "tg", [httpx.HTTPStatusError("401", request=response.request, response=response)]
            )

        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", boom)
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
        def boom(definition, headers, *, timeout):  # noqa: ANN001, ANN202
            response = httpx.Response(405, request=httpx.Request("POST", "https://x.test/"))
            raise ExceptionGroup(
                "tg", [httpx.HTTPStatusError("405", request=response.request, response=response)]
            )

        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", boom)
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

        def discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
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
        def boom(definition, headers, *, timeout):  # noqa: ANN001, ANN202
            raise RuntimeError("something nobody predicted")

        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", boom)
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


# --------------------------------------------------------------------- #
# Honesty gates that can be tested
# --------------------------------------------------------------------- #


class TestHonestyGates:
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
