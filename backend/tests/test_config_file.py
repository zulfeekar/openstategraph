"""`openstategraph.yaml` — versioned config, secrets excluded by construction.

Ticket 03. Three separable promises, tested separately:

1. the file declares providers and models and is schema-validated, with an
   error naming the file and the field rather than a stack trace;
2. a secret can never be in it — not "should not be", *rejected*;
3. the precedence chain is exactly
   `config file < environment < workflow settings.model < node's own model
   < caller's model= argument`, and every adjacent pair is pinned.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.config_file import (
    CONFIG_FILENAMES,
    ConfigError,
    OpenStateGraphConfig,
    find_config_file,
    load_config,
    reset_active_config,
)
from openstategraph.providers import reset_provider_catalogue


@pytest.fixture(autouse=True)
def _fresh():
    reset_provider_catalogue()
    reset_active_config()
    yield
    reset_provider_catalogue()
    reset_active_config()


def write(root: Path, text: str, name: str = "openstategraph.yaml") -> Path:
    path = root / name
    path.write_text(text)
    return path


# --------------------------------------------------------------------- #
# Discovery and shape
# --------------------------------------------------------------------- #


class TestTheFileIsFound:
    def test_yaml_is_the_canonical_name(self) -> None:
        assert CONFIG_FILENAMES[0] == "openstategraph.yaml"

    def test_json_is_accepted_too(self) -> None:
        """Nobody is forced into YAML; `json` is stdlib either way."""
        assert "openstategraph.json" in CONFIG_FILENAMES

    def test_it_is_found_in_the_root(self, tmp_path: Path) -> None:
        path = write(tmp_path, "version: 1\n")
        assert find_config_file(tmp_path) == path

    def test_absent_is_not_an_error(self, tmp_path: Path) -> None:
        """No config file is the normal case, not a degraded one."""
        assert find_config_file(tmp_path) is None

    def test_an_env_var_points_at_one_explicitly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = write(tmp_path, "version: 1\n", name="custom.yaml")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(path))
        assert find_config_file(tmp_path / "elsewhere") == path


class TestItIsSchemaValidated:
    def test_a_minimal_file_loads(self, tmp_path: Path) -> None:
        config = load_config(write(tmp_path, "version: 1\n"))
        assert isinstance(config, OpenStateGraphConfig)
        assert config.providers == []

    def test_providers_and_models_are_declared(self, tmp_path: Path) -> None:
        config = load_config(
            write(
                tmp_path,
                """
version: 1
default_model: anthropic:claude-haiku-4-5
providers:
  - name: anthropic
    default_model: claude-sonnet-4-5
    api_key_env: ANTHROPIC_API_KEY
  - name: nvidia
    default_model: meta/llama-3.3-70b-instruct
    extra: nvidia
    api_key_env: NVIDIA_API_KEY
