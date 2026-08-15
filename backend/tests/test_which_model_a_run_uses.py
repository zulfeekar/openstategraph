"""Which model a run uses when nobody named one — both axes, in one file.

install-experience ticket 03 (wave 1). The design's §1.3 makes the point this
file exists to honour: **two** axes decide the model, and writing them in two
places is how they drift.

- **Axis A — where the request came from.** The instance default, the config
  file, `settings.model`, the node, the caller. Pinned pair by pair in
  `test_config_file.py::TestPrecedence`; what is pinned *here* is the bottom of
  that ladder — how the instance default is elected at all.
- **Axis B — how a model reference is spelled.** `"ollama:"` and `"anthropic"`
  are the same request as `"ollama:gpt-oss:120b-cloud"` and
  `"anthropic:claude-haiku-4-5"`, and until this they reached the vendor SDK
  verbatim (workflow-gallery ticket 12).

Axis B is a precondition for axis A: without a spelling for *"whatever this
install's default is"*, a document's only way to say it is to omit the field.
"""

from __future__ import annotations

import pytest

from openstategraph.errors import NoProviderInstalled, UnknownProvider
from openstategraph.providers import ProviderSpec, provider_catalogue

_AMBIENT = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OLLAMA_API_KEY",
    "OLLAMA_HOST",
    "OPENSTATEGRAPH_ANTHROPIC_MODEL",
    "OPENSTATEGRAPH_OPENAI_MODEL",
    "OPENSTATEGRAPH_OLLAMA_MODEL",
)


@pytest.fixture(autouse=True)
def _no_ambient_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own keys are not part of this file's fixture.

    Every assertion below is about what the *rules* answer, so the machine the
    suite runs on must not be an input to them.
    """
    for name in _AMBIENT:
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------- #
# Axis B — how a model reference is spelled (T1, closes workflow-gallery 12)
# --------------------------------------------------------------------- #


class TestABareProviderPrefixResolvesToItsDefault:
    """`"ollama:"` is a shorthand or it is a lie; until now it was a lie.

    It reached `init_chat_model` verbatim and the run died at the first
    model-driven node with *"String should have at least 1 character"* — as a
    node **warning**, so the CLI exited 0 with an empty answer.
    """

    def test_a_trailing_colon_expands_to_that_providers_default(self) -> None:
        from openstategraph.api.model_resolution import resolve_model

        assert resolve_model("ollama:") == "ollama:gpt-oss:120b-cloud"
        assert resolve_model("anthropic:") == "anthropic:claude-haiku-4-5"

    def test_a_bare_provider_name_expands_the_same_way(self) -> None:
        from openstategraph.api.model_resolution import resolve_model

        assert resolve_model("anthropic") == "anthropic:claude-haiku-4-5"
        assert resolve_model("ollama") == "ollama:gpt-oss:120b-cloud"

    def test_an_alias_is_a_prefix_too(self) -> None:
        """`claude:` and `azure_openai:` are prefixes, not providers."""
        from openstategraph.api.model_resolution import resolve_model

        assert resolve_model("claude:") == "anthropic:claude-haiku-4-5"
        assert resolve_model("azure_openai") == "openai:gpt-4.1-mini"

    def test_expansion_goes_through_the_providers_own_model_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No second table of defaults: `ProviderSpec.model_string` owns it."""
        from openstategraph.api.model_resolution import resolve_model

        monkeypatch.setenv("OPENSTATEGRAPH_OLLAMA_MODEL", "qwen3-coder:480b-cloud")
        assert resolve_model("ollama:") == "ollama:qwen3-coder:480b-cloud"

    def test_a_fully_spelled_model_is_untouched(self) -> None:
        from openstategraph.api.model_resolution import resolve_model

        assert resolve_model("anthropic:claude-opus-4-1") == "anthropic:claude-opus-4-1"
        # Two colons: the provider is the first field, the rest is the vendor's.
        assert resolve_model("ollama:gpt-oss:120b-cloud") == "ollama:gpt-oss:120b-cloud"

    def test_a_prefix_we_never_registered_is_refused_by_name(self) -> None:
        """An empty model name cannot work, whoever would have handled it."""
        from openstategraph.api.model_resolution import resolve_model

        with pytest.raises(UnknownProvider) as caught:
            resolve_model("nosuchvendor:")
        assert "nosuchvendor" in str(caught.value)
        assert "anthropic" in str(caught.value)  # it names what *is* registered

    def test_an_unprefixed_model_name_is_still_passed_through(self) -> None:
        """The open provider set is not re-narrowed on the way out.

        LangChain resolves an unambiguous bare model name itself — *"You can
        also omit the provider prefix if the model name is unambiguous (e.g.
        `gpt-5.5` resolves to OpenAI)"* — and `providers.py` exists precisely
        because our own three-name lists were narrower than
        `init_chat_model`. Refusing `"gpt-4o"` here would put that narrowing
        back. A **trailing colon** is different and is refused above: it names
        no model at all, so nothing downstream can rescue it.
        """
        from openstategraph.api.model_resolution import resolve_model

        assert resolve_model("gpt-4o") == "gpt-4o"
        assert resolve_model("google_genai:gemini-3-pro") == "google_genai:gemini-3-pro"

    def test_the_gallery_shorthand_names_a_model_the_catalogue_owns(self) -> None:
        """The other half of gallery 12: what it expands to must be reachable."""
        from openstategraph.api.model_resolution import resolve_model

        expanded = resolve_model("ollama:")
        spec = provider_catalogue().for_model(expanded)
        assert spec is not None and spec.name == "ollama"
        assert expanded.endswith("-cloud"), "Ollama means Ollama cloud, never a local model"


