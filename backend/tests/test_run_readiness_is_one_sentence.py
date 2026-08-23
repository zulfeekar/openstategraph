"""providers-and-credentials/14 — the CLI and the editor read one sentence.

Measured on a clean-venv wheel install: `openstategraph serve` printed *"no
model provider integration is installed, so every run will fail"* while the
editor's own banner, forty seconds later, said *"workflows run against mock
data"*. Both were wrong to disagree — pressing Run from the editor on that
same install (traced in the browser, not reasoned about) posted to
`/api/runs/stream` and came back a 500 raised from
`resolve_model` -> `NoProviderInstalled`. The mock path is real
(`MockProvider.ts`) but nothing in the shipped editor reaches it any more:
`workbench.engine.run()` — the only caller of the client-side execution
engine — is called from tests alone; the Run button's own comment says why
("Run means run... it no longer starts the in-browser preview engine").
So the CLI's sentence was the true one, and the banner's was a promise the
server cannot keep.

The fix follows `providers-and-credentials/13`'s precedent
(`dotenv.environment_source_note`): one function composes the sentence,
every surface prints it verbatim. Here that function already existed —
`ProviderCatalogue.elected_default().reason` is documented as "the header of
`openstategraph providers`" — the gap was that `/api/providers` never
published it. This test is the pin: if the route's `run_readiness` field and
the CLI's own sentence ever diverge, this goes red before a person reads two
different things again.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app

CREDENTIALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")


def _run_readiness(monkeypatch: pytest.MonkeyPatch) -> str:
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    response = TestClient(create_app()).get("/api/providers")
    assert response.status_code == 200, response.text
    return response.json()["run_readiness"]


class TestTheRouteExposesOneSharedSentence:
    def test_the_envelope_carries_a_run_readiness_sentence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sentence = _run_readiness(monkeypatch)
        assert isinstance(sentence, str)
        assert sentence

    def test_it_is_the_catalogue_s_own_elected_default_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not a second copy — the exact object `openstategraph providers` reads."""
        from openstategraph.providers import provider_catalogue

        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        sentence = _run_readiness(monkeypatch)
        assert sentence == provider_catalogue().elected_default().reason

    def test_on_a_configured_provider_it_says_a_run_will_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-whatever")
        response = TestClient(create_app()).get("/api/providers")
        sentence = response.json()["run_readiness"]
        assert "credential" in sentence
        assert "will fail" not in sentence


class TestOnAnInstallWithNoProviderAtAll:
    """The exact state the ticket was found in: zero integrations importable."""

    def test_the_route_says_a_run_will_fail_never_mock_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.providers import ProviderSpec, reset_provider_catalogue

        monkeypatch.setattr(
            "openstategraph.providers.builtin_specs",
            lambda: (
                ProviderSpec(
                    name="ghost",
                    default_model="spook-1",
                    extra="ghost",
                    integration_module="langchain_ghost_which_is_not_installed",
                ),
            ),
        )
        reset_provider_catalogue()
        try:
            sentence = _run_readiness(monkeypatch)
        finally:
            monkeypatch.undo()
            reset_provider_catalogue()

        assert "every run will fail" in sentence
        assert "mock data" not in sentence

    def test_it_is_the_exact_sentence_the_serve_banner_prints(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The CLI and the editor read the same function, not two spellings.

        `cli.no_provider_warning()` is what `openstategraph serve` prints
        first, on the same install. This asserts they are byte-identical —
        the whole point of ticket 14 — rather than merely similar.
        """
        from openstategraph import cli
        from openstategraph.providers import ProviderSpec, reset_provider_catalogue

        monkeypatch.setattr(
            "openstategraph.providers.builtin_specs",
            lambda: (
                ProviderSpec(
                    name="ghost",
                    default_model="spook-1",
                    extra="ghost",
                    integration_module="langchain_ghost_which_is_not_installed",
                ),
            ),
        )
        reset_provider_catalogue()
        try:
            sentence = _run_readiness(monkeypatch)
            warning = cli.no_provider_warning()
        finally:
            monkeypatch.undo()
            reset_provider_catalogue()

        assert warning is not None
        assert sentence == warning
