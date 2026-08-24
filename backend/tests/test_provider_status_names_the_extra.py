"""launch-readiness/28 — the picker must know a model cannot run before a user picks it.

Filed from a stranger install: `openstategraph[server,anthropic]==0.3.0rc3` — one
provider extra. `openstategraph providers` correctly said `openai` "needs its
extra"; `/api/providers` said only `configured: false`, indistinguishable from
"has an extra but no key yet". The editor's picker, reading only `configured`,
listed `gpt-4.1-mini` beside `claude-haiku-4-5` with no marking at all.

The two gaps are not the same fact and must not collapse to one boolean:
a missing **credential** can be supplied by the browser's own credential store
(`ProviderRegistry.setApiKey`) without touching the server. A missing
**package** cannot — no browser key fixes an `ImportError`. So the picker
needs to know which wall it is looking at, and the route is the one place
that already asks `ProviderEnvironment.is_installed()`
(`openstategraph providers`, `_check_providers`) — this test pins that the
same fact reaches `/api/providers` rather than a second guess invented in
TypeScript.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.providers import ProviderSpec, provider_catalogue, reset_provider_catalogue

CREDENTIALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")

#: Registered rather than monkeypatched, same precedent as `test_provider_gap.py`'s
#: GHOST — a real provider whose integration module genuinely does not import.
GHOST = ProviderSpec(
    name="ghost",
    label="Ghost",
    default_model="spook-1",
    extra="ghost",
    env_vars=("GHOST_API_KEY",),
    integration_module="langchain_ghost_which_is_not_installed",
)


@pytest.fixture(autouse=True)
def _fresh_catalogue():
    reset_provider_catalogue()
    yield
    reset_provider_catalogue()


def _providers(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GHOST_API_KEY", raising=False)
    provider_catalogue().register(GHOST)
    response = TestClient(create_app()).get("/api/providers")
    assert response.status_code == 200, response.text
    return {row["name"]: row for row in response.json()["providers"]}


class TestTheRouteNamesAMissingExtra:
    def test_an_uninstalled_integration_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = _providers(monkeypatch)
        assert rows["ghost"]["installed"] is False

    def test_a_real_provider_is_reported_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = _providers(monkeypatch)
        # `openstategraph[anthropic]` is on this checkout's own dependency list.
        assert rows["anthropic"]["installed"] is True

    def test_the_pip_line_is_the_one_the_cli_prints(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = _providers(monkeypatch)
        assert rows["ghost"]["install_hint"] == "pip install 'openstategraph[ghost]'"

    def test_a_row_that_needs_no_credential_still_reports_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The two facts are independent — this must not fold missing-key into it."""
        rows = _providers(monkeypatch)
        assert rows["anthropic"]["installed"] is True
        assert rows["anthropic"]["configured"] is False

    def test_the_bare_extra_name_is_published_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = _providers(monkeypatch)
        assert rows["ghost"]["extra"] == "ghost"