""",
            )
        )
        assert config.default_model == "anthropic:claude-haiku-4-5"
        assert [p.name for p in config.providers] == ["anthropic", "nvidia"]
        assert config.providers[1].api_key_env == "NVIDIA_API_KEY"

    def test_an_unknown_key_is_never_silently_ignored(self, tmp_path: Path) -> None:
        path = write(tmp_path, "version: 1\nprovidres:\n  - name: anthropic\n")
        with pytest.raises(ConfigError) as caught:
            load_config(path)
        message = str(caught.value)
        assert "openstategraph.yaml" in message
        assert "providres" in message  # names the typo, not just "invalid"

    def test_an_unknown_key_on_a_provider_is_refused_too(self, tmp_path: Path) -> None:
        path = write(tmp_path, "version: 1\nproviders:\n  - name: a\n    modle: x\n")
        with pytest.raises(ConfigError) as caught:
            load_config(path)
        assert "modle" in str(caught.value)
        assert "providers.0" in str(caught.value)  # the field path, not a line alone

    def test_a_syntax_error_names_the_file_and_the_line(self, tmp_path: Path) -> None:
        path = write(tmp_path, "version: 1\n  bad:\n:::\n")
        with pytest.raises(ConfigError) as caught:
            load_config(path)
        message = str(caught.value)
        assert str(path) in message
        assert "line" in message.lower()

    def test_a_wrong_type_names_the_field(self, tmp_path: Path) -> None:
        path = write(tmp_path, "version: not-a-number\n")
        with pytest.raises(ConfigError) as caught:
            load_config(path)
        assert "version" in str(caught.value)

    def test_an_unsupported_version_says_so(self, tmp_path: Path) -> None:
        path = write(tmp_path, "version: 99\n")
        with pytest.raises(ConfigError) as caught:
            load_config(path)
        assert "99" in str(caught.value)

    def test_json_loads_identically(self, tmp_path: Path) -> None:
        path = tmp_path / "openstategraph.json"
        path.write_text(json.dumps({"version": 1, "default_model": "openai:gpt-4.1-mini"}))
        assert load_config(path).default_model == "openai:gpt-4.1-mini"


# --------------------------------------------------------------------- #
# Secrets, excluded by construction
# --------------------------------------------------------------------- #


class TestASecretCannotBeInThisFile:
    @pytest.mark.parametrize(
        "field",
        ["api_key", "apikey", "key", "token", "secret", "password", "credentials"],
    )
    def test_a_key_shaped_field_is_rejected_by_name(self, tmp_path: Path, field: str) -> None:
        path = write(tmp_path, f"version: 1\nproviders:\n  - name: a\n    {field}: whatever\n")
        with pytest.raises(ConfigError) as caught:
            load_config(path)
        message = str(caught.value)
        assert field in message
        assert ".env" in message  # says where it belongs instead

    def test_naming_the_env_var_is_explicitly_allowed(self, tmp_path: Path) -> None:
        """`api_key_env` contains "key" and must survive — it names a
        variable, which is the whole point of the file."""
        config = load_config(
            write(
                tmp_path,
                "version: 1\nproviders:\n  - name: a\n    api_key_env: A_API_KEY\n",
            )
        )
        assert config.providers[0].api_key_env == "A_API_KEY"

    @pytest.mark.parametrize(
        "value",
        ["sk-ant-api03-abcdef", "sk-proj-abcdef", "ghp_abcdefabcdef", "AIzaSyAbCdEf"],
    )
    def test_a_key_shaped_value_is_rejected_wherever_it_hides(
        self, tmp_path: Path, value: str
    ) -> None:
        """The field-name rule alone is not enough: `api_key_env: sk-…` has an
        innocent name and a secret in it."""
        path = write(tmp_path, f"version: 1\nproviders:\n  - name: a\n    api_key_env: {value}\n")
        with pytest.raises(ConfigError) as caught:
            load_config(path)
        assert ".env" in str(caught.value)

    def test_a_normal_model_id_is_not_mistaken_for_a_secret(self, tmp_path: Path) -> None:
        """No false positives — a model id is long and opaque-looking too."""
        config = load_config(
            write(
                tmp_path,
                "version: 1\ndefault_model: nvidia:meta/llama-3.3-70b-instruct\n",
            )
        )
        assert config.default_model == "nvidia:meta/llama-3.3-70b-instruct"


# --------------------------------------------------------------------- #
# The config file contributes providers
# --------------------------------------------------------------------- #


class TestTheFileCanDeclareAProvider:
    def test_a_new_provider_reaches_the_catalogue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.providers import provider_catalogue

        write(
            tmp_path,
            """
version: 1
providers:
  - name: nvidia
    default_model: meta/llama-3.3-70b-instruct
    extra: nvidia
    api_key_env: NVIDIA_API_KEY
