"""The provider set, open by registration (ticket 02).

**Tier 1 — semver-public.** `ProviderSpec` and `PROVIDERS_GROUP` are a contract
a third party writes into their own `pyproject.toml`:

    # in the THIRD PARTY's pyproject.toml
    [project.entry-points."openstategraph.providers"]
    nvidia = "acme_osg_nvidia:SPEC"

**What was closed before this module.** `init_chat_model` already accepts far
more `provider:model` strings than we ever named — the narrowing was entirely
ours, and it lived in three literal lists that had to be edited together:

- `model_resolution.resolve_model` — an `if os.getenv(...)` chain naming
  Anthropic then OpenAI then Ollama. A fourth vendor could not be a default
  however it was configured.
- `model_resolution.ACCEPTED_CREDENTIAL_KEYS` — a four-name frozenset, so a
  fourth vendor's key was *dropped* from a run request rather than forwarded.
- `_extras.PROVIDER_EXTRAS` — a five-prefix dict, so a fourth vendor's missing
  package produced no install hint.

All three now derive from the one catalogue below. Nothing downstream may
re-enumerate providers; if a new call site needs the list, it asks here.

**Built-in and third-party are indistinguishable, and that is load-bearing.**
The three bundled providers are plain `ProviderSpec` values pushed through the
very same `ProviderCatalogue.register` a plugin's are. There is no privileged
field, no `builtin=True`, and no branch anywhere that asks where a spec came
from — so a capability a built-in has is one a plugin can have, by
construction rather than by our remembering to expose it.

**Precedence: built-in < third-party**, matching `extensions.py`'s rule for
tools. Installing a plugin that replaces `anthropic`'s default model is what
installing that plugin is *for*; a plugin that could not override would force
a fork to change one string.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

#: Providers: a `ProviderSpec`, or an iterable of them. See the module
#: docstring for the `pyproject.toml` stanza a plugin author writes.
PROVIDERS_GROUP = "openstategraph.providers"


@dataclass(frozen=True)
class ProviderSpec:
    """One vendor, as much as this framework needs to know about it.

    Deliberately *data*, not a class to subclass: everything here is a value
    `init_chat_model`, a `.env` file or an error message needs, and none of it
    is behaviour. A vendor that needed behaviour would need a client, and
    shipping vendor clients is explicitly out of scope (map.md).
    """

    #: The `init_chat_model` prefix — the `anthropic` in `anthropic:claude-…`.
    name: str

    #: The model used when this provider is chosen with nothing more specific
    #: asked for. Bare (no prefix); `model_string` adds the prefix.
    default_model: str

    #: The `pip install 'openstategraph[…]'` extra supplying its LangChain
    #: integration package.
    extra: str

    #: Credential environment variables, most significant first. The first is
    #: the one an error message tells a developer to set. Empty means the
    #: provider needs no credential from us (Ollama authenticates from its own
    #: local config).
    env_vars: tuple[str, ...] = ()

    #: Further model-string prefixes that belong to this provider's extra.
    #: `claude:` and `azure_openai:` are the two that exist, and neither is a
    #: provider in its own right.
    aliases: tuple[str, ...] = ()

    #: Human-facing name for messages. Defaults to `name`.
    label: str = ""

    def __post_init__(self) -> None:
        if not self.name or ":" in self.name or "/" in self.name:
            raise ValueError(f"provider name {self.name!r} must be a bare identifier")
        if not self.default_model:
            raise ValueError(f"provider {self.name!r} declares no default_model")
        if not self.extra:
            raise ValueError(f"provider {self.name!r} declares no extra")

    @property
    def display(self) -> str:
        return self.label or self.name

    @property
    def requires_key(self) -> bool:
        """True when this provider needs a credential we can check for.

        Derived rather than declared: a provider with no `env_vars` is one we
        have no way to check, so treating it as "needs a key" would mean
        refusing to ever select it.
        """
        return bool(self.env_vars)

    @property
    def primary_env_var(self) -> str | None:
        """The variable an error message names. `None` for keyless providers."""
        return self.env_vars[0] if self.env_vars else None

    @property
    def model_env_var(self) -> str:
        """The variable that overrides `default_model` for this provider.

        `OPENSTATEGRAPH_OLLAMA_MODEL` predates this module and is exactly this
        rule spelled out for one vendor; generalising it costs nothing and
        makes the built-in stop being a special case.
        """
        return f"OPENSTATEGRAPH_{self.name.upper()}_MODEL"

    @property
    def prefixes(self) -> tuple[str, ...]:
        """Every model-string prefix that resolves to this provider."""
        return (self.name, *self.aliases)

    def is_configured(self, env: Mapping[str, str] | None = None) -> bool:
        """Whether this provider could be called right now."""
        source: Mapping[str, str] = os.environ if env is None else env
        if not self.requires_key:
            return True
        return any(str(source.get(name) or "").strip() for name in self.env_vars)

    def model_string(self, env: Mapping[str, str] | None = None) -> str:
        """The full `provider:model` string, honouring the model env var."""
        source: Mapping[str, str] = os.environ if env is None else env
        override = str(source.get(self.model_env_var) or "").strip()
        if override:
            # An override may be written either bare or already prefixed; both
            # spellings appear in the wild and neither is wrong.
            return override if override.startswith(f"{self.name}:") else f"{self.name}:{override}"
        return f"{self.name}:{self.default_model}"

    def missing_key_message(self) -> str:
        """The exact fix, for a provider named but not configured (ticket 03)."""
        variable = self.primary_env_var
        if variable is None:  # pragma: no cover - keyless providers never fail this way
            return f'Provider "{self.name}" needs no key.'
        return (
            f'Provider "{self.name}" has no credential — '
            f"set {variable} in .env (see .env.example)."
        )


@dataclass
class ProviderCatalogue:
    """Every known provider, in registration order.

    Order is meaningful only among providers that *require* a key: see
    `default_spec`, which deliberately does not let a keyless fallback win by
    merely having registered earlier.
    """

    _specs: dict[str, ProviderSpec] = field(default_factory=dict)

    #: One line per extension that failed to load, carried rather than
    #: swallowed — the same "degrade loud, never silent" rule `extensions.py`
    #: follows for tools.
    warnings: list[str] = field(default_factory=list)

    def register(self, spec: ProviderSpec) -> "ProviderCatalogue":
        """Adds a provider, replacing any earlier one of the same name."""
        if not isinstance(spec, ProviderSpec):
            raise TypeError(f"{type(spec).__name__} is not a ProviderSpec")
        # Re-inserting keeps the *first* registration's position, which is what
        # makes a plugin's override of a built-in an override rather than a
        # demotion to the end of the default-selection order.
        self._specs[spec.name] = spec
        return self

    def get(self, name: str) -> ProviderSpec | None:
        return self._specs.get(str(name or "").strip().lower())

    def list(self) -> tuple[ProviderSpec, ...]:
        return tuple(self._specs.values())

    def for_prefix(self, prefix: str) -> ProviderSpec | None:
        """The provider a model-string prefix belongs to, aliases included."""
        wanted = str(prefix or "").strip().lower()
        if not wanted:
            return None
        direct = self._specs.get(wanted)
        if direct is not None:
            return direct
        for spec in self._specs.values():
            if wanted in spec.aliases:
                return spec
        return None

    def for_model(self, model_string: str) -> ProviderSpec | None:
        """The provider a full `provider:model` string names."""
        return self.for_prefix(str(model_string or "").split(":", 1)[0])

    def credential_names(self) -> frozenset[str]:
        """Every environment variable any registered provider calls a key.

        This is the allow-list `apply_credentials` enforces: a request may set
        these and nothing else, so registering a provider is also what makes
        its key forwardable.
        """
        return frozenset(name for spec in self._specs.values() for name in spec.env_vars)

    def extras_by_prefix(self) -> dict[str, str]:
        """`{model prefix: extra}` for every provider and every alias."""
        return {prefix: spec.extra for spec in self._specs.values() for prefix in spec.prefixes}

    def default_spec(self, env: Mapping[str, str] | None = None) -> ProviderSpec | None:
        """The provider to use when nothing more specific was asked for.

        Two passes, and the second is the reason this is not a one-liner: a
        *configured* key-requiring provider always beats a keyless fallback,
        whatever the registration order. Ollama registers third and needs no
        key, so a single ordered scan would let it shadow every plugin that
        registers after it — a fourth vendor would be unreachable by default
        no matter how correctly its key was set, which is precisely the
        closedness this ticket exists to remove.
        """
        specs = self.list()
        for spec in specs:
            if spec.requires_key and spec.is_configured(env):
                return spec
        for spec in specs:
            if not spec.requires_key:
                return spec
        return None


def builtin_specs() -> tuple[ProviderSpec, ...]:
    """The bundled three — plain specs, no privileged type or field.

    Registration order is the historical default order and is preserved
    deliberately: a developer with both an Anthropic and an OpenAI key keeps
    getting Anthropic, exactly as before this module existed.
    """
    return (
        ProviderSpec(
            name="anthropic",
            label="Anthropic",
            default_model="claude-haiku-4-5",
            extra="anthropic",
            env_vars=("ANTHROPIC_API_KEY",),
            aliases=("claude",),
        ),
        ProviderSpec(
            name="openai",
            label="OpenAI",
            default_model="gpt-4.1-mini",
            extra="openai",
            env_vars=("OPENAI_API_KEY",),
            aliases=("azure_openai",),
        ),
        ProviderSpec(
            name="ollama",
            label="Ollama",
            # **Cloud, never local.** Standing project instruction with direct
            # evidence: `llama3.1:8b` locally could not hold structured output,
            # took minutes per run, and answered a database question from
            # parametric knowledge. `gpt-oss:120b-cloud` wrote a correct
            # two-join GROUP BY in 23s. A bare `ollama:` fallback resolves
            # here, so a local model must be named explicitly to be used.
            default_model="gpt-oss:120b-cloud",
            extra="ollama",
            # No env_vars: Ollama authenticates from its own local credentials,
            # verified live with no ANTHROPIC/OPENAI/OLLAMA_HOST var set at
            # all. That is what makes it the zero-configuration fallback.
            # OLLAMA_API_KEY / OLLAMA_HOST are still *accepted* from a request
            # — see `credential_env_vars` below.
            env_vars=(),
        ),
    )


#: Variables a provider accepts but does not require, and so cannot declare in
#: `env_vars` without becoming key-requiring. Ollama is the only case: setting
#: `OLLAMA_HOST` configures it, but not setting it does not leave it broken.
OPTIONAL_ENV_VARS: dict[str, tuple[str, ...]] = {
    "ollama": ("OLLAMA_API_KEY", "OLLAMA_HOST"),
}


def credential_env_vars(catalogue: "ProviderCatalogue | None" = None) -> frozenset[str]:
    """Every variable a run request may set — required and optional alike.

    Separate from `ProviderCatalogue.credential_names` because the two answer
    different questions: that one asks "what makes this provider usable", this
    one asks "what may a request write into the process". Ollama's host and key
    are the second without being the first.
    """
    cat = catalogue if catalogue is not None else provider_catalogue()
    optional = {
        name
        for spec in cat.list()
        for name in OPTIONAL_ENV_VARS.get(spec.name, ())
    }
    return cat.credential_names() | frozenset(optional)


# --------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------- #

_CATALOGUE: ProviderCatalogue | None = None


def load_provider_catalogue() -> ProviderCatalogue:
    """Builds a fresh catalogue: built-ins, then installed plugins.

    Not memoised — `provider_catalogue()` is. Kept separate so a caller that
    genuinely wants an unshared catalogue (a test, a config loader applying
    file-declared providers) can have one without disturbing the global.
    """
    catalogue = ProviderCatalogue()
    for spec in builtin_specs():
        catalogue.register(spec)

    from openstategraph.extensions import entry_point_providers

    discovered = entry_point_providers()
    for spec in discovered.values:
        catalogue.register(spec)
    catalogue.warnings.extend(discovered.warnings)

    # Last, and therefore highest: built-in < installed plugin < config file.
    # The file is the most local and most explicit of the three — someone wrote
    # it *for this project* — so it settles a disagreement between the other
    # two. A malformed file raises rather than being skipped; see
    # `config_file.active_config`.
    from openstategraph.config_file import config_provider_specs

    for spec in config_provider_specs():
        catalogue.register(spec)
    return catalogue


def provider_catalogue() -> ProviderCatalogue:
    """The process-wide catalogue, built once.

    Memoised because entry-point enumeration walks `sys.path` and
    `resolve_model` is on the path of every single run.
    """
    global _CATALOGUE
    if _CATALOGUE is None:
        _CATALOGUE = load_provider_catalogue()
    return _CATALOGUE


def reset_provider_catalogue() -> None:
    """Drops the memoised catalogue. For tests and for config reloads."""
    global _CATALOGUE
    _CATALOGUE = None


#: Fences around the generated block in `.env.example`. Everything between them
#: is written by `env_example_section`; everything outside is hand-written.
ENV_EXAMPLE_BEGIN = "# >>> generated from the provider registry — do not edit by hand"
ENV_EXAMPLE_END = "# <<< end generated"


def env_example_section(catalogue: "ProviderCatalogue | None" = None) -> str:
    """The provider half of `.env.example`, written by the registry itself.

    Generated rather than hand-listed because a hand-listed one is wrong the
    day a provider is added and nobody notices until someone cannot work out
    why their key is ignored. `tests/test_config_file.py::TestEnvExampleParity`
    asserts the committed file still matches this, so the two cannot drift.

    Names only. A generator that emitted a value would be a generator that
    committed a secret.
    """
    cat = catalogue if catalogue is not None else provider_catalogue()
    lines = [ENV_EXAMPLE_BEGIN, "#", "# Regenerate: python3 -m openstategraph.cli env-example"]
    for spec in cat.list():
        lines.append("")
        lines.append(f"# --- {spec.display} ---")
        for name in spec.env_vars:
            lines.append(f"# Required for {spec.name}: without it this provider is skipped.")
            lines.append(f"{name}=")
        for name in OPTIONAL_ENV_VARS.get(spec.name, ()):
            if name in spec.env_vars:
                continue
            lines.append(f"# Optional for {spec.name}; accepted from a run request.")
            lines.append(f"{name}=")
        lines.append(
            f"# Overrides the default model ({spec.default_model}) for {spec.name}."
        )
        lines.append(f"{spec.model_env_var}=")
    lines.append("")
    lines.append(ENV_EXAMPLE_END)
    return "\n".join(lines)


def missing_key_diagnosis(model_string: str) -> str | None:
    """The exact fix when a named provider has no credential, else `None`.

    Returns `None` for an unknown prefix rather than guessing: `init_chat_model`
    already names the package it could not import, and a confidently wrong
    "set MYSTERY_API_KEY" is worse than saying nothing. Also `None` for a
    keyless provider, which cannot be missing a key.
    """
    spec = provider_catalogue().for_model(model_string)
    if spec is None or not spec.requires_key or spec.is_configured():
        return None
    return spec.missing_key_message()


__all__ = [
    "ENV_EXAMPLE_BEGIN",
    "ENV_EXAMPLE_END",
    "OPTIONAL_ENV_VARS",
    "PROVIDERS_GROUP",
    "ProviderCatalogue",
    "ProviderSpec",
    "builtin_specs",
    "credential_env_vars",
    "env_example_section",
    "load_provider_catalogue",
    "missing_key_diagnosis",
    "provider_catalogue",
    "reset_provider_catalogue",
]
