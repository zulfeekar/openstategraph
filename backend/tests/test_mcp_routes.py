"""`/api/mcp/*` — what the panel (ticket 03) will call.

No test here reaches a real server: `validate_mcp_server` is replaced. The
one live handshake this feature gets is the smoke recorded in
`.scratch/mcp-connect/tickets/02-the-mcp-picker-atom.md`.

The route this module exists to protect is the *secrets* one. A validate
endpoint is exactly where a credential would be posted if nobody stopped it,
so the schema has no field for one and two tests below say so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from openstategraph.api.main import create_app
from openstategraph.config_file import CONFIG_ENV_VAR, reset_active_config
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


class TestRegistering:
    """`POST`/`DELETE /api/mcp/servers` — the write half ticket 03 added.

    `54497b3` shipped the registry read-only, which was correct for a card
    that only *names* a server and is a panel that cannot add one. Every test
    here points the loader at a temporary file: nothing writes the checkout's
    own `openstategraph.yaml`.
    """

    @pytest.fixture
    def project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "openstategraph.yaml"
        path.write_text("version: 1\n", encoding="utf-8")
        monkeypatch.setenv(CONFIG_ENV_VAR, str(path))
        reset_active_config()
        yield path
        reset_active_config()

    def test_a_saved_server_appears_in_the_list_the_panel_reads(
        self, client: TestClient, project: Path
    ) -> None:
        saved = client.post(
            "/api/mcp/servers",
            json={"name": "Internal docs", "url": "https://mcp.example.test/mcp"},
        )
        assert saved.status_code == 200

        names = {entry["name"]: entry for entry in client.get("/api/mcp/servers").json()}
        assert names["Internal docs"]["origin"] == "project"
        # Adding one has not cost the project the two it started with.
        assert "LangChain docs" in names

    def test_the_response_is_the_whole_list_so_the_panel_needs_no_second_call(
        self, client: TestClient, project: Path
    ) -> None:
        body = client.post(
            "/api/mcp/servers",
            json={"name": "Internal docs", "url": "https://mcp.example.test/mcp"},
        ).json()
        assert {entry["name"] for entry in body} >= {"Internal docs", "LangChain docs"}

    def test_a_pasted_credential_is_refused_with_the_loader_s_own_message(
        self, client: TestClient, project: Path
    ) -> None:
        response = client.post(
            "/api/mcp/servers",
            json={
                "name": "Vendor",
                "url": "https://vendor.test/mcp",
                "auth": {"kind": "bearer", "tokenEnv": "sk-live-abc123"},
            },
        )
        assert response.status_code == 400
        assert "sk-live-abc123" not in project.read_text(encoding="utf-8")

    def test_the_write_schema_has_no_field_a_credential_fits_in(
        self, client: TestClient, project: Path
    ) -> None:
        response = client.post(
            "/api/mcp/servers",
            json={
                "name": "Vendor",
                "url": "https://vendor.test/mcp",
                "auth": {"kind": "bearer", "token": "sk-x"},
            },
        )
        assert response.status_code == 422

    def test_a_project_entry_is_deleted_outright(
        self, client: TestClient, project: Path
    ) -> None:
        client.post(
            "/api/mcp/servers",
            json={"name": "Internal docs", "url": "https://mcp.example.test/mcp"},
        )
        body = client.delete("/api/mcp/servers/Internal docs").json()

        assert "Internal docs" not in {entry["name"] for entry in body}

    def test_a_built_in_default_is_deletable_like_any_other_row(
        self, client: TestClient, project: Path
    ) -> None:
        """A list whose first two rows are the only undeletable ones reads as a bug."""
        body = client.delete("/api/mcp/servers/LangChain docs").json()

        names = {entry["name"] for entry in body}
        assert "LangChain docs" not in names
        assert "LangChain API reference" in names
        assert "enabled: false" in project.read_text(encoding="utf-8")

    def test_deleting_a_name_nobody_registered_is_a_404(
        self, client: TestClient, project: Path
    ) -> None:
        response = client.delete("/api/mcp/servers/Nonesuch")
        assert response.status_code == 404
        assert "Nonesuch" in response.json()["detail"]


class TestABuiltInCanComeBack:
    """mcp-connect ticket 06 — Delete on a `default` row destroyed it, as far
    as any user could tell. It never did: the tombstone is committed and
    commented. These are the two routes that make it reachable.
    """

    @pytest.fixture
    def project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "openstategraph.yaml"
        path.write_text("version: 1\n", encoding="utf-8")
        monkeypatch.setenv(CONFIG_ENV_VAR, str(path))
        reset_active_config()
        yield path
        reset_active_config()

    def test_nothing_is_hidden_before_anything_is_deleted(
        self, client: TestClient, project: Path
    ) -> None:
        assert client.get("/api/mcp/servers/hidden").json()["names"] == []

    def test_a_deleted_default_is_reported_as_hidden(
        self, client: TestClient, project: Path
    ) -> None:
        client.delete("/api/mcp/servers/LangChain docs")

        assert client.get("/api/mcp/servers/hidden").json()["names"] == ["LangChain docs"]

    def test_restoring_puts_it_back_wearing_its_own_badge(
        self, client: TestClient, project: Path
    ) -> None:
        client.delete("/api/mcp/servers/LangChain docs")
        body = client.post("/api/mcp/servers/LangChain docs/restore").json()

        row = next(entry for entry in body if entry["name"] == "LangChain docs")
        # `built-in`, not `project`: re-adding by hand resurrected the server
        # and stamped it a project entry, so the badge said the wrong thing
        # about a server the product ships.
        assert row["origin"] == "built-in"
        assert client.get("/api/mcp/servers/hidden").json()["names"] == []

    def test_restoring_something_that_was_never_hidden_is_a_404(
        self, client: TestClient, project: Path
    ) -> None:
        response = client.post("/api/mcp/servers/LangChain docs/restore")

        assert response.status_code == 404

    def test_hidden_is_a_segment_not_a_server_name(
        self, client: TestClient, project: Path
    ) -> None:
        """The read route sits under the same prefix as the writers. It is a
        GET and they are not, so nothing could shadow it — pinned because the
        next route added here might not be."""
        assert client.get("/api/mcp/servers/hidden").status_code == 200


class TestWhoWouldBreak:
    """A `tool.mcp` card NAMES a server; nothing warned that deleting one
    would break a document that is not open (mcp-connect ticket 06)."""

    @pytest.fixture
    def workflows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        from openstategraph.workflows_root import WORKFLOWS_ROOT_ENV

        root = tmp_path / "workflows"
        root.mkdir()
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(root))
        return root

    @staticmethod
    def _package(root: Path, slug: str, server: str) -> None:
        import json

        directory = root / slug
        directory.mkdir()
        (directory / "workflow.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": slug,
                    "document": {
                        "nodes": [
                            {
                                "id": "mcp-1",
                                "type": "tool.mcp",
                                "data": {"servers": [{"server": server}]},
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_it_names_the_packages_that_would_break(
        self, client: TestClient, workflows: Path
    ) -> None:
        self._package(workflows, "docs-bot", "LangChain docs")
        self._package(workflows, "other-bot", "Something else")

        assert client.get("/api/mcp/servers/LangChain docs/usage").json()["slugs"] == ["docs-bot"]

    def test_a_server_nobody_names_reports_nobody(
        self, client: TestClient, workflows: Path
    ) -> None:
        self._package(workflows, "docs-bot", "LangChain docs")

        assert client.get("/api/mcp/servers/Unused/usage").json()["slugs"] == []

    def test_rubble_on_disk_is_skipped_rather_than_raised(
        self, client: TestClient, workflows: Path
    ) -> None:
        (workflows / "half-written").mkdir()
        (workflows / "broken").mkdir()
        (workflows / "broken" / "workflow.json").write_text("{not json", encoding="utf-8")
        self._package(workflows, "docs-bot", "LangChain docs")

        assert client.get("/api/mcp/servers/LangChain docs/usage").json()["slugs"] == ["docs-bot"]