""",
        )
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(tmp_path / "openstategraph.yaml"))
        reset_provider_catalogue()

        spec = provider_catalogue().get("nvidia")
        assert spec is not None
        assert spec.env_vars == ("NVIDIA_API_KEY",)
        assert spec.default_model == "meta/llama-3.3-70b-instruct"

    def test_it_may_override_a_built_in_default_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.providers import provider_catalogue

        write(
            tmp_path,
            "version: 1\nproviders:\n  - name: anthropic\n    default_model: claude-opus-4-5\n",
        )
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(tmp_path / "openstategraph.yaml"))
        reset_provider_catalogue()

        spec = provider_catalogue().get("anthropic")
        assert spec is not None
        assert spec.default_model == "claude-opus-4-5"
        # …without losing what the file did not mention.
        assert spec.env_vars == ("ANTHROPIC_API_KEY",)

    def test_redeclaring_a_built_in_keeps_its_endpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every inherited field, not just the ones that existed at the time.

        This rebuilds a `ProviderSpec` field by field, so a field added to the
        dataclass and not added here is silently dropped. That is not
        hypothetical: `endpoint_env` and `default_endpoint` were added for
        providers-and-credentials ticket 02 and missed here, so a file
        containing nothing but `- name: ollama` — which
        `openstategraph.example.yaml` contains — reverted Ollama's endpoint to
        `None` and sent every call back to `127.0.0.1:11434`. The exact
        violation that ticket closed, reachable through a config file.
        """
        from openstategraph.providers import provider_catalogue

        write(tmp_path, "version: 1\nproviders:\n  - name: ollama\n")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(tmp_path / "openstategraph.yaml"))
        for name in ("OLLAMA_HOST", "OLLAMA_ENDPOINT"):
            monkeypatch.delenv(name, raising=False)
        reset_provider_catalogue()

        spec = provider_catalogue().get("ollama")
        assert spec is not None
        assert spec.endpoint_env == ("OLLAMA_HOST", "OLLAMA_ENDPOINT")
        assert spec.base_url() == "https://ollama.com"

    def test_no_provider_field_is_silently_dropped(self) -> None:
        """A guard against the next field, rather than only this one.

        Any `ProviderSpec` field the config layer does not carry over is a
        redeclaration that quietly loses behaviour. Listed explicitly so that
        adding a field forces a decision here.
        """
        import dataclasses

        from openstategraph.providers import ProviderSpec

        carried = {
            "name",
            "default_model",
            "extra",
            "env_vars",
            "aliases",
            "endpoint_env",
            "default_endpoint",
            "label",
            "integration_module",
        }
        declared = {field.name for field in dataclasses.fields(ProviderSpec)}
        assert declared == carried, (
            "ProviderSpec gained or lost a field; config_file.config_provider_specs "
            "rebuilds the spec field by field and must carry it over"
        )


# --------------------------------------------------------------------- #
# Precedence — every adjacent pair
# --------------------------------------------------------------------- #


