"""A provider whose constructor needs an argument our catalogue cannot supply.

**The reproduction.** A service configured for Azure OpenAI, running the
product in a container, `POST /api/runs/stream` answered 500:

    pydantic_core.ValidationError: 1 validation error for AzureChatOpenAI
      Value error, Must provide either the `api_version` argument
      or the OPENAI_API_VERSION environment variable

Its environment carried the values under their real names —
`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`,
`AZURE_OPENAI_ENDPOINT` — and this library could read none of them.
`grep -rn "api_version" backend/openstategraph/` returned nothing.

The cause is not Azure. It is that `ProviderSpec` had one vocabulary for
*credentials* (`env_vars`) and one for *addresses* (`endpoint_env`), and no
vocabulary at all for a **constructor argument**. Azure is simply the first
bundled vendor that needs one, so the only fixes available to a consumer were
to edit this library or to duplicate their variables under names it happens to
read — which is what they did, in their compose file, with a comment saying it
was a workaround.

**Where the proof reaches, and where it stops.** The 500 happened at
*construction*, not at the network: pydantic refused before a request was ever
sent. So constructing the model object with well-formed values and asserting
no `ValidationError` reproduces the whole of the reported defect. Nothing here
calls Azure, and nothing here needs an Azure subscription; the first thing that
would is `verify_provider`, which is behind a button somebody presses.

Ticket: providers-and-credentials/18
"""

from __future__ import annotations

import pytest

#: The four variables the reproduction's environment actually carried, under
#: the names Azure's own documentation and portal use. Written out rather than
#: derived, because the point of the test is that *these* names work.
AZURE_ENVIRONMENT = {
    "AZURE_OPENAI_API_KEY": "az-not-a-real-key",
    "AZURE_OPENAI_ENDPOINT": "https://example-resource.openai.azure.com/",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini-deployment",
    "AZURE_OPENAI_API_VERSION": "2025-03-01-preview",
}

#: Every variable belonging to a bundled provider, cleared before each case so
#: a developer's own `.env` cannot make a red test green or the reverse.
_OTHERS = (
    "OPENAI_API_VERSION",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OLLAMA_API_KEY",
    "OLLAMA_HOST",
    "AZURE_OPENAI_DEPLOYMENT_NAME",
)


