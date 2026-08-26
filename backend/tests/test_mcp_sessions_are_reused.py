"""One handshake per server, not one per tool call.

The defect this pins: `_discover_tools` used to build tools from a
*connection*, and the adapters' tool body then opened a fresh `ClientSession`
— `initialize`, `notifications/initialized`, `tools/list` — before every single
`tools/call`. `prebuilt_mcp`'s own header measured it at ≈0.8 s of every
1.2–1.5 s call and documented it instead of removing it.

These tests are written at the layer the defect lives: they count handshakes
against a fake session factory. A test at the wrapper layer would stay green
against a completely unfixed `_discover_tools`, which is the trap this
repository has paid for before.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from openstategraph import mcp_sessions


class _FakeSession:
    """Counts what a real `ClientSession` would put on the wire."""

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.closed = False

    async def initialize(self) -> Any:
        self._log.append("initialize")
        return object()

    async def list_tools(self, *_args: Any, **_kwargs: Any) -> Any:
        self._log.append("list_tools")
        return object()

    async def call_tool(self, name: str, *_args: Any, **_kwargs: Any) -> Any:
        self._log.append(f"call:{name}")
        return f"result:{name}"


class _Broken(_FakeSession):
    """The pipe dies once, ever — a proxy that timed the connection out.

    The flag is on the *class*, not the instance, because a reconnect makes a
    new session: an instance flag would break every replacement too and the
    test would be asserting an infinite retry loop rather than one retry.
    """

    dead = True

    async def call_tool(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if _Broken.dead:
            _Broken.dead = False
            raise ConnectionResetError("peer closed the connection")
        return await super().call_tool(name, *args, **kwargs)


@pytest.fixture()
def sessions(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A `create_session` that logs, and a pool cleared around the test."""
    log: list[str] = []

    class _Ctx:
        async def __aenter__(self) -> Any:
            log.append("connect")
            return _FakeSession(log)

        async def __aexit__(self, *_exc: Any) -> bool:
            log.append("disconnect")
            return False

    import langchain_mcp_adapters.sessions as vendor_sessions

    monkeypatch.setattr(vendor_sessions, "create_session", lambda *_a, **_k: _Ctx())
    mcp_sessions._POOL.clear()
    yield log
    mcp_sessions._POOL.clear()


class TestOneSessionPerServer:
    def test_many_calls_pay_one_handshake(self, sessions: Any) -> None:
        proxy = mcp_sessions.session_proxy(
            {"url": "https://example.test/mcp", "transport": "streamable_http"}, timeout=5.0
        )

        for index in range(5):
            assert mcp_sessions.run_on_mcp_loop(proxy.call_tool(f"t{index}")) == f"result:t{index}"

        assert sessions.count("connect") == 1
        assert sessions.count("initialize") == 1
        assert [entry for entry in sessions if entry.startswith("call:")] == [
            f"call:t{index}" for index in range(5)
        ]

    def test_two_cards_naming_one_server_share_it(self, sessions: Any) -> None:
        connection = {"url": "https://example.test/mcp", "transport": "streamable_http"}
        first = mcp_sessions.session_proxy(connection, timeout=5.0)
        second = mcp_sessions.session_proxy(dict(connection), timeout=5.0)

        assert first is second
        mcp_sessions.run_on_mcp_loop(first.call_tool("a"))
        mcp_sessions.run_on_mcp_loop(second.call_tool("b"))
        assert sessions.count("initialize") == 1

    def test_two_servers_are_two_sessions(self, sessions: Any) -> None:
        one = mcp_sessions.session_proxy(
            {"url": "https://one.test/mcp", "transport": "streamable_http"}, timeout=5.0
        )
        two = mcp_sessions.session_proxy(
            {"url": "https://two.test/mcp", "transport": "streamable_http"}, timeout=5.0
        )
        assert one is not two
        mcp_sessions.run_on_mcp_loop(one.call_tool("a"))
        mcp_sessions.run_on_mcp_loop(two.call_tool("b"))
        assert sessions.count("initialize") == 2

    def test_an_async_caller_is_not_blocked_and_shares_the_session(
        self, sessions: Any
    ) -> None:
        """The async entry point reaches the same session from a different loop."""
        proxy = mcp_sessions.session_proxy(
            {"url": "https://example.test/mcp", "transport": "streamable_http"}, timeout=5.0
        )

        async def caller() -> list[Any]:
            return await asyncio.gather(
                *(mcp_sessions.run_on_mcp_loop_async(proxy.call_tool(f"t{i}")) for i in range(4))
            )

        assert sorted(asyncio.run(caller())) == [f"result:t{i}" for i in range(4)]
        assert sessions.count("initialize") == 1