class TestPrecedence:
    """config file < environment < workflow settings.model < node < caller."""

    @pytest.fixture(autouse=True)
    def _no_ambient_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENSTATEGRAPH_OLLAMA_MODEL"):
            monkeypatch.delenv(name, raising=False)

    def _with_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
        write(tmp_path, text)
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(tmp_path / "openstategraph.yaml"))
        reset_provider_catalogue()
        reset_active_config()

    def test_config_beats_the_built_in_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.model_resolution import resolve_model

        assert resolve_model(None) == "ollama:gpt-oss:120b-cloud"
        self._with_config(tmp_path, monkeypatch, "version: 1\ndefault_model: ollama:custom\n")
        assert resolve_model(None) == "ollama:custom"

    def test_environment_beats_the_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.model_resolution import resolve_model

        self._with_config(tmp_path, monkeypatch, "version: 1\ndefault_model: ollama:custom\n")
        assert resolve_model(None) == "ollama:custom"

        # A credential in the environment names a provider, and that outranks
        # a file a colleague committed.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        assert resolve_model(None).startswith("anthropic:")

    def test_environment_beats_the_config_file_for_the_model_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.model_resolution import resolve_model

        self._with_config(
            tmp_path,
            monkeypatch,
            "version: 1\nproviders:\n  - name: anthropic\n    default_model: claude-from-file\n",
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        assert resolve_model(None) == "anthropic:claude-from-file"

        monkeypatch.setenv("OPENSTATEGRAPH_ANTHROPIC_MODEL", "claude-from-env")
        assert resolve_model(None) == "anthropic:claude-from-env"

    def test_workflow_settings_beats_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.model_resolution import resolve_model, workflow_default_model

        self._with_config(tmp_path, monkeypatch, "version: 1\ndefault_model: ollama:custom\n")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")

        document = {"settings": {"model": "openai:gpt-4.1-mini"}}
        assert resolve_model(workflow_default_model(document)) == "openai:gpt-4.1-mini"

    def test_the_caller_argument_beats_the_workflow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.model_resolution import resolve_model, workflow_default_model

        self._with_config(tmp_path, monkeypatch, "version: 1\ndefault_model: ollama:custom\n")
        document = {"settings": {"model": "openai:gpt-4.1-mini"}}
        caller = "anthropic:claude-opus-4-5"

        # The call sites all spell it this way: `request.model or settings`.
        assert resolve_model(caller or workflow_default_model(document)) == caller

    def test_the_node_beats_the_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The node layer lives in `NodeRuntime`, between workflow and caller.

        `_resolve_model` is handed the already-resolved shared default and
        overrides it only when the node names one of its own.
        """
        import langchain.chat_models

        from openstategraph.compile.node_runtime import NodeRuntime

        monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda key, **_: f"<{key}>")
        # The node names OpenAI, so OpenAI has to be configured — otherwise
        # this exercises the unconfigured-provider fallback instead of the
        # precedence rule it is named for.
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        # A real runtime rather than `__new__` plus two hand-set attributes.
        # The surgery predated `RuntimeServices` being kept whole and broke
        # the moment the class had a collaborator to set up
        # (reviews-2026-08-14 ticket 07); the constructor is all defaults, so
        # it was never the cost the shortcut implied.
        runtime = NodeRuntime(model="<workflow-default>")
        runtime._model_cache = {}  # type: ignore[attr-defined]

        assert runtime._resolve_model({}) == "<workflow-default>"
        assert runtime._resolve_model({"model": "openai/gpt-4.1-mini"}) == "<openai:gpt-4.1-mini>"


# --------------------------------------------------------------------- #
# A named provider with no key fails loudly, with the exact fix
# --------------------------------------------------------------------- #


class TestAMissingKeyIsLoud:
    def test_it_names_the_variable_and_the_example_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.providers import provider_catalogue

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        spec = provider_catalogue().get("anthropic")
        assert spec is not None

        message = spec.missing_key_message()
        assert "ANTHROPIC_API_KEY" in message
        assert ".env" in message
        assert ".env.example" in message

    def test_the_diagnosis_fires_for_a_model_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from openstategraph.providers import missing_key_diagnosis

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert "ANTHROPIC_API_KEY" in (missing_key_diagnosis("anthropic:claude-haiku-4-5") or "")

    def test_a_configured_provider_produces_no_diagnosis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.providers import missing_key_diagnosis

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        assert missing_key_diagnosis("anthropic:claude-haiku-4-5") is None

    def test_a_keyless_provider_produces_no_diagnosis(self) -> None:
        """A provider that declares no variables cannot be missing one.

        Ollama used to be this case and no longer is
        (providers-and-credentials ticket 02), so the rule is exercised
        directly on a spec rather than through a built-in — which is better,
        because the rule belongs to `ProviderSpec`, not to any one vendor.
        """
        from openstategraph.providers import (
            ProviderCatalogue,
            ProviderSpec,
            missing_key_diagnosis,
        )

        keyless = ProviderSpec(name="aardvark", default_model="a-1", extra="aardvark")
        assert keyless.requires_key is False
        assert ProviderCatalogue().register(keyless).for_model("aardvark:a-1") is keyless
        # And the built-in that used to occupy this branch now does not.
        assert missing_key_diagnosis("ollama:gpt-oss:120b-cloud") is not None

    def test_an_unknown_provider_produces_no_diagnosis(self) -> None:
        """A wrong guess is worse than none — `init_chat_model`'s own error
        already names what it could not import."""
        from openstategraph.providers import missing_key_diagnosis

        assert missing_key_diagnosis("mystery:model") is None


# --------------------------------------------------------------------- #
# .env.example is generated from the registry, not hand-listed
# --------------------------------------------------------------------- #


class TestEnvExampleParity:
    ROOT = Path(__file__).resolve().parents[2]

    def test_every_registered_variable_is_documented(self) -> None:
        from openstategraph.providers import credential_env_vars

        text = (self.ROOT / ".env.example").read_text()
        missing = [name for name in sorted(credential_env_vars()) if name not in text]
        assert missing == [], f".env.example is missing {missing}"

    def test_every_model_override_variable_is_documented(self) -> None:
        from openstategraph.providers import provider_catalogue

        text = (self.ROOT / ".env.example").read_text()
        missing = [
            spec.model_env_var
            for spec in provider_catalogue().list()
            if spec.model_env_var not in text
        ]
        assert missing == [], f".env.example is missing {missing}"

    def test_the_generated_block_is_exactly_what_the_registry_produces(self) -> None:
        """Parity, not merely presence — the two cannot drift in either
        direction. Regenerate with `openstategraph env-example`."""
        from openstategraph.providers import (
            ENV_EXAMPLE_BEGIN,
            ENV_EXAMPLE_END,
            env_example_section,
        )

        text = (self.ROOT / ".env.example").read_text()
        start = text.index(ENV_EXAMPLE_BEGIN)
        end = text.index(ENV_EXAMPLE_END) + len(ENV_EXAMPLE_END)
        assert text[start:end] == env_example_section()

    def test_a_provider_reachable_two_ways_does_not_call_both_required(self) -> None:
        """"Required" is a lie when either variable on its own is enough.

        Ollama takes `OLLAMA_API_KEY` *or* `OLLAMA_HOST`
        (providers-and-credentials ticket 02). A developer reading two lines
        each headed "Required" would reasonably conclude they need an API key
        to point at their own daemon, which is exactly backwards.
        """
        from openstategraph.providers import env_example_section

        section = env_example_section()
        ollama = section[section.index("--- Ollama ---") :]
        assert "set one of OLLAMA_API_KEY or OLLAMA_HOST" in ollama
        # Not once per variable, and never the bare singular claim.
        assert "without it this provider is skipped" not in ollama
        assert ollama.count("Required for ollama") == 1

    def test_a_single_variable_provider_still_says_required(self) -> None:
        """The copy stays direct where there is only one thing to set."""
        from openstategraph.providers import env_example_section

        section = env_example_section()
        anthropic = section[section.index("--- Anthropic ---") : section.index("--- OpenAI ---")]
        assert "Required for anthropic:" in anthropic
        assert "one of" not in anthropic

    def test_the_cli_prints_that_same_block(self, capsys: pytest.CaptureFixture[str]) -> None:
        from openstategraph.cli import main
        from openstategraph.providers import env_example_section

        assert main(["env-example"]) == 0
        assert capsys.readouterr().out.strip() == env_example_section().strip()

    def test_the_providers_command_reports_state_without_printing_a_key(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from openstategraph.cli import main

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret")
        assert main(["providers"]) == 0
        out = capsys.readouterr().out
        assert "anthropic" in out and "ANTHROPIC_API_KEY" in out
        assert "supersecret" not in out  # the name, never the value

    def test_it_contains_no_actual_secret(self) -> None:
        """Every variable is present and every one of them is empty."""
        from openstategraph.config_file import looks_like_a_secret

        for line in (self.ROOT / ".env.example").read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            _, _, value = line.partition("=")
            assert not looks_like_a_secret(value.strip()), line

    def test_dot_env_is_gitignored(self) -> None:
        ignore = (self.ROOT / ".gitignore").read_text()
        assert "\n.env\n" in ignore
        assert "!.env.example" in ignore


class TestTheShippedExampleIsReal:
    """The example file is documentation that runs. A shipped example that
    does not load is worse than none — it teaches the wrong shape."""

    EXAMPLE = Path(__file__).resolve().parents[2] / "openstategraph.example.yaml"

    def test_it_loads(self) -> None:
        config = load_config(self.EXAMPLE)
        assert config.version == 1
        assert {p.name for p in config.providers} == {"anthropic", "openai", "ollama"}

    def test_it_contains_no_secret(self) -> None:
        from openstategraph.config_file import looks_like_a_secret

        for line in self.EXAMPLE.read_text().splitlines():
            assert not looks_like_a_secret(line.partition(":")[2].strip()), line

    def test_it_is_not_picked_up_as_the_real_config(self, tmp_path: Path) -> None:
        """Its name is deliberately not one of `CONFIG_FILENAMES` — shipping a
        file that silently becomes everyone's config would be a trap."""
        assert self.EXAMPLE.name not in CONFIG_FILENAMES
