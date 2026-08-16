"""The provider set is open: registered, never enumerated (ticket 02).

Three things are pinned here, and they are the three that were hardcoded
before: which providers exist at all, which environment variables count as
credentials, and which extra a model-string prefix belongs to. Every one of
them now derives from a single catalogue that a third party can contribute to
with a `pyproject.toml` stanza and no fork.
"""

from __future__ import annotations

import importlib.metadata
import inspect
from typing import Any

import pytest

from openstategraph.extensions import reset_entry_point_cache
from openstategraph.providers import (
    PROVIDERS_GROUP,
    ProviderCatalogue,
    ProviderEnvironment,
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
        """A keyless provider registered early must not shadow a later one.

        Order alone would let a keyless fallback win simply by being earlier,
        which would make a third-party provider unreachable by default no
        matter how it is configured. No *built-in* is keyless since
        providers-and-credentials ticket 02, but a plugin may still declare
        `env_vars=()`, so the two-pass rule in `default_spec` still earns its
        place — this test now covers a plugin rather than Ollama.
        """
        from openstategraph.api.model_resolution import resolve_model

        install(
            monkeypatch,
            # Registers *first*, and needs no key — the shadowing risk.
            FakeEntryPoint(
                "aardvark",
                ProviderSpec(
                    name="aardvark",
                    default_model="aardvark-1",
                    extra="aardvark",
                    env_vars=(),
                ),
            ),
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
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nv")
        assert resolve_model(None) == "nvidia:meta/llama-3.3-70b-instruct"


class TestTheSpecIsARecordAndTheEnvironmentIsNot:
    """Install-experience 20, pinned as a property rather than as a count.

    `ProviderSpec` is a `frozen=True` dataclass, and six of its members used to
    read `os.environ` or call `importlib.util.find_spec`. A record that reaches
    the machine is not a record: it cannot be exercised without arranging an
    environment, and it answers two questions with different reasons to change
    — *what is this vendor* moves when a vendor does, *can I call it from here*
    moves when a machine does.

    The member count is guarded by `test_public_surface_ceiling.py`; a count
    can be satisfied by moving one member anywhere. This asserts the thing the
    split was actually for, and it is checkable: the class's own source names
    neither.
    """

    def test_the_spec_reads_no_environment_and_imports_nothing(self) -> None:
        source = inspect.getsource(ProviderSpec)

        assert "os.environ" not in source
        assert "importlib" not in source

    def test_the_environment_is_the_half_that_does(self) -> None:
        source = inspect.getsource(ProviderEnvironment)

        assert "os.environ" in source
        assert "importlib" in source

    def test_an_environment_can_be_stated_rather_than_arranged(self) -> None:
        """The point of the seam, in one assertion.

        No `monkeypatch`, no `setenv`, no fixture: the machine under test is an
        argument. That is what could not be written while these lived on the
        frozen record — `is_configured` took an `env` mapping, but `readiness`
        passed it to `is_configured` and not to `is_installed`, so half the
        answer always came from the process this test happens to run in.
        """
        spec = ProviderSpec(
            name="acme", default_model="acme-1", extra="acme", env_vars=("ACME_API_KEY",)
        )

        assert ProviderEnvironment(spec, {}).is_configured() is False
        assert ProviderEnvironment(spec, {"ACME_API_KEY": "sk-acme"}).is_configured() is True


class TestOllamaHasTwoWaysToBeConfigured:
    """Providers-and-credentials ticket 02.

    Ollama used to declare `env_vars=()` and so was *always* configured. That
    was not keyless, it was **ambient**: it reached the cloud through a local
    daemon signing with `~/.ollama/id_ed25519`, a credential that never passes
    through the environment and cannot be seen, moved or revoked from one.

    It now declares two variables, and `is_configured`'s existing `any()` gives
    the rule for free — either signal is enough:

    - `OLLAMA_HOST` alone — a local or self-hosted daemon owning its own auth.
    - `OLLAMA_API_KEY` alone — the cloud, via `OLLAMA_ENDPOINT`.

    Only "neither" changes behaviour, and that is the case indistinguishable
    from a broken install.
    """

    @pytest.fixture(autouse=True)
    def _no_ambient_ollama(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("OLLAMA_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(name, raising=False)

    def _ollama(self) -> ProviderSpec:
        spec = provider_catalogue().get("ollama")
        assert spec is not None
        return spec

    def _here(self) -> ProviderEnvironment:
        return ProviderEnvironment(self._ollama())

    def test_neither_variable_is_not_configured(self) -> None:
        assert self._here().is_configured() is False

    def test_a_host_alone_is_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Running a local daemon is a legitimate, fully-supported setup."""
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        assert self._here().is_configured() is True

    def test_a_key_alone_is_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", "sk-ollama")
        assert self._here().is_configured() is True

    def test_the_message_names_both_ways_of_fixing_it(self) -> None:
        """Ticket 04: naming only the key sends a daemon user shopping.

        The message named `primary_env_var` alone, which was the same thing as
        "every variable that would work" while each provider had one. Ollama
        having two made it advice to buy a cloud subscription that a developer
        running their own daemon does not need.
        """
        message = self._ollama().missing_key_message()
        assert "OLLAMA_API_KEY or OLLAMA_HOST" in message
        assert message.endswith("in .env (see .env.example).")

    def test_a_single_variable_provider_still_reads_naturally(self) -> None:
        spec = provider_catalogue().get("anthropic")
        assert spec is not None
        assert spec.missing_key_message() == (
            'Provider "anthropic" has no credential — '
            "set ANTHROPIC_API_KEY in .env (see .env.example)."
        )

    def test_an_unconfigured_ollama_now_produces_a_diagnosis(self) -> None:
        """It used to return `None`: a keyless provider cannot lack a key."""
        from openstategraph.providers import missing_key_diagnosis

        assert missing_key_diagnosis("ollama:gpt-oss:120b-cloud") is not None


class TestTheEndpointIsCloudUnlessAHostIsNamed:
    """`OLLAMA_HOST` and `OLLAMA_ENDPOINT` answer different questions.

    Host is *where my Ollama is*; endpoint is *where the cloud is*. They
    coexist, and precedence is just the order of `endpoint_env`.

    The default matters most: with neither set, `ollama.Client` would dial
    `127.0.0.1:11434`. That is how "Ollama means cloud, never local" was being
    violated by omission — no decision was ever made to prefer a local model,
    the SDK's default simply went unexamined.
    """

    @pytest.fixture(autouse=True)
    def _no_ambient_ollama(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("OLLAMA_HOST", "OLLAMA_ENDPOINT"):
            monkeypatch.delenv(name, raising=False)

    def _here(self) -> ProviderEnvironment:
        spec = provider_catalogue().get("ollama")
        assert spec is not None
        return ProviderEnvironment(spec)

    def test_neither_set_means_the_cloud(self) -> None:
        assert self._here().base_url() == "https://ollama.com"

    def test_a_host_wins_over_the_cloud_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        monkeypatch.setenv("OLLAMA_ENDPOINT", "https://ollama.com")
        assert self._here().base_url() == "http://localhost:11434"

    def test_the_endpoint_is_used_when_no_host_is_named(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_ENDPOINT", "https://ollama.example.internal")
        assert self._here().base_url() == "https://ollama.example.internal"

    def test_a_provider_that_declares_none_leaves_the_sdk_alone(self) -> None:
        """Anthropic and OpenAI must be untouched by this mechanism.

        Not favouritism — they already honour their own endpoint variables:
        `ChatOpenAI` reads `OPENAI_BASE_URL`/`OPENAI_API_BASE` and
        `ChatAnthropic` reads `ANTHROPIC_BASE_URL`, both verified against the
        installed packages. Declaring ours as well would be a second spelling
        of a working feature, which is the duplication this catalogue exists to
        prevent. Ollama is the only provider whose SDK *default* is wrong for
        this project.

        So `None` means "pass no `base_url`" and leaves the SDK in charge —
        deliberately different from passing a URL we believe to be its default.
        """
        for name in ("anthropic", "openai"):
            spec = provider_catalogue().get(name)
            assert spec is not None
            assert ProviderEnvironment(spec).base_url() is None
            assert spec.endpoint_env == ()

    def test_the_mechanism_is_open_not_ollama_specific(self) -> None:
        """A plugin gets the same lever, with no change to this module."""
        spec = ProviderSpec(
            name="acme",
            default_model="acme-1",
            extra="acme",
            env_vars=("ACME_API_KEY",),
            endpoint_env=("ACME_BASE_URL",),
            default_endpoint="https://api.acme.test",
        )
        assert ProviderEnvironment(spec, {}).base_url() == "https://api.acme.test"
        assert (
            ProviderEnvironment(spec, {"ACME_BASE_URL": "http://box.local"}).base_url()
            == "http://box.local"
        )


class TestAnyMixOfProvidersWorks:
    """Three vendors, independently configured, in any combination.

    The catalogue has no notion of "the configured provider" — each spec
    answers for itself, so a developer may hold keys for one, two or all
    three, and adding Ollama's credential requirement changes none of that.
    """

    ALL = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in self.ALL:
            monkeypatch.delenv(name, raising=False)

    def test_each_provider_answers_only_for_itself(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        catalogue = provider_catalogue()
        configured = {
            spec.name: ProviderEnvironment(spec).is_configured()
            for spec in catalogue.list()
            if spec.requires_key
        }
        assert configured == {"anthropic": False, "openai": True, "ollama": False}

    def test_registration_order_decides_the_default_among_those_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And only among those configured — an unset vendor is skipped."""
        from openstategraph.api.model_resolution import resolve_model

        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        monkeypatch.setenv("OLLAMA_API_KEY", "sk-ollama")
        # Anthropic registers first but is not configured, so OpenAI wins.
        assert resolve_model(None).startswith("openai:")

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        assert resolve_model(None).startswith("anthropic:")

    def test_every_provider_stays_individually_addressable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A default is a default, not a restriction."""
        from openstategraph.api.model_resolution import resolve_model

        for name in self.ALL:
            monkeypatch.setenv(name, "x")
        assert resolve_model("openai:gpt-4.1-mini") == "openai:gpt-4.1-mini"
        assert resolve_model("anthropic:claude-haiku-4-5") == "anthropic:claude-haiku-4-5"
        assert resolve_model("ollama:gpt-oss:120b-cloud") == "ollama:gpt-oss:120b-cloud"


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
        # These tests are about *selection*, so every provider they select must
        # be configured. Without this they exercise the unconfigured-provider
        # fallback instead, and pass or fail depending on what an earlier test
        # happened to leave in the environment.
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "NVIDIA_API_KEY"):
            monkeypatch.setenv(name, "configured-for-this-test")
        # A real runtime rather than `__new__` plus hand-set attributes — see
        # the same note in `test_config_file.py`.
        runtime = NodeRuntime(model="model<default>")
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
