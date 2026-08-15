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

from openstategraph.errors import UnknownProvider
from openstategraph.providers import provider_catalogue

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