@pytest.fixture
def azure_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reproduced machine: Azure's four names set, nothing else.

    `OPENAI_API_VERSION` is deleted deliberately and is the whole point — it is
    the duplicate the consumer had to invent, and a proof that leaves it set
    proves nothing.
    """
    for name in _OTHERS:
        monkeypatch.delenv(name, raising=False)
    for name, value in AZURE_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


class TestTheCatalogueKnowsAzure:
    def test_the_prefix_resolves_to_a_provider_of_its_own(self) -> None:
        """`azure_openai:` was a nickname for OpenAI, which is the defect.

        The word survives; what it means is corrected. A string that resolved
        to a provider whose constructor cannot accept an Azure deployment was
        never a working spelling of anything.
        """
        from openstategraph.providers import provider_catalogue

        spec = provider_catalogue().for_prefix("azure_openai")
        assert spec is not None
        assert spec.name == "azure_openai"

    def test_no_provider_still_claims_the_prefix_as_a_nickname(self) -> None:
        from openstategraph.providers import provider_catalogue

        for spec in provider_catalogue().list():
            assert "azure_openai" not in spec.aliases

    def test_its_credential_is_named_in_its_own_vocabulary(self) -> None:
        """The Ollama correction, applied before it can be broken again.

        A vendor is never reached without naming a variable somebody can set,
        see and revoke — and never through a variable belonging to a different
        vendor.
        """
        from openstategraph.providers import provider_catalogue

        spec = provider_catalogue().get("azure_openai")
        assert spec is not None
        assert spec.env_vars == ("AZURE_OPENAI_API_KEY",)


class TestConstructionIsWhereItFailed:
    def test_the_model_object_is_built_from_azures_own_names(
        self, azure_environment: None
    ) -> None:
        """The reported 500, run forwards. No `OPENAI_API_VERSION` anywhere."""
        import os

        from openstategraph.chat_model import build_chat_model

        assert "OPENAI_API_VERSION" not in os.environ

        model = build_chat_model("azure_openai:gpt-4o-mini")

        assert type(model).__name__ == "AzureChatOpenAI"
        assert model.openai_api_version == AZURE_ENVIRONMENT["AZURE_OPENAI_API_VERSION"]
        assert model.deployment_name == AZURE_ENVIRONMENT["AZURE_OPENAI_DEPLOYMENT"]
        assert model.azure_endpoint == AZURE_ENVIRONMENT["AZURE_OPENAI_ENDPOINT"]

    def test_a_workflow_resolves_and_constructs_it(self, azure_environment: None) -> None:
        """End to end from the elected default, not from a hand-written string.

        With only Azure's four variables set, the election must reach Azure and
        the string it elects must build. That is the whole path a run takes
        before it touches a network.
        """
        from openstategraph.chat_model import build_chat_model
        from openstategraph.providers import provider_catalogue

        elected = provider_catalogue().elected_default()

        assert elected.spec is not None
        assert elected.spec.name == "azure_openai"
        assert elected.configured is True
        assert elected.model is not None
        assert type(build_chat_model(elected.model)).__name__ == "AzureChatOpenAI"


class TestAMissingArgumentNamesItsVariable:
    """The negative. A required argument with no source must be *reported*,
    not discovered inside pydantic — which is the difference between a
    sentence a person can act on and a 500 with a validation traceback.
    """

    def test_the_message_names_the_variable(
        self, azure_environment: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.providers import ProviderEnvironment, provider_catalogue

        monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)
        spec = provider_catalogue().get("azure_openai")
        assert spec is not None

        gap = ProviderEnvironment(spec).readiness()

        assert gap is not None
        assert "AZURE_OPENAI_API_VERSION" in gap.message
        # Not a credential problem, and the message must not send a reader to
        # check a key that is present and correct.
        assert gap.missing_key is False

    def test_nothing_reaches_pydantic(
        self, azure_environment: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`build_chat_model` returns the stand-in rather than raising, and the
        stand-in's error is ours — the same shape a missing key already had."""
        from openstategraph.chat_model import build_chat_model
        from openstategraph.errors import OpenStateGraphError

        monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)

        model = build_chat_model("azure_openai:gpt-4o-mini")

        with pytest.raises(OpenStateGraphError) as raised:
            model.invoke("hi")
        assert "AZURE_OPENAI_API_VERSION" in str(raised.value)

    def test_the_provider_does_not_report_itself_configured(
        self, azure_environment: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`providers-and-credentials/12` said ready without a credential. This
        is the same lie one field along: a key is present and the provider
        still cannot be called."""
        from openstategraph.providers import ProviderEnvironment, provider_catalogue

        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        spec = provider_catalogue().get("azure_openai")
        assert spec is not None

        here = ProviderEnvironment(spec)

        assert here.has_credential() is True
        assert here.is_configured() is False


class TestNothingMovedForAnybodyElse:
    """The widening is a default, so every existing spec keeps its behaviour."""

    def test_no_bundled_provider_but_azure_declares_an_argument(self) -> None:
        from openstategraph.providers import builtin_specs

        declaring = {spec.name for spec in builtin_specs() if spec.constructor_args}
        assert declaring == {"azure_openai"}

    def test_the_historical_election_order_is_unchanged(self) -> None:
        from openstategraph.providers import builtin_specs

        assert [spec.name for spec in builtin_specs()][:3] == [
            "anthropic",
            "openai",
            "ollama",
        ]

    def test_an_argumentless_provider_contributes_no_keyword(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.chat_model import model_kwargs

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-real")
        assert model_kwargs("anthropic:claude-haiku-4-5") == {}


class TestTheMechanismCarriesNoSecret:
    """A constructor argument is *configuration*, never key material.

    Stated as a test rather than as a comment because the config loader
    already refuses key-shaped fields and this must not become the way round
    it. Azure's key stays in `env_vars`, where the credential machinery masks
    it; the SDK reads it from the environment itself.
    """

    def test_no_argument_reads_a_secret_variable(self) -> None:
        from openstategraph.providers import provider_catalogue

        for spec in provider_catalogue().list():
            for argument in spec.constructor_args:
                for name in argument.env_vars:
                    assert not name.upper().endswith(
                        ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
                    ), f"{spec.name}.{argument.keyword} would carry a secret via {name}"

    def test_the_resolved_keywords_carry_no_secret(self, azure_environment: None) -> None:
        from openstategraph.chat_model import model_kwargs

        resolved = model_kwargs("azure_openai:gpt-4o-mini")

        assert AZURE_ENVIRONMENT["AZURE_OPENAI_API_KEY"] not in repr(resolved)
        assert "api_key" not in resolved

    def test_an_argument_variable_is_not_forwardable_from_a_request(self) -> None:
        """An address a client could name is an address a client could redirect
        the server's own credential to — the rule `_is_secret`'s docstring
        already states for `endpoint_env`, applied to the new field."""
        from openstategraph.providers import credential_env_vars

        forwardable = credential_env_vars()
        assert "AZURE_OPENAI_ENDPOINT" not in forwardable
        assert "AZURE_OPENAI_API_VERSION" not in forwardable


class TestTwoProvidersShareOneSdk:
    """`openai` and `azure_openai` both ship in `langchain-openai`, so both
    raise `openai.AuthenticationError` — and `credential_error_from` attributes
    an exception by the module it came from.

    Found by running it, not by reading it: a workflow configured for Azure and
    given a bad key answered *"Provider \"openai\" refused the credential —
    check OPENAI_API_KEY"*, on a machine where `OPENAI_API_KEY` was not set at
    all. The message named a variable that was not in play, which is the same
    defect as the 500 wearing different clothes.

    The exception cannot tell the two apart. The **environment** can, and that
    is the tolerant-in-reading, strict-in-trusting rule applied here: narrow
    the candidates to those holding a credential, and where two still claim it,
    name both rather than guess.
    """

    class _Refused(Exception):
        status_code = 401

    _Refused.__module__ = "openai"

    def _error(self) -> Exception:
        error = self._Refused("Access denied")
        error.__class__.__module__ = "openai"
        return error

    def test_it_names_the_provider_that_actually_holds_a_credential(
        self, azure_environment: None
    ) -> None:
        from openstategraph.chat_model import credential_error_from

        translated = credential_error_from(self._error())

        assert translated is not None
        assert "AZURE_OPENAI_API_KEY" in str(translated)
        # `check OPENAI_API_KEY`, not the bare name — `AZURE_OPENAI_API_KEY`
        # ends with it, so the loose assertion could never have failed.
        assert "check OPENAI_API_KEY" not in str(translated)
        assert '"openai"' not in str(translated)

    def test_with_both_configured_it_names_both(
        self, azure_environment: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guessing between two live credentials is worse than naming two."""
        from openstategraph.chat_model import credential_error_from

        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

        translated = credential_error_from(self._error())

        assert translated is not None
        assert "OPENAI_API_KEY" in str(translated)
        assert "AZURE_OPENAI_API_KEY" in str(translated)

    def test_with_neither_configured_it_still_names_both(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The degenerate case, and naming both is right in it too.

        With no credential anywhere there is nothing to narrow by — and a 401
        cannot in practice arrive from here at all, since `build_chat_model`
        would have handed back the stand-in before a request was sent. Falling
        back to the first registered would be picking a name out of a hat.
        """
        from openstategraph.chat_model import credential_error_from

        for name in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"):
            monkeypatch.delenv(name, raising=False)

        translated = credential_error_from(self._error())

        assert translated is not None
        assert "OPENAI_API_KEY or AZURE_OPENAI_API_KEY" in str(translated)

    def test_a_provider_with_an_sdk_of_its_own_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ordinary case — one SDK, one provider — word for word as before."""
        from openstategraph.chat_model import credential_error_from

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")

        class Refused(Exception):
            status_code = 401

        Refused.__module__ = "anthropic"

        translated = credential_error_from(Refused("nope"))

        assert translated is not None
        assert str(translated).startswith(
            'Provider "anthropic" refused the credential — check ANTHROPIC_API_KEY in .env.'
        )
