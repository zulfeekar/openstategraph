"""One place a model string becomes a model — providers-and-credentials t02.

Before this module, three things were true at once and none of them were
visible from a call site:

- the credential gate existed only in `loader.py`, so the HTTP, MCP and
  per-node paths raised the vendor SDK's error instead of ours;
- nothing ever passed an endpoint, so `ollama.Client` dialled
  `127.0.0.1:11434` — "Ollama means cloud, never local" violated by omission;
- the extras hint was likewise `loader.py`-only.
"""

from __future__ import annotations

import pytest

from openstategraph.chat_model import model_kwargs
from openstategraph.errors import MissingProviderKey
from openstategraph.providers import reset_provider_catalogue


@pytest.fixture(autouse=True)
def _fresh_catalogue():
    reset_provider_catalogue()
    yield
    reset_provider_catalogue()


@pytest.fixture(autouse=True)
def _no_ambient_ollama(monkeypatch: pytest.MonkeyPatch):
    for name in ("OLLAMA_API_KEY", "OLLAMA_HOST", "OLLAMA_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)


class TestTheEndpointReachesTheModel:
    def test_ollama_goes_to_the_cloud_by_default(self) -> None:
        """The single most important line in this file.

        With no host named, the request must leave the machine. The old
        behaviour — no `base_url` at all — sent it to localhost.
        """
        assert model_kwargs("ollama:gpt-oss:120b-cloud") == {"base_url": "https://ollama.com"}

    def test_a_named_host_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        assert model_kwargs("ollama:llama3.1:8b") == {"base_url": "http://localhost:11434"}

    def test_the_other_providers_are_passed_nothing(self) -> None:
        """`ChatOpenAI` and `ChatAnthropic` read their own base-URL variables.

        Passing ours as well would be a second spelling of a working feature.
        """
        assert model_kwargs("anthropic:claude-haiku-4-5") == {}
        assert model_kwargs("openai:gpt-4.1-mini") == {}

    def test_an_unknown_prefix_is_passed_nothing(self) -> None:
        assert model_kwargs("mystery:model") == {}


class TestTheCredentialGateIsOnEveryPath:
    def test_an_unconfigured_provider_names_the_variable_when_used(self) -> None:
        from openstategraph.chat_model import build_chat_model

        model = build_chat_model("ollama:gpt-oss:120b-cloud")
        with pytest.raises(MissingProviderKey) as caught:
            model.invoke("hi")
        assert "OLLAMA_API_KEY" in str(caught.value)

    def test_building_it_does_not_raise(self) -> None:
        """The property that keeps credential-free workflows working.

        `input.text → output.formatted` needs nobody's API key, but every run
        builds a model before it knows whether a node will ask for one. So the
        failure belongs at first *use*.
        """
        from openstategraph.chat_model import UnconfiguredProvider, build_chat_model

        assert isinstance(build_chat_model("ollama:gpt-oss:120b-cloud"), UnconfiguredProvider)

    def test_any_way_of_reaching_for_it_raises(self) -> None:
        """Not just `invoke` — a node may bind tools or ask for structure."""
        from openstategraph.chat_model import build_chat_model

        model = build_chat_model("ollama:gpt-oss:120b-cloud")
        for reach in (
            lambda: model.bind_tools([]),
            lambda: model.with_structured_output(dict),
            lambda: model.stream("hi"),
            lambda: model("hi"),
        ):
            with pytest.raises(MissingProviderKey):
                reach()

    def test_a_host_alone_gets_past_the_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Running your own daemon needs no API key — the daemon owns its auth.

        Stops short of constructing the model: this pins the *gate*, and
        building one would reach for the `ollama` integration package.
        """
        from openstategraph.providers import missing_key_diagnosis

        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        assert missing_key_diagnosis("ollama:gpt-oss:120b-cloud") is None


class TestEveryCallSiteComesThroughHere:
    def test_no_module_calls_init_chat_model_directly(self) -> None:
        """The rule this module exists to hold.

        A direct `init_chat_model` call is one that skips the credential gate
        and the endpoint — which is exactly how the HTTP path came to give a
        vendor SDK error where the CLI gave ours.
        """
        import ast
        from pathlib import Path

        package = Path(__file__).resolve().parents[1] / "openstategraph"
        offenders: list[str] = []
        for path in sorted(package.rglob("*.py")):
            if path.name == "chat_model.py":
                continue
            # Parsed rather than grepped: half this package *discusses*
            # `init_chat_model` in prose, and a docstring is not a call.
            for node in ast.walk(ast.parse(path.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "init_chat_model"
                ):
                    offenders.append(f"{path.relative_to(package)}:{node.lineno}")
        assert offenders == [], (
            "these call init_chat_model directly and so skip the credential "
            f"gate and the endpoint: {offenders} — use chat_model.build_chat_model"
        )
