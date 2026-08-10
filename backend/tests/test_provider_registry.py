"""The provider set is open: registered, never enumerated (ticket 02).

Three things are pinned here, and they are the three that were hardcoded
before: which providers exist at all, which environment variables count as
credentials, and which extra a model-string prefix belongs to. Every one of
them now derives from a single catalogue that a third party can contribute to
with a `pyproject.toml` stanza and no fork.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any

import pytest

from openstategraph.extensions import reset_entry_point_cache
from openstategraph.providers import (
    PROVIDERS_GROUP,
    ProviderCatalogue,
    ProviderSpec,
    builtin_specs,
    provider_catalogue,
    reset_provider_catalogue,
)


@pytest.fixture(autouse=True)
def _fresh_catalogue():
    """The catalogue is memoised; every test here starts from a clean one."""
    reset_provider_catalogue()
    yield
    reset_provider_catalogue()


class FakeEntryPoint:
    """Mirrors the shape `test_extensions.py` already uses for tools."""

    def __init__(self, name: str, value: Any, group: str = PROVIDERS_GROUP) -> None:
        self.name = name
        self.group = group
        self._value = value
        self.dist = type("D", (), {"name": f"{name}-dist"})()

    def load(self) -> Any:
        return self._value


def install(monkeypatch: pytest.MonkeyPatch, *entry_points: FakeEntryPoint) -> None:
    def fake_entry_points(*, group: str = "") -> list[FakeEntryPoint]:
        return [ep for ep in entry_points if ep.group == group]

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)
    reset_provider_catalogue()
    # Faking installed entry points IS a change to the environment, so it must
    # invalidate the process-lifetime discovery cache in
    # `openstategraph.extensions` — otherwise a test that discovers before it
    # fakes gets the real venv's answer, which is a passing test asserting
    # nothing. `conftest.py` clears the cache *between* tests; this clears it
    # mid-test, where the fake is installed.
    reset_entry_point_cache()


# --------------------------------------------------------------------- #
# The seam itself
# --------------------------------------------------------------------- #


class TestTheGroupIsTheContract:
    def test_group_name_is_pinned(self) -> None:
        """Renaming this un-registers every plugin ever shipped against it."""
        assert PROVIDERS_GROUP == "openstategraph.providers"

    def test_group_is_listed_among_the_seams(self) -> None:
        from openstategraph.extensions import ENTRY_POINT_GROUPS

        assert PROVIDERS_GROUP in ENTRY_POINT_GROUPS


class TestBuiltInsGoThroughTheSameSeam:
    def test_built_ins_are_plain_specs(self) -> None:
        """No privileged type, no privileged field — the proof of openness."""
        for spec in builtin_specs():
            assert type(spec) is ProviderSpec

    def test_the_three_built_ins_are_present(self) -> None:
        names = {spec.name for spec in builtin_specs()}
        assert {"anthropic", "openai", "ollama"} <= names

    def test_registration_is_the_only_path(self) -> None:
        """A catalogue built with nothing registered knows no providers."""
        assert ProviderCatalogue().list() == ()


class TestAThirdPartyNeedsNoFork:
    def test_a_fourth_provider_appears(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = ProviderSpec(
            name="nvidia",
            default_model="meta/llama-3.3-70b-instruct",
            extra="nvidia",
            env_vars=("NVIDIA_API_KEY",),
        )
        install(monkeypatch, FakeEntryPoint("nvidia", spec))
        assert provider_catalogue().get("nvidia") is spec

    def test_a_plugin_may_contribute_several(self, monkeypatch: pytest.MonkeyPatch) -> None:
        specs = [
            ProviderSpec(name="bedrock", default_model="m", extra="bedrock"),
            ProviderSpec(name="together", default_model="m", extra="together"),
        ]
        install(monkeypatch, FakeEntryPoint("acme", specs))
        names = {spec.name for spec in provider_catalogue().list()}
        assert {"bedrock", "together"} <= names

    def test_a_plugin_may_replace_a_built_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Built-in < third-party, the same order `extensions` documents."""
        override = ProviderSpec(
            name="anthropic", default_model="claude-opus-4-5", extra="anthropic",
            env_vars=("ANTHROPIC_API_KEY",),
        )
        install(monkeypatch, FakeEntryPoint("override", override))
        assert provider_catalogue().get("anthropic").default_model == "claude-opus-4-5"

    def test_a_broken_plugin_is_skipped_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Boom:
            group = PROVIDERS_GROUP
            name = "boom"
            dist = None

            def load(self) -> Any:
                raise RuntimeError("no")

        install(monkeypatch, Boom())  # type: ignore[arg-type]
        catalogue = provider_catalogue()
        assert catalogue.get("anthropic") is not None  # the rest survived
        assert any("boom" in w for w in catalogue.warnings)

    def test_a_non_spec_is_refused_by_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install(monkeypatch, FakeEntryPoint("junk", "not-a-spec"))
        assert any("junk" in w for w in provider_catalogue().warnings)


# --------------------------------------------------------------------- #
# Everything that used to be a literal list
# --------------------------------------------------------------------- #