# --------------------------------------------------------------------- #
# Axis A — the instance default is elected, in one place (T2)
# --------------------------------------------------------------------- #


def _installed(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Simulate a one-extra install.

    All three integrations are importable in this checkout, so the only way to
    exercise candidacy is to answer `is_installed` for a machine that is not
    this one. `find_spec` is the real implementation and is tested where it
    lives; what is under test here is the *rule* that consumes it.
    """
    monkeypatch.setattr(ProviderSpec, "is_installed", lambda self: self.name in names)


class TestTheInstanceDefaultIsElected:
    """One rule, one place. Before this there were two, and they disagreed.

    `resolve_model(None)` reimplemented the choice and `default_spec()` carried
    the reasoning with **no production caller** — on a bare machine one said
    `ollama:gpt-oss:120b-cloud` and the other said `None`. Neither asked
    `is_installed()`, so both could elect a provider that cannot be imported.

    The rule now: among the **installed** providers, the first configured with
    a credential wins; failing that the first that needs no credential; failing
    that the first installed one, unconfigured, so the wall names its key; and
    with nothing installed there is no default at all.
    """

    def test_an_uninstalled_provider_is_never_elected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ticket's headline, and it was live.

        `[openai]` installed, a stale `ANTHROPIC_API_KEY` exported by some
        other tool: the product elected Anthropic and then told the user to
        `pip install 'openstategraph[anthropic]'` — the opposite of the extra
        they chose. Electing an uninstalled provider is electing a failure we
        have already detected.
        """
        from openstategraph.api.model_resolution import resolve_model

        _installed(monkeypatch, "openai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stale")

        assert resolve_model(None).startswith("openai:")

    def test_the_first_configured_candidate_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Registration order is the tiebreak, and only among candidates."""
        from openstategraph.api.model_resolution import resolve_model

        _installed(monkeypatch, "anthropic", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert resolve_model(None).startswith("openai:")

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        assert resolve_model(None).startswith("anthropic:")

    def test_an_installed_but_unconfigured_provider_still_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rule 2, and it is what makes the install line the mental model.

        `pip install 'openstategraph[anthropic]'` with no key at all resolves
        to Anthropic, so the one remaining wall names *their* vendor's
        variable rather than listing three strangers.
        """
        from openstategraph.api.model_resolution import resolve_model

        _installed(monkeypatch, "anthropic")
        assert resolve_model(None) == "anthropic:claude-haiku-4-5"

        default = provider_catalogue().elected_default()
        assert default.configured is False
        assert "ANTHROPIC_API_KEY" in default.reason

    def test_a_configured_provider_beats_a_keyless_one_whatever_the_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The two-pass rule `default_spec` carried, kept rather than collapsed.

        A keyless provider registered first must not shadow a configured one
        registered later — that is a third-party provider made unreachable by
        default no matter how correctly its key was set. No built-in is keyless
        since providers-and-credentials 02, but a plugin may be, so the rule
        still earns its place.
        """
        catalogue = provider_catalogue()
        catalogue.register(
            ProviderSpec(name="aardvark", default_model="aardvark-1", extra="aardvark")
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        _installed(monkeypatch, "aardvark", "anthropic")

        assert catalogue.elected_default().model == "anthropic:claude-haiku-4-5"

    def test_a_keyless_provider_beats_an_unconfigured_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """…but it beats a candidate that cannot be called at all."""
        catalogue = provider_catalogue()
        catalogue.register(
            ProviderSpec(name="aardvark", default_model="aardvark-1", extra="aardvark")
        )
        _installed(monkeypatch, "aardvark", "anthropic")

        assert catalogue.elected_default().model == "aardvark:aardvark-1"

    def test_nothing_installed_is_an_answer_not_a_string_nobody_can_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The F2 case: a typo'd extra installs successfully and runs nothing.

        Returning a model name here would hand back a provider that cannot be
        imported and let the failure surface as a LangChain traceback three
        layers down.
        """
        from openstategraph.api.model_resolution import resolve_model

        _installed(monkeypatch)  # nothing at all
        with pytest.raises(NoProviderInstalled) as caught:
            resolve_model(None)

        message = str(caught.value)
        assert "no model provider integration is installed" in message
        assert "pip install 'openstategraph[anthropic]'" in message

    def test_the_two_copies_of_the_rule_are_now_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2, pinned: they used to disagree on the same machine."""
        from openstategraph.api.model_resolution import resolve_model

        for installed, env in (
            (("anthropic", "openai", "ollama"), {}),
            (("openai",), {"ANTHROPIC_API_KEY": "sk-ant"}),
            (("ollama",), {"OLLAMA_HOST": "http://localhost:11434"}),
            (("anthropic",), {"ANTHROPIC_API_KEY": "sk-ant"}),
        ):
            with monkeypatch.context() as patch:
                _installed(patch, *installed)
                for name, value in env.items():
                    patch.setenv(name, value)
                assert resolve_model(None) == provider_catalogue().elected_default().model

    def test_the_reason_names_how_many_candidates_there_were(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`providers` prints this line (T3), so it is written once, here."""
        _installed(monkeypatch, "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        alone = provider_catalogue().elected_default()
        assert alone.reason == "the only provider integration installed, and it is configured"

        with monkeypatch.context() as patch:
            _installed(patch, "anthropic", "openai")
            patch.setenv("ANTHROPIC_API_KEY", "sk-ant")
            patch.setenv("OPENAI_API_KEY", "sk-openai")
            both = provider_catalogue().elected_default()
        assert both.spec is not None and both.spec.name == "anthropic"
        assert "2 integrations installed and configured (anthropic, openai)" in both.reason
        assert "default_model:" in both.reason  # how to stop guessing

    def test_the_ollama_default_is_still_never_a_local_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE.md's standing rule, moved to where Ollama can now win.

        It used to be guarded by the terminal `OLLAMA_CLOUD_MODEL` literal —
        which named Ollama whatever you had installed, and is deleted. The rule
        it protected is unchanged: when Ollama *is* elected, it is the cloud.
        """
        from openstategraph.api.model_resolution import OLLAMA_CLOUD_MODEL, resolve_model

        _installed(monkeypatch, "ollama")
        monkeypatch.setenv("OLLAMA_API_KEY", "sk-ollama")

        resolved = resolve_model(None)
        assert resolved == OLLAMA_CLOUD_MODEL
        assert resolved.endswith("-cloud")
        assert "8b" not in resolved