class TestReconnect:
    def test_a_broken_pipe_reconnects_once(
        self, sessions: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import langchain_mcp_adapters.sessions as vendor_sessions

        class _Ctx:
            async def __aenter__(self) -> Any:
                sessions.append("connect")
                return _Broken(sessions)

            async def __aexit__(self, *_exc: Any) -> bool:
                return False

        _Broken.dead = True
        monkeypatch.setattr(vendor_sessions, "create_session", lambda *_a, **_k: _Ctx())
        proxy = mcp_sessions.session_proxy(
            {"url": "https://flaky.test/mcp", "transport": "streamable_http"}, timeout=5.0
        )

        assert mcp_sessions.run_on_mcp_loop(proxy.call_tool("a")) == "result:a"
        assert sessions.count("connect") == 2

    def test_a_protocol_error_is_not_retried(
        self, sessions: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bad argument must fail once. A silent second call doubles it."""
        import langchain_mcp_adapters.sessions as vendor_sessions

        calls: list[str] = []

        class _Rejecting(_FakeSession):
            async def call_tool(self, name: str, *_a: Any, **_k: Any) -> Any:
                calls.append(name)
                raise ValueError("unknown argument")

        class _Ctx:
            async def __aenter__(self) -> Any:
                return _Rejecting(sessions)

            async def __aexit__(self, *_exc: Any) -> bool:
                return False

        monkeypatch.setattr(vendor_sessions, "create_session", lambda *_a, **_k: _Ctx())
        proxy = mcp_sessions.session_proxy(
            {"url": "https://strict.test/mcp", "transport": "streamable_http"}, timeout=5.0
        )

        with pytest.raises(ValueError):
            mcp_sessions.run_on_mcp_loop(proxy.call_tool("a"))
        assert calls == ["a"]


class TestTheKeyCarriesNoCredential:
    def test_a_token_value_never_reaches_the_pool_key(self) -> None:
        key = mcp_sessions.pool_key(
            {
                "url": "https://example.test/mcp",
                "transport": "streamable_http",
                "headers": {"Authorization": "Bearer sk-do-not-log-me"},
            }
        )
        assert "sk-do-not-log-me" not in key
        assert "Authorization" in key

    def test_two_rows_differing_by_header_name_are_two_sessions(self) -> None:
        base = {"url": "https://example.test/mcp", "transport": "streamable_http"}
        bearer = mcp_sessions.pool_key({**base, "headers": {"Authorization": "x"}})
        custom = mcp_sessions.pool_key({**base, "headers": {"LANGSMITH-API-KEY": "x"}})
        assert bearer != custom


class TestTheAtomUsesASession:
    def test_discovery_hands_the_adapters_a_session_not_a_connection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fix, at the layer it lives. A connection here is the defect."""
        from openstategraph import prebuilt_mcp

        seen: dict[str, Any] = {}

        async def fake_load(session: Any, **kwargs: Any) -> list[Any]:
            seen["session"] = session
            seen["connection"] = kwargs.get("connection")
            return []

        import langchain_mcp_adapters.tools as vendor_tools

        monkeypatch.setattr(vendor_tools, "load_mcp_tools", fake_load)
        mcp_sessions._POOL.clear()

        definition = prebuilt_mcp.McpServerDefinition(
            name="docs", url="https://example.test/mcp"
        )
        asyncio.run(prebuilt_mcp._discover_tools(definition, {}, timeout=5.0))

        assert isinstance(seen["session"], mcp_sessions.McpSessionProxy)
        assert seen["connection"] is None
        mcp_sessions._POOL.clear()