class TestNothingHardcodesAClosedListAnymore:
    def test_credential_names_derive_from_the_catalogue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.model_resolution import accepted_credential_keys

        before = accepted_credential_keys()
        assert "NVIDIA_API_KEY" not in before

        install(
            monkeypatch,
            FakeEntryPoint(
                "nvidia",
                ProviderSpec(
                    name="nvidia", default_model="m", extra="nvidia",
                    env_vars=("NVIDIA_API_KEY",),
                ),
            ),
        )
        assert "NVIDIA_API_KEY" in accepted_credential_keys()

    def test_a_registered_provider_key_is_accepted_from_a_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.model_resolution import apply_credentials

        install(
            monkeypatch,
            FakeEntryPoint(
                "nvidia",
                ProviderSpec(
                    name="nvidia", default_model="m", extra="nvidia",
                    env_vars=("NVIDIA_API_KEY",),
                ),
            ),
        )
        env: dict[str, str] = {}
        assert apply_credentials({"NVIDIA_API_KEY": "nv-1"}, env) == ["NVIDIA_API_KEY"]

    def test_extras_hint_derives_from_the_catalogue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph._extras import provider_extra_hint

        assert provider_extra_hint("nvidia:whatever") is None
        install(
            monkeypatch,
            FakeEntryPoint(
                "nvidia",
                ProviderSpec(name="nvidia", default_model="m", extra="nvidia"),
            ),
        )
        assert provider_extra_hint("nvidia:whatever") == "pip install 'openstategraph[nvidia]'"

    def test_aliases_still_map_to_their_extra(self) -> None:
        from openstategraph._extras import provider_extra_hint

        # The two prefixes that are not provider names in their own right.
        assert provider_extra_hint("claude:x") == "pip install 'openstategraph[anthropic]'"
        assert provider_extra_hint("azure_openai:x") == "pip install 'openstategraph[openai]'"


# --------------------------------------------------------------------- #
# Three providers at once, and a per-node override between them
# --------------------------------------------------------------------- #


class TestThreeProvidersCoexist:
    def test_all_three_configured_at_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from openstategraph.api.model_resolution import resolve_model

        monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
        monkeypatch.setenv("OPENAI_API_KEY", "o")
        monkeypatch.setenv("OLLAMA_API_KEY", "l")

        # Registration order decides which is the *default*…
        assert resolve_model(None).startswith("anthropic:")
        # …and every one of them remains individually addressable.
        assert resolve_model("openai:gpt-4.1-mini") == "openai:gpt-4.1-mini"
        assert resolve_model("ollama:gpt-oss:120b-cloud") == "ollama:gpt-oss:120b-cloud"

    def test_a_keyed_provider_beats_a_keyless_fallback_whatever_the_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ollama registers before any plugin, but must not shadow one.

        Order alone would let the keyless fallback win simply by being
        earlier, which would make a third-party provider unreachable by
        default no matter how it is configured.
        """
        from openstategraph.api.model_resolution import resolve_model

        install(
            monkeypatch,
            FakeEntryPoint(
                "nvidia",
                ProviderSpec(
                    name="nvidia",
                    default_model="meta/llama-3.3-70b-instruct",
                    extra="nvidia",
                    env_vars=("NVIDIA_API_KEY",),
                ),
            ),
        )
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nv")
        assert resolve_model(None) == "nvidia:meta/llama-3.3-70b-instruct"


class TestPerNodeOverridePicksBetweenProviders:
    """The canvas `provider/modelId` selection, resolved in one run.

    `_resolve_model` is the seam a node's own model goes through; this proves
    two nodes in the SAME runtime reach two different providers, which is what
    "mixing providers in one workflow" actually means.
    """

    def _runtime(self, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, dict[str, str]]:
        from openstategraph.compile.node_runtime import NodeRuntime

        seen: dict[str, str] = {}

        def fake_init(key: str, **_: Any) -> str:
            seen[key] = key
            return f"model<{key}>"

        import langchain.chat_models

        monkeypatch.setattr(langchain.chat_models, "init_chat_model", fake_init)
        runtime = NodeRuntime.__new__(NodeRuntime)
        runtime.model = "model<default>"  # type: ignore[attr-defined]
        runtime._model_cache = {}  # type: ignore[attr-defined]
        return runtime, seen

    def test_two_nodes_two_providers_one_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runtime, seen = self._runtime(monkeypatch)
        first = runtime._resolve_model({"model": "anthropic/claude-haiku-4-5"})
        second = runtime._resolve_model({"model": "openai/gpt-4.1-mini"})
        third = runtime._resolve_model({})

        assert first == "model<anthropic:claude-haiku-4-5>"
        assert second == "model<openai:gpt-4.1-mini>"
        assert third == "model<default>"
        assert set(seen) == {"anthropic:claude-haiku-4-5", "openai:gpt-4.1-mini"}

    def test_a_registered_fourth_provider_is_selectable_per_node(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime, seen = self._runtime(monkeypatch)
        assert runtime._resolve_model({"model": "nvidia/meta/llama-3.3-70b-instruct"}) == (
            "model<nvidia:meta/llama-3.3-70b-instruct>"
        )
        assert "nvidia:meta/llama-3.3-70b-instruct" in seen
