"""`/api/mcp/*` — what the panel (ticket 03) will call.

No test here reaches a real server: `validate_mcp_server` is replaced. The
one live handshake this feature gets is the smoke recorded in
`.scratch/mcp-connect/tickets/02-the-mcp-picker-atom.md`.

The route this module exists to protect is the *secrets* one. A validate
endpoint is exactly where a credential would be posted if nobody stopped it,
so the schema has no field for one and two tests below say so.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from openstategraph.api.main import create_app
from openstategraph import prebuilt_mcp
from openstategraph.prebuilt_mcp import (
    STATUS_AUTH_REQUIRED,
    STATUS_LIVE,
    STATUS_UNREACHABLE,
    McpValidation,
)


class _State(TypedDict, total=False):
    question: str
    answer: str


@pytest.fixture
def client() -> TestClient:
    builder = StateGraph(_State)
    builder.add_node("answer", lambda state: {"answer": "hi"})
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    graph = builder.compile()
    return TestClient(create_app(graph_factory=lambda _model: graph))


class TestTheServerList:
    def test_a_new_project_already_has_two_working_servers(self, client: TestClient) -> None:
        body = client.get("/api/mcp/servers").json()
        by_name = {entry["name"]: entry for entry in body}

        assert set(by_name) >= {"LangChain docs", "LangChain API reference"}
        assert by_name["LangChain docs"]["url"] == "https://docs.langchain.com/mcp"
        assert by_name["LangChain docs"]["transport"] == "streamable_http"
        assert by_name["LangChain docs"]["origin"] == "built-in"

    def test_a_keyless_default_reads_as_configured(self, client: TestClient) -> None:
        """Nothing to set, so nothing missing — the panel must not show red."""
        body = client.get("/api/mcp/servers").json()
        docs = next(e for e in body if e["name"] == "LangChain docs")
        assert docs["auth"]["kind"] == "none"
        assert docs["credentialConfigured"] is True

    def test_the_list_never_carries_a_credential(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MY_MCP_TOKEN", "sk-live-never-serialise-me")
        assert "sk-live-never-serialise-me" not in client.get("/api/mcp/servers").text


class TestValidation:
    def _stub(self, monkeypatch: pytest.MonkeyPatch, verdict: McpValidation) -> list[Any]:
        seen: list[Any] = []

        def fake(definition, *, timeout=15.0):  # noqa: ANN001, ANN202
            seen.append(definition)
            return verdict

        monkeypatch.setattr(prebuilt_mcp, "validate_mcp_server", fake)
        return seen

    def test_a_live_server_reports_its_tool_names(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub(
            monkeypatch,
            McpValidation(
                status=STATUS_LIVE,
                message="Docs by LangChain answered with 3 tools.",
                server_name="Docs by LangChain",
                server_version="1.0.0",
                tools=("search_docs_by_lang_chain", "submit_feedback"),
                elapsed_seconds=0.86,
            ),
        )
        body = client.post("/api/mcp/validate", json={"server": "LangChain docs"}).json()

        assert body["status"] == "live"
        assert body["tools"] == ["search_docs_by_lang_chain", "submit_feedback"]
        assert body["serverName"] == "Docs by LangChain"

    def test_a_failure_is_a_verdict_not_an_error_status(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The map's decision: validation *saves* with a badge, never refuses."""
        self._stub(
            monkeypatch,
            McpValidation(status=STATUS_UNREACHABLE, message="Nothing answered at that address."),
        )
        response = client.post(
            "/api/mcp/validate", json={"url": "https://no-such-host.invalid/mcp"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "unreachable"

    def test_an_inline_server_carries_its_transport_and_variable_name(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._stub(
            monkeypatch, McpValidation(status=STATUS_AUTH_REQUIRED, message="rejected")
        )
        client.post(
            "/api/mcp/validate",
            json={
                "url": "https://vendor.test/mcp",
                "transport": "sse",
                "auth": {"kind": "header", "headerName": "X-KEY", "tokenEnv": "VENDOR_TOKEN"},
            },
        )
        definition = seen[0]
        assert definition.transport == "sse"
        assert definition.auth.header_name == "X-KEY"
        assert definition.auth.token_env == "VENDOR_TOKEN"

    def test_an_unknown_transport_falls_back_rather_than_failing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._stub(monkeypatch, McpValidation(status=STATUS_LIVE, message="ok"))
        client.post(
            "/api/mcp/validate", json={"url": "https://vendor.test/mcp", "transport": "websocket"}
        )
        assert seen[0].transport == "streamable_http"

    def test_an_unregistered_name_is_a_client_error_not_unreachable(
        self, client: TestClient
    ) -> None:
        """Answering "unreachable" would send someone to look at a network."""
        response = client.post("/api/mcp/validate", json={"server": "Nonesuch"})
        assert response.status_code == 404
        assert "Nonesuch" in response.json()["detail"]

    def test_naming_neither_a_server_nor_a_url_is_refused(self, client: TestClient) -> None:
        assert client.post("/api/mcp/validate", json={}).status_code == 400


class TestTheSecretsRule:
    def test_the_request_schema_has_no_field_a_credential_fits_in(
        self, client: TestClient
    ) -> None:
        """`extra: forbid`, so an editor cannot invent one either."""
        response = client.post(
            "/api/mcp/validate",
            json={"url": "https://vendor.test/mcp", "auth": {"kind": "bearer", "token": "sk-x"}},
        )
        assert response.status_code == 422

    def test_a_verdict_never_echoes_the_environment_value(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VENDOR_TOKEN", "sk-live-secret-value")

        def fake(definition, *, timeout=15.0):  # noqa: ANN001, ANN202
            return McpValidation(status=STATUS_AUTH_REQUIRED, message="rejected the credential")

        monkeypatch.setattr(prebuilt_mcp, "validate_mcp_server", fake)
        response = client.post(
            "/api/mcp/validate",
            json={
                "url": "https://vendor.test/mcp",
                "auth": {"kind": "bearer", "tokenEnv": "VENDOR_TOKEN"},
            },
        )
        assert "sk-live-secret-value" not in response.text
