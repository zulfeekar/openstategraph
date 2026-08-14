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


#: Variable names whose value must never be shown. Everything else a provider
#: declares is an address, not a credential — a host or an endpoint — and those
#: are useful precisely because they are readable.
_SECRET_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")


def _without_userinfo(value: str) -> str:
    """A URL with any `user:password@` removed, or the value unchanged.

    The hint shows a non-secret variable whole, because masking an address
    hides the only thing worth reading. `OLLAMA_HOST` can carry credentials
    though — reaching a daemon through an authenticating proxy is the ordinary
    way that happens, and nobody thinks of it as putting a key in a variable
    named `_HOST`. So the exception for addresses gets its own exception: the
    host and port survive, the userinfo does not.

    Deliberately string-level and conservative. Anything that does not parse
    as a URL with userinfo is returned untouched — this must never mangle a
    plain `localhost:11434`, which is the overwhelmingly common value.
    """
    marker = "://"
    scheme_at = value.find(marker)
    if scheme_at == -1:
        return value
    rest = value[scheme_at + len(marker) :]
    # Only userinfo can precede the host, and only up to the first `/`.
    authority_end = len(rest) if "/" not in rest else rest.index("/")
    authority = rest[:authority_end]
    if "@" not in authority:
        return value
    host = authority.rsplit("@", 1)[1]
    return value[: scheme_at + len(marker)] + host + rest[authority_end:]


def _is_secret(name: str) -> bool:
    """Whether a variable holds a **secret** rather than an address.

    The distinction is load-bearing in two opposite-facing places: a secret
    must never be *shown* (`key_hint` masks it), and an address must never be
    *accepted from a client* (`accepted_credential_keys` — a request that
    could name the endpoint could redirect the server's own key to it).

    Deliberately not exported. It is read across the package by
    `api/model_resolution`, which is one home for the knowledge rather than
    two copies of the suffix list — but nothing outside needs it, and a
    security fix should not widen the public surface as a side effect.
    """
    return name.upper().endswith(_SECRET_SUFFIXES)


#: Fixed width, so the mask never reveals how long the value was. A
#: proportional one leaks real entropy; four asterisks leak none.
HINT_MASK = "****"

