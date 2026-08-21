"""The six credential-free cases of the nine-case matrix (providers-and-credentials/03).

Three providers x three states — absent, wrong, valid — is nine cells. Six
need no vendor account: **absent** (empty environment, no network call — the
gate fires on first use) and **wrong** (any non-empty string, a real network
call that 401s). **Valid** needs a real key and is not exercised here; see
`scripts/nine_provider_cases.py --valid <provider>` for a human with one.

This file pins the three **absent** cases only. The three **wrong** cases make
a real outbound call to a vendor on every run, which is not something the
default suite should do (opt-in, per the ticket's own instruction) — they live
in `scripts/nine_provider_cases.py --live`, run by a person, not by CI.

**Properties, never exact text** — `providers-and-credentials/04`'s copy stays
free to change. A message must name a variable someone can set, and must not
leak a vendor stack trace. Nothing here freezes the sentence.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from nine_provider_cases import absent_case, isolated_environment  # noqa: E402

from openstategraph.providers import provider_catalogue  # noqa: E402


@pytest.fixture(autouse=True)
def _real_process_environment_restored():
    """`isolated_environment` restores what it found — this just proves it,
    so a bug in the restore cannot leak into another test's provider election.
    """
    before = {
        name: __import__("os").environ.get(name)
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST", "OLLAMA_ENDPOINT")
    }
    yield
    after = {name: __import__("os").environ.get(name) for name in before}
    assert after == before, "a case leaked an environment change past its own scope"


class TestAbsent:
    """No credential at all. No network call — the message comes straight off
    `provider_readiness`, which is itself pinned by `test_provider_gap.py`.
    This file's job is only to prove the six-case runner reaches it correctly.
    """

    @pytest.mark.parametrize("provider", ["anthropic", "openai", "ollama"])
    def test_names_a_variable_someone_can_set(self, provider: str) -> None:
        result = absent_case(provider)
        assert result.ok, result.notes
        spec = provider_catalogue().get(provider)
        assert any(var in result.message for var in spec.env_vars), result.message

    @pytest.mark.parametrize("provider", ["anthropic", "openai", "ollama"])
    def test_does_not_leak_a_stack_trace(self, provider: str) -> None:
        result = absent_case(provider)
        assert "Traceback" not in result.message
        assert '.py", line' not in result.message

    def test_ollama_absent_means_neither_key_nor_host(self) -> None:
        """`CLAUDE.md`: `OLLAMA_HOST` alone is a legitimate keyless config — a
        daemon someone runs. "Absent" for Ollama is therefore *neither*
        `OLLAMA_API_KEY` nor `OLLAMA_HOST` nor `OLLAMA_ENDPOINT`, not just a
        missing key — the message must offer both routes back in, not just
        the cloud one.
        """
        result = absent_case("ollama")
        assert "OLLAMA_API_KEY" in result.message
        assert "OLLAMA_HOST" in result.message
