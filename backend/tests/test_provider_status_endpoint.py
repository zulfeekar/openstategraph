"""What the *server* is configured for — the-editor-makes-a-real-package t04.

"Models and credentials" told a QA analyst the product "runs offline against
mock data by default" on a server holding three valid keys that had just
answered `144` through two of them. The dialog was not lying about the browser
— the canvas preview really has no keys — it was describing the wrong machine,
and nothing let it describe the right one: `/api/health` answers a single
boolean for *any* provider and there was no per-provider endpoint at all.

**Names and booleans only.** The server never sends key material to a browser,
masked or otherwise. A mask still leaks length, prefix and entropy, and it
would contradict `chat_model.credential_error_from`, which deliberately drops
OpenAI's own `sk-defin****-key` out of its 401 rather than forwarding it.
Naming the *variable* is what a person can act on; a mask of the value is not.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app

CREDENTIALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")


def _providers(client: TestClient) -> list[dict]:
    response = client.get("/api/providers")
    assert response.status_code == 200, response.text
    return response.json()


class TestItReportsWhatTheServerHolds:
    def test_it_lists_every_registered_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        names = {row["name"] for row in _providers(TestClient(create_app()))}
        assert {"anthropic", "openai", "ollama"} <= names

    def test_an_unconfigured_server_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        assert all(not row["configured"] for row in _providers(TestClient(create_app())))

    def test_a_configured_provider_is_reported_as_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-whatever")

        rows = {row["name"]: row for row in _providers(TestClient(create_app()))}
        assert rows["openai"]["configured"] is True
        assert rows["anthropic"]["configured"] is False

    def test_it_names_the_variable_that_did_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The actionable fact. A mask of the value is not one."""
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-whatever")

        rows = {row["name"]: row for row in _providers(TestClient(create_app()))}
        assert rows["openai"]["configured_by"] == "OPENAI_API_KEY"

    def test_ollama_names_whichever_of_its_two_did_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`is_configured` is `any(env_vars)`, so naming the first would lie.

        A developer reaching their own daemon set `OLLAMA_HOST`; telling them
        `OLLAMA_API_KEY` is what configured it sends them looking for a cloud
        key they do not need.
        """
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")

        rows = {row["name"]: row for row in _providers(TestClient(create_app()))}
        assert rows["ollama"]["configured"] is True
        assert rows["ollama"]["configured_by"] == "OLLAMA_HOST"

    def test_an_unconfigured_provider_names_what_would_configure_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        rows = {row["name"]: row for row in _providers(TestClient(create_app()))}
        assert rows["anthropic"]["configured_by"] is None
        assert "ANTHROPIC_API_KEY" in rows["anthropic"]["env_vars"]


class TestItNeverLeaksTheValue:
    def test_no_part_of_a_key_appears_in_the_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not even masked. See the module docstring for why."""
        secret = "sk-supersecretvalue-abcdef123456"
        monkeypatch.setenv("OPENAI_API_KEY", secret)

        body = TestClient(create_app()).get("/api/providers").text
        assert secret not in body
        for fragment in (secret[:8], secret[-8:], "supersecret"):
            assert fragment not in body

    def test_it_reports_names_and_booleans_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-supersecretvalue")
        for row in _providers(TestClient(create_app())):
            for key, value in row.items():
                assert isinstance(value, (str, bool, list, type(None))), (key, value)


class TestTheHint:
    """First two characters, then a fixed mask — the owner's call, twice asked.

    I argued against sending any key material and was overruled, which is
    recorded rather than quietly reversed. What made it defensible to build:

    - **Two characters is very nearly nothing.** Every Anthropic and OpenAI key
      begins `sk`, so the revealed prefix is the part an attacker already knows.
    - **The mask is fixed-width**, so it does not leak the key's *length* —
      which a proportional mask would, and which is real entropy.

    A non-secret variable is shown in full instead: `OLLAMA_HOST` is a URL, and
    masking it would hide the one thing a developer debugging a mount actually
    needs to read.
    """

    def test_a_configured_key_shows_two_characters_and_a_fixed_mask(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-abcdefghijklmnop")
        rows = {r["name"]: r for r in _providers(TestClient(create_app()))}
        assert rows["openai"]["key_hint"] == "sk****"

    def test_the_mask_does_not_reveal_the_length(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-short")
        short = {r["name"]: r for r in _providers(TestClient(create_app()))}["openai"]["key_hint"]
        monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "x" * 200)
        long = {r["name"]: r for r in _providers(TestClient(create_app()))}["openai"]["key_hint"]
        assert short == long

    def test_an_unconfigured_provider_has_no_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        rows = {r["name"]: r for r in _providers(TestClient(create_app()))}
        assert rows["anthropic"]["key_hint"] is None

    def test_a_host_is_not_a_secret_and_is_shown_whole(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Masking a URL hides the one thing worth reading."""
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        rows = {r["name"]: r for r in _providers(TestClient(create_app()))}
        assert rows["ollama"]["key_hint"] == "http://localhost:11434"

    def test_nothing_beyond_the_two_characters_survives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRETBODY-9999")
        body = TestClient(create_app()).get("/api/providers").text
        for fragment in ("SECRETBODY", "9999", "sk-ant"):
            assert fragment not in body


class TestVerifyMakesTheRealCall:
    """`set` is not `valid`, and only a call can tell them apart.

    The day this was written the owner's Anthropic key was set, well-formed,
    and rejected for want of credit. No inspection of the value could have
    known that — which is why "not valid" is never guessed from a key's shape
    and only ever reported after something came back.

    Behind a button, deliberately: it spends money and latency, so it is a
    thing a person asks for rather than something a dialog does on open.
    """

    def test_an_unconfigured_provider_is_refused_without_spending_anything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        body = TestClient(create_app()).post("/api/providers/anthropic/verify").json()

        assert body["ok"] is False
        assert "ANTHROPIC_API_KEY" in body["detail"]

    def test_an_unknown_provider_is_a_404(self) -> None:
        assert TestClient(create_app()).post("/api/providers/nope/verify").status_code == 404

    def test_a_working_provider_reports_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import openstategraph.chat_model as chat_model

        monkeypatch.setenv("OPENAI_API_KEY", "sk-whatever")

        class Fine:
            def invoke(self, _prompt: object) -> object:
                return object()

        monkeypatch.setattr(chat_model, "build_chat_model", lambda _name: Fine())
        body = TestClient(create_app()).post("/api/providers/openai/verify").json()
        assert body["ok"] is True

    def test_a_rejected_key_reports_why_without_a_stack_trace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import openstategraph.chat_model as chat_model

        monkeypatch.setenv("OPENAI_API_KEY", "sk-whatever")

        class Rejects:
            def invoke(self, _prompt: object) -> object:
                raise RuntimeError("Error code: 400 - credit balance is too low")

        monkeypatch.setattr(chat_model, "build_chat_model", lambda _name: Rejects())
        body = TestClient(create_app()).post("/api/providers/openai/verify").json()

        assert body["ok"] is False
        assert "credit balance" in body["detail"]
        assert "Traceback" not in body["detail"]

    def test_the_probe_never_echoes_the_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import openstategraph.chat_model as chat_model

        monkeypatch.setenv("OPENAI_API_KEY", "sk-SECRETVALUE-123")

        class Leaks:
            def invoke(self, _prompt: object) -> object:
                raise RuntimeError("rejected key sk-SECRETVALUE-123")

        monkeypatch.setattr(chat_model, "build_chat_model", lambda _name: Leaks())
        body = TestClient(create_app()).post("/api/providers/openai/verify").text
        assert "SECRETVALUE" not in body