#: How many leading characters a hint keeps. Two, on the owner's decision
#: (the-editor-makes-a-real-package ticket 04, asked twice). Nearly free: every
#: Anthropic and OpenAI key begins `sk`, so the revealed prefix is the part an
#: attacker already knows — while it is enough for a person to see that *a* key
#: is there, which is what was asked for.
#:
#: Module-level rather than class attributes: `ProviderSpec` is a frozen
#: dataclass, so a class attribute with a default becomes a *field* and changes
#: a Tier 1 public signature.
HINT_PREFIX = 2


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

    #: Environment variables that make this provider usable, most significant
    #: first. **Any one of them is enough** — see `is_configured` — so a vendor
    #: reachable two ways lists both, and the first is the one an error message
    #: tells a developer to set. Empty means the provider needs no credential
    #: from us at all; no built-in declares that, but a plugin may.
    env_vars: tuple[str, ...] = ()

    #: Further model-string prefixes that belong to this provider's extra.
    #: `claude:` and `azure_openai:` are the two that exist, and neither is a
    #: provider in its own right.
    aliases: tuple[str, ...] = ()

    #: Variables naming this provider's API endpoint, **most significant
    #: first** — the same idiom as `env_vars`, so precedence is tuple order
    #: rather than a rule written down somewhere else. Empty means the vendor's
    #: own SDK default is correct and we should not interfere.
    endpoint_env: tuple[str, ...] = ()

    #: The endpoint used when none of `endpoint_env` is set. Empty means "let
    #: the SDK decide", which is not the same as a URL we happen to agree with:
    #: declaring one is how a provider overrides a *wrong* SDK default.
    default_endpoint: str = ""

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

    def key_hint(self, env: Mapping[str, str] | None = None) -> str | None:
        """A glance at what configured this, or `None` when nothing did.

        A **secret** variable is reduced to its first two characters and a
        fixed mask. A **non-secret** one is shown whole: `OLLAMA_HOST` is a
        URL, and masking it would hide the single thing a developer debugging
        a mount needs to read.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        for name in self.env_vars:
            value = str(source.get(name) or "").strip()
            if not value:
                continue
            if not _is_secret(name):
                return _without_userinfo(value)
            return value[:HINT_PREFIX] + HINT_MASK
        return None

    def base_url(self, env: Mapping[str, str] | None = None) -> str | None:
        """This provider's endpoint, or `None` to leave the SDK's default alone.

        Ollama is why this exists, and it is worth stating because the two
        variables look interchangeable and are not:

        - `OLLAMA_HOST` — *where my Ollama is*. A daemon the developer runs.
        - `OLLAMA_ENDPOINT` — *where the cloud is*. Defaulted, rarely set.

        Host first, so a developer who runs a daemon gets it without having to
        also clear the cloud endpoint. With neither set, `default_endpoint`
        sends the request to the cloud rather than to `localhost:11434`, which
        is what `ollama.Client` would otherwise choose — and a silent localhost
        default is how "Ollama means cloud, never local" was being violated by
        omission.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        for name in self.endpoint_env:
            value = str(source.get(name) or "").strip()
            if value:
                return value
        return self.default_endpoint or None

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
        """The exact fix, for a provider named but not configured (ticket 03).

        **Names every variable that would work, not just the first.** While
        each provider had one, naming `primary_env_var` was the same thing; it
        stopped being so when Ollama gained a second way to be configured, and
        the message then told a developer running their own daemon to go and
        get a cloud key (providers-and-credentials ticket 04).
        """
        if not self.env_vars:  # pragma: no cover - keyless providers never fail this way
            return f'Provider "{self.name}" needs no key.'
        variables = " or ".join(self.env_vars)
        return (
            f'Provider "{self.name}" has no credential — '
            f"set {variables} in .env (see .env.example)."
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
            # **Two ways to be configured, and `is_configured`'s `any()` gives
            # the rule for free.** `OLLAMA_API_KEY` alone reaches the cloud via
            # `OLLAMA_ENDPOINT`; `OLLAMA_HOST` alone reaches a local or
            # self-hosted daemon that owns its own auth. Either is enough.
            #
            # This used to be `env_vars=()`, which made Ollama *always*
            # configured. That was not keyless, it was **ambient**: it reached
            # the cloud through a local daemon signing with
            # `~/.ollama/id_ed25519` — a credential that never passes through
            # the environment and cannot be seen, moved or revoked from one.
            # The key is listed first so `missing_key_message` names it: the
            # host path is the one you opt into by naming a host.
            env_vars=("OLLAMA_API_KEY", "OLLAMA_HOST"),
            # Host first — a developer running a daemon should not also have to
            # clear the cloud endpoint. With neither set this sends the request
            # to the cloud; `ollama.Client` would otherwise default to
            # `127.0.0.1:11434`, which is how "cloud, never local" was being
            # violated by omission rather than by decision.
            endpoint_env=("OLLAMA_HOST", "OLLAMA_ENDPOINT"),
            default_endpoint="https://ollama.com",
        ),
    )


#: Variables a provider accepts but does not require, and so cannot declare in
#: `env_vars` without becoming one of the things that makes it configured.
#: Ollama is the only case: `OLLAMA_ENDPOINT` says *where the cloud is*, and it
#: has a working default, so setting it can never be what makes the provider
#: usable — but a run request may still override it.
OPTIONAL_ENV_VARS: dict[str, tuple[str, ...]] = {
    "ollama": ("OLLAMA_ENDPOINT",),
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
        # "Required" is only true when there is one of them. `is_configured`
        # takes *any* of `env_vars`, so a vendor reachable two ways — Ollama by
        # key or by host — must not print two lines each headed "Required", or
        # a developer pointing at their own daemon concludes they also need a
        # cloud key.
        if len(spec.env_vars) > 1:
            joined = " or ".join(spec.env_vars)
            lines.append(
                f"# Required for {spec.name}: set one of {joined} — "
                "with none of them this provider is skipped."
            )
        for name in spec.env_vars:
            if len(spec.env_vars) == 1:
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


def redact_known_secrets(text: str, catalogue: "ProviderCatalogue | None" = None) -> str:
    """Replace any configured credential value appearing in `text` with its hint.

    A vendor's own exception sometimes quotes the key back — OpenAI's 401 does,
    masked; others do not bother masking. Everything this project prints is
    supposed to be safe to paste into an issue, and that promise cannot depend
    on every vendor choosing to redact for us.

    Only *secret* variables are replaced. A host or an endpoint is an address,
    and blanking it out of an error would remove the one detail that explains
    the error.
    """
    if not text:
        return text
    cat = catalogue if catalogue is not None else provider_catalogue()
    for spec in cat.list():
        for name in spec.env_vars:
            if not _is_secret(name):
                continue
            value = os.environ.get(name, "").strip()
            if len(value) >= 8 and value in text:
                text = text.replace(value, value[:HINT_PREFIX] + HINT_MASK)
    return text


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
