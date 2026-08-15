"""Two walls, one message — workflow-gallery ticket 38.

A model-driven node is guarded by two checks: *is there a credential* and *is
the provider integration installed*. They used to be evaluated one at a time,
in the order that wastes a round trip. Ticket 08's customer, on a
`[server]`-only install with no key, saw this:

    warning: Node "summarise1" failed and produced no result. Provider
    "ollama" has no credential — set OLLAMA_API_KEY or OLLAMA_HOST in .env.

did exactly what it said, and the *same* command then failed **worse** — a
34-line LangChain traceback out of `load_workflow`, because the credential
gate short-circuited ahead of the import and the integration gap could only
ever be discovered second. Supplying the credential made the error louder,
longer and later.

So the rule these tests hold is: **report everything missing for this
provider in one message, whichever gap is discovered first, and never show a
LangChain traceback for a condition we detected ourselves.** The last clause
is deliberately narrow — a provider whose integration module we cannot name
is one we did *not* detect, and its ImportError is still the honest answer.
"""

from __future__ import annotations

import pytest

from openstategraph.errors import MissingProviderKey, MissingProviderPackage
from openstategraph.providers import (
    ProviderSpec,
    provider_catalogue,
    reset_provider_catalogue,
)

#: A provider whose integration package is guaranteed absent, and whose key is
#: equally guaranteed unset. Registered rather than monkeypatched so the gap is
#: expressed the way a third-party provider expresses it — the catalogue draws
#: no distinction between built-in and plugin, and neither does this test.
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


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch):
    for name in ("GHOST_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST", "OLLAMA_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def ghost():
    provider_catalogue().register(GHOST)
    return GHOST


def _raise(model_name: str) -> BaseException:
    """Build the model, use it, and hand back whatever it refused with."""
    from openstategraph.chat_model import build_chat_model

    model = build_chat_model(model_name)
    with pytest.raises(Exception) as caught:  # noqa: B017 - the class is the assertion
        model.invoke("hi")
    return caught.value


class TestTheGapIsOneLine:
    def test_a_missing_integration_refuses_in_our_voice(self, ghost) -> None:
        """No LangChain sentence, no traceback — the same shape as a missing key."""
        error = _raise("ghost:spook-1")

        assert isinstance(error, MissingProviderPackage)
        assert str(error).count("\n") == 0
        assert "pip install 'openstategraph[ghost]'" in str(error)
        assert "Initializing" not in str(error)

    def test_building_it_does_not_raise(self, ghost) -> None:
        """The property `UnconfiguredProvider` exists for, extended to the extra.

        A workflow with no model-calling node runs fine on an install with no
        provider integration at all, exactly as it does with no credential —
        and every run builds a model before it knows whether a node will ask
        for one. The integration gap used to raise out of `load_workflow`, so
        `openstategraph graph` on a document it could not draw a model for
        failed too.
        """
        from openstategraph.chat_model import UnconfiguredProvider, build_chat_model

        assert isinstance(build_chat_model("ghost:spook-1"), UnconfiguredProvider)

    def test_both_gaps_arrive_in_one_message(self, ghost) -> None:
        error = _raise("ghost:spook-1")

        assert "GHOST_API_KEY" in str(error)
        assert "pip install 'openstategraph[ghost]'" in str(error)
        assert str(error).count("\n") == 0

    def test_fixing_only_the_credential_does_not_change_the_class(
        self, ghost, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ticket 38's headline, pinned.

        Doing what the message said must not produce a different *kind* of
        failure. The remaining wall is the same wall, named the same way, and
        the message is strictly shorter than it was.
        """
        before = _raise("ghost:spook-1")

        monkeypatch.setenv("GHOST_API_KEY", "sk-whatever")
        after = _raise("ghost:spook-1")

        assert type(after) is type(before) is MissingProviderPackage
        assert "GHOST_API_KEY" not in str(after)
        assert "pip install 'openstategraph[ghost]'" in str(after)
        assert len(str(after)) < len(str(before))

    def test_a_credential_gap_alone_is_still_a_credential_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The installed-but-unconfigured case, unchanged by this ticket."""
        error = _raise("ollama:gpt-oss:120b-cloud")

        assert isinstance(error, MissingProviderKey)
        assert "OLLAMA_API_KEY" in str(error)


class TestTheCatalogueKnowsWhatIsInstalled:
    def test_a_declared_module_that_is_absent_reads_as_not_installed(self) -> None:
        assert GHOST.is_installed() is False

    def test_the_built_in_three_declare_their_integration_module(self) -> None:
        """Without this, nothing can be pre-checked and the traceback returns."""
        from openstategraph.providers import builtin_specs

        assert {spec.name: spec.integration_module for spec in builtin_specs()} == {
            "anthropic": "langchain_anthropic",
            "openai": "langchain_openai",
            "ollama": "langchain_ollama",
        }

    def test_a_provider_that_declares_no_module_is_never_pre_checked(self) -> None:
        """Silence beats a guess.

        A plugin may ship its integration inside its own distribution, or name
        a module we would derive wrongly from its extra. For those, the
        pre-flight check has nothing to check and `init_chat_model`'s own
        ImportError — which names the package it actually failed on — is the
        honest answer.
        """
        undeclared = ProviderSpec(name="mystery", default_model="m", extra="mystery")

        assert undeclared.is_installed() is True


class TestNoTracebackForAGapWeDetected:
    def test_load_workflow_does_not_raise_on_a_missing_integration(
        self, ghost, tmp_path
    ) -> None:
        """The 34 lines, gone at the source.

        `load_workflow` builds the document's model, so an integration gap
        raised there rather than at first use — and out of the *library* path,
        where nothing catches it.
        """
        import json

        from openstategraph import load_workflow

        package = tmp_path / "gap-demo"
        package.mkdir()
        (package / "workflow.json").write_text(
            json.dumps(
                {
                    "version": 3,
                    "name": "Gap Demo",
                    "settings": {"model": "ghost:spook-1"},
                    "nodes": [
                        {"id": "in1", "type": "input.text", "data": {}},
                        {"id": "out1", "type": "output.formatted", "data": {}},
                    ],
                    "edges": [
                        {
                            "id": "e1",
                            "source": {"nodeId": "in1", "portId": "text"},
                            "target": {"nodeId": "out1", "portId": "content"},
                        }
                    ],
                }
            )
        )

        workflow = load_workflow(str(package))

        assert workflow is not None
