"""The optional shared-token gate — scale-and-adopt ticket 06.

Two things are being pinned, and they pull in opposite directions:

- **Off by default stays off.** A first run must not need a secret, so the
  absence of `OPENSTATEGRAPH_API_TOKEN` has to leave every route exactly as it
  was. A security feature that changes the default experience is a security
  feature people work around.
- **On means on.** With the token set, *every* route is refused without it —
  including the SSE streams and the editor's own HTML — with `/api/health` the
  single, argued exception.

The cookie half is tested as hard as the header half. It is not a convenience:
without it, enabling the token would break the editor and `/chat`, and a
control that breaks the product is a control that gets switched off.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api import auth
from openstategraph.api.main import create_app

TOKEN = "s3cret-token-value"


@pytest.fixture
def workflows(tmp_path) -> Any:
    """An isolated root, so nothing here reads or writes the real catalogue."""
    root = tmp_path / "workflows"
    root.mkdir()
    return root


@pytest.fixture
def open_client(monkeypatch: pytest.MonkeyPatch, workflows) -> TestClient:
    monkeypatch.delenv(auth.API_TOKEN_ENV, raising=False)
    return TestClient(create_app(workflows_root=workflows))


@pytest.fixture
def gated_client(monkeypatch: pytest.MonkeyPatch, workflows) -> TestClient:
    monkeypatch.setenv(auth.API_TOKEN_ENV, TOKEN)
    return TestClient(create_app(workflows_root=workflows))


class TestOffByDefault:
    def test_no_token_configured_means_no_gate(self, open_client: TestClient) -> None:
        assert open_client.get("/api/workflows").status_code == 200

    def test_an_empty_variable_is_off_not_an_unusable_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(auth.API_TOKEN_ENV, "   ")
        assert auth.configured_token() is None

    def test_no_login_route_exists_when_there_is_nothing_to_log_in_to(
        self, open_client: TestClient
    ) -> None:
        assert open_client.get("/login").status_code == 404


class TestTheGateRefuses:
    def test_an_api_call_without_a_token_is_401(self, gated_client: TestClient) -> None:
        response = gated_client.get("/api/workflows")
        assert response.status_code == 401
        assert "docs/deploying.md" in response.text

    def test_the_challenge_names_the_scheme(self, gated_client: TestClient) -> None:
        """A client told only "401" retries the same wrong way forever."""
        response = gated_client.get("/api/workflows")
        assert response.headers["www-authenticate"].startswith("Bearer")

    def test_a_wrong_token_is_refused(self, gated_client: TestClient) -> None:
        response = gated_client.get(
            "/api/workflows", headers={"authorization": "Bearer not-the-token"}
        )
        assert response.status_code == 401

    def test_a_run_cannot_be_started(self, gated_client: TestClient) -> None:
        """The endpoint that spends the deployer's model budget, specifically."""
        response = gated_client.post("/api/runs", json={"document": {}, "question": "hi"})
        assert response.status_code == 401

    def test_the_event_stream_is_gated_too(self, gated_client: TestClient) -> None:
        """SSE is where a naive `BaseHTTPMiddleware` gate would either leak or
        hang; `/api/events` is the cheapest of the three to assert on."""
        response = gated_client.get("/api/events")
        assert response.status_code == 401

    def test_a_browser_is_sent_to_the_form_rather_than_a_bare_401(
        self, gated_client: TestClient
    ) -> None:
        response = gated_client.get(
            "/chat", headers={"accept": "text/html"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_health_stays_open(self, gated_client: TestClient) -> None:
        """A liveness probe runs before anything has credentials. It answers a
        literal and reads no state, so it leaks nothing the open port did not."""
        assert gated_client.get("/api/health").status_code == 200


class TestTheGateAdmits:
    def test_a_bearer_header_gets_in(self, gated_client: TestClient) -> None:
        response = gated_client.get(
            "/api/workflows", headers={"authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 200

    def test_the_scheme_is_case_insensitive(self, gated_client: TestClient) -> None:
        response = gated_client.get(
            "/api/workflows", headers={"authorization": f"bearer {TOKEN}"}
        )
        assert response.status_code == 200

    def test_the_session_cookie_gets_in(self, gated_client: TestClient) -> None:
        gated_client.cookies.set(auth.SESSION_COOKIE, TOKEN)
        assert gated_client.get("/api/workflows").status_code == 200

    def test_a_header_beats_a_stale_cookie(self, gated_client: TestClient) -> None:
        gated_client.cookies.set(auth.SESSION_COOKIE, "an-old-value")
        response = gated_client.get(
            "/api/workflows", headers={"authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 200


class TestTheLoginForm:
    def test_it_is_served_without_credentials(self, gated_client: TestClient) -> None:
        response = gated_client.get("/login")
        assert response.status_code == 200
        assert "<form" in response.text

    def test_it_is_self_contained(self, gated_client: TestClient) -> None:
        """Served before authentication and possibly with no editor installed,
        so it must not reference the bundle or any other asset."""
        body = gated_client.get("/login").text
        assert "<script" not in body
        assert "/assets/" not in body

    def test_a_wrong_token_is_401_and_re_renders(self, gated_client: TestClient) -> None:
        response = gated_client.post("/login", data={"token": "wrong"})
        assert response.status_code == 401
        assert "<form" in response.text

    def test_the_wrong_token_never_reaches_a_url(self, gated_client: TestClient) -> None:
        """A redirect carrying the value would write the secret into every
        access log between here and the browser."""
        response = gated_client.post(
            "/login", data={"token": "wrong"}, follow_redirects=False
        )
        assert "location" not in response.headers

    def test_the_right_token_sets_a_session_and_redirects(
        self, gated_client: TestClient
    ) -> None:
        response = gated_client.post(
            "/login", data={"token": TOKEN}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        cookie = response.headers["set-cookie"].lower()
        assert auth.SESSION_COOKIE in cookie
        # HttpOnly so an XSS in the editor cannot read it out; SameSite=Strict
        # so no other origin can ride on it, which is what stands in for a CSRF
        # token here.
        assert "httponly" in cookie
        assert "samesite=strict" in cookie

    def test_the_session_then_works(self, gated_client: TestClient) -> None:
        gated_client.post("/login", data={"token": TOKEN}, follow_redirects=False)
        assert gated_client.get("/api/workflows").status_code == 200


class TestCredentialParsing:
    def test_a_missing_credential_is_none(self) -> None:
        assert auth.presented_credential([]) is None

    def test_a_non_bearer_scheme_is_not_a_credential(self) -> None:
        assert auth.presented_credential([(b"authorization", b"Basic abc")]) is None

    def test_one_cookie_among_several_is_found(self) -> None:
        header = f"other=1; {auth.SESSION_COOKIE}={TOKEN}; last=2".encode()
        assert auth.presented_credential([(b"cookie", header)]) == TOKEN

    def test_comparison_is_constant_time(self) -> None:
        """Not observable from outside, so it is pinned by inspection: `matches`
        must go through `hmac.compare_digest`, never `==`."""
        import inspect

        assert "compare_digest" in inspect.getsource(auth.matches)
        assert auth.matches(TOKEN, TOKEN)
        assert not auth.matches(None, TOKEN)
        assert not auth.matches("", TOKEN)


class TestMachineOnlyGate:
    """The shape the MCP transport uses: no form, so no redirect."""

    def test_html_still_gets_401_when_there_is_no_login_path(self) -> None:
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        inner = Starlette(
            routes=[Route("/mcp", lambda _r: PlainTextResponse("ok"))]
        )
        gated = auth.TokenGate(inner, TOKEN, open_paths=(), login_path=None)
        client = TestClient(gated)

        assert client.get("/mcp", headers={"accept": "text/html"}).status_code == 401
        assert (
            client.get("/mcp", headers={"authorization": f"Bearer {TOKEN}"}).status_code
            == 200
        )


class TestTheMcpTransportUsesTheSameSecret:
    """One deployment, one variable. Two secrets would mean one of them unset."""

    def test_streamable_http_is_wrapped_when_a_token_is_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph import mcp_server

        served: list[Any] = []
        monkeypatch.setenv(auth.API_TOKEN_ENV, TOKEN)
        monkeypatch.setattr(
            "uvicorn.run", lambda app, **kwargs: served.append(app), raising=False
        )
        mcp_server._run_gated_http(_StubMcpServer())

        assert isinstance(served[0], auth.TokenGate)

    def test_it_is_machine_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No login form: an MCP client cannot fill one in, so a redirect would
        be an unreadable 303 instead of a 401 it can act on."""
        from openstategraph import mcp_server

        served: list[Any] = []
        monkeypatch.setenv(auth.API_TOKEN_ENV, TOKEN)
        monkeypatch.setattr(
            "uvicorn.run", lambda app, **kwargs: served.append(app), raising=False
        )
        mcp_server._run_gated_http(_StubMcpServer())

        assert served[0]._login_path is None

    def test_without_a_token_it_serves_and_says_so(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unauthenticated stays possible — it is the default and a private
        network is a real deployment — but never silent."""
        import logging

        from openstategraph import mcp_server

        served: list[Any] = []
        monkeypatch.delenv(auth.API_TOKEN_ENV, raising=False)
        monkeypatch.setattr(
            "uvicorn.run", lambda app, **kwargs: served.append(app), raising=False
        )
        with caplog.at_level(logging.WARNING, logger="openstategraph.mcp_server"):
            mcp_server._run_gated_http(_StubMcpServer())

        assert not isinstance(served[0], auth.TokenGate)
        assert "NO authentication" in caplog.text
        assert "model budget" in caplog.text


class _StubMcpServer:
    """The two members `_run_gated_http` touches, and nothing else."""

    class settings:
        host = "127.0.0.1"
        port = 8000

    def streamable_http_app(self) -> Any:
        return object()


class TestExposureWarning:
    def test_loopback_with_no_token_is_silent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Warning a developer on every local run is how a warning becomes
        wallpaper, and wallpaper is what people stop reading."""
        monkeypatch.delenv(auth.API_TOKEN_ENV, raising=False)
        assert auth.exposure_warning("127.0.0.1") is None
        assert auth.exposure_warning("localhost") is None
        assert auth.exposure_warning("::1") is None

    def test_a_public_bind_with_no_token_names_what_it_exposes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(auth.API_TOKEN_ENV, raising=False)
        message = auth.exposure_warning("0.0.0.0")
        assert message is not None
        for expected in ("run your workflows", "model budget", auth.API_TOKEN_ENV):
            assert expected in message

    def test_a_public_bind_with_a_token_is_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(auth.API_TOKEN_ENV, TOKEN)
        assert auth.exposure_warning("0.0.0.0") is None

    def test_an_unresolvable_host_is_assumed_exposed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(auth.API_TOKEN_ENV, raising=False)
        assert auth.exposure_warning("app.internal") is not None
