"""Which origins a browser client may call this API from.

Scale-and-adopt ticket 05. "Build your own UI" was true for a server-side
client and only accidentally true for a browser one: the allowlist was the
editor's Vite dev origin, hard-coded, so anybody's own page was blocked by
CORS with no way to say otherwise short of editing our source.

The allowlist stays **explicit** — this process holds provider keys, and `*`
on a credential-holding API is how a key becomes everyone's. So the escape
hatch adds origins and refuses the wildcard, loudly.
"""

from __future__ import annotations

import pytest

from openstategraph.api.main import ALLOWED_ORIGINS, WildcardOriginError, allowed_origins

DEFAULTS = tuple(ALLOWED_ORIGINS)


class TestTheDefault:
    def test_it_is_the_editor_dev_origin(self) -> None:
        assert allowed_origins({}) == list(DEFAULTS)

    def test_an_empty_variable_changes_nothing(self) -> None:
        assert allowed_origins({"OPENSTATEGRAPH_ALLOWED_ORIGINS": "  "}) == list(DEFAULTS)


class TestTheEscapeHatch:
    def test_it_adds_rather_than_replaces(self) -> None:
        # Adding, not replacing: a developer who lets their own page in should
        # not silently lock the editor's dev server out of the same server.
        origins = allowed_origins(
            {"OPENSTATEGRAPH_ALLOWED_ORIGINS": "https://app.example.com"}
        )
        assert origins[: len(DEFAULTS)] == list(DEFAULTS)
        assert "https://app.example.com" in origins

    def test_it_takes_a_comma_separated_list(self) -> None:
        origins = allowed_origins(
            {"OPENSTATEGRAPH_ALLOWED_ORIGINS": "https://a.example, https://b.example"}
        )
        assert origins[-2:] == ["https://a.example", "https://b.example"]

    def test_it_does_not_repeat_an_origin_already_allowed(self) -> None:
        origins = allowed_origins(
            {"OPENSTATEGRAPH_ALLOWED_ORIGINS": "http://localhost:5273"}
        )
        assert origins == list(DEFAULTS)

    def test_the_wildcard_is_refused(self) -> None:
        # Not ignored — refused. A server that quietly dropped `*` would leave
        # the developer believing their client is allowed until it 403s.
        with pytest.raises(WildcardOriginError):
            allowed_origins({"OPENSTATEGRAPH_ALLOWED_ORIGINS": "*"})

    def test_the_refusal_names_the_variable_and_the_reason(self) -> None:
        with pytest.raises(WildcardOriginError) as exc:
            allowed_origins({"OPENSTATEGRAPH_ALLOWED_ORIGINS": "https://a.example, *"})
        assert "OPENSTATEGRAPH_ALLOWED_ORIGINS" in str(exc.value)


class TestItReachesTheApp:
    def test_a_configured_origin_gets_a_cors_header(self, monkeypatch, tmp_path) -> None:
        from fastapi.testclient import TestClient

        from openstategraph.api.main import create_app

        monkeypatch.setenv("OPENSTATEGRAPH_ALLOWED_ORIGINS", "https://app.example.com")
        client = TestClient(create_app(workflows_root=tmp_path))
        response = client.get("/api/health", headers={"Origin": "https://app.example.com"})
        assert response.headers["access-control-allow-origin"] == "https://app.example.com"

    def test_an_unconfigured_origin_gets_none(self, tmp_path) -> None:
        from fastapi.testclient import TestClient

        from openstategraph.api.main import create_app

        client = TestClient(create_app(workflows_root=tmp_path))
        response = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in response.headers
