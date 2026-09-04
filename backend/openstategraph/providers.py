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
The bundled providers are plain `ProviderSpec` values pushed through the
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

import importlib.util
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from openstategraph._extras import install_hint

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
    must never be *shown* (`ProviderEnvironment.key_hint` masks it), and an address must never be
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
class ProviderArgument:
    """One constructor keyword a vendor needs, and where its value comes from.

    **The third vocabulary, and the one that was missing.** A spec could say
    what a provider's *credential* is (`env_vars`) and what its *address* is
    (`endpoint_env`), and had no way at all to say that a vendor's constructor
    takes a required keyword — so a provider needing one could not be
    expressed, and adopting it meant editing this library or duplicating
    variables under names it happens to read (providers-and-credentials/18).

    Azure OpenAI is the first bundled vendor that needs this, and it needs
    three. The shape was checked against two others before it was settled,
    because a field shaped around one vendor is a field shaped around nothing:
    `bedrock`/`bedrock_converse` want a region and `google_vertexai` wants a
    project and a location, and all three are the same sentence — *a keyword,
    filled from an environment variable somebody sets*.

    **What is deliberately absent is a class name.** The other half of the
    obvious widening — *which class in the integration module* — has no
    reader: `init_chat_model` carries its own `provider -> (module, class)`
    table (`azure_openai -> langchain_openai.AzureChatOpenAI`,
    `bedrock -> langchain_aws.ChatBedrock`), and this project is a compiler
    onto that function rather than a second one. A field nothing reads is a
    claim nothing can check.

    **Never a secret.** Every value here is passed as a keyword and could be
    read back off the constructed object; a credential belongs in `env_vars`,
    where the masking and the request allow-list already live, and is left for
    the vendor's own SDK to read out of the environment. Refused in
    `__post_init__` rather than merely asked for, so the field cannot become
    the way round the config loader's own refusal of key-shaped values.
    """

    #: The keyword `init_chat_model` forwards to the vendor's constructor.
    keyword: str

    #: Variables that supply it, **most significant first** — the same idiom
    #: as `env_vars` and `endpoint_env`, so precedence is tuple order rather
    #: than a rule written down somewhere else. Azure's api-version lists
    #: `AZURE_OPENAI_API_VERSION` before the vendor's own `OPENAI_API_VERSION`:
    #: the first is the name a person setting Azure up reaches for, and the
    #: second is the one they should never have had to invent.
    env_vars: tuple[str, ...]

    #: Whether the provider can be called without it. A required argument with
    #: no source leaves the provider unconfigured and is named in the gap; an
    #: optional one is simply omitted and the vendor's own default stands.
    required: bool = True

    def __post_init__(self) -> None:
        if not self.keyword:
            raise ValueError("a provider argument declares no keyword")
        if not self.env_vars:
            raise ValueError(f"argument {self.keyword!r} names no environment variable")
        secret = [name for name in self.env_vars if _is_secret(name)]
        if secret:
            raise ValueError(
                f"argument {self.keyword!r} would carry a secret through {secret[0]} — "
                "a credential belongs in env_vars, where it is masked and never "
                "forwarded from a request"
            )

    @property
    def variables(self) -> str:
        """Every variable that would supply it, as one readable phrase."""
        return " or ".join(self.env_vars)


@dataclass(frozen=True)
class ProviderSpec:
    """One vendor, as much as this framework needs to know about it.

    Deliberately *data*, not a class to subclass: everything here is a value
    `init_chat_model`, a `.env` file or an error message needs, and none of it
    is behaviour. A vendor that needed behaviour would need a client, and
    shipping vendor clients is explicitly out of scope (map.md).

    **And it is now true of the members as well as the fields**
    (install-experience 20). Every member below derives from this record's own
    fields — a property whose whole implementation you can read in one line —
    which is what makes it a record rather than an object that happens to be
    frozen. The six that asked the *machine* instead (`is_configured`,
    `is_installed`, `key_hint`, `base_url`, `model_string`, `readiness`) are
    `ProviderEnvironment` now. `test_provider_registry.py` holds the line by
    reading this class's own source and refusing to find the environment or
    the import machinery named in it.
    """

    #: The `init_chat_model` prefix — the `anthropic` in `anthropic:claude-…`.
    name: str

    #: The model used when this provider is chosen with nothing more specific
    #: asked for. Bare (no prefix); `ProviderEnvironment.model_string` adds the
    #: prefix.
    default_model: str

    #: The `pip install 'openstategraph[…]'` extra supplying its LangChain
    #: integration package.
    extra: str

    #: Environment variables that make this provider usable, most significant
    #: first. **Any one of them is enough** — see
    #: `ProviderEnvironment.is_configured` — so a vendor reachable two ways
    #: lists both, and the first is the one an error message tells a developer
    #: to set. Empty means the provider needs no credential from us at all; no
    #: built-in declares that, but a plugin may.
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

    #: The module `init_chat_model` imports to reach this vendor —
    #: `langchain_ollama` for Ollama. Declared rather than derived from `extra`,
    #: because deriving it is right for the bundled set and wrong for anyone
    #: else: `langchain-nvidia-ai-endpoints` is not `langchain_nvidia`.
    #:
    #: Empty means **we cannot pre-check this provider**, and that is a
    #: supported answer rather than a gap — see
    #: `ProviderEnvironment.is_installed`. Everything the readiness check does
    #: depends on this being honest, so a spec that declares nothing gets
    #: `init_chat_model`'s own ImportError, which names the package it actually
    #: failed on (workflow-gallery ticket 38).
    integration_module: str = ""

    #: Keywords this vendor's constructor needs that no `provider:model` string
    #: can carry — Azure's endpoint, deployment and api-version. **Empty by
    #: default, and empty for every provider that existed before this field**,
    #: so `resolveMiddleware`-style composition is unchanged for anthropic,
    #: openai, ollama and every plugin written against the older signature.
    #:
    #: The field is what stops "adopting this needs a fork" being the answer:
    #: the arguments are declared beside the credential and the endpoint, in
    #: one record, and `chat_model.model_kwargs` is the single place they
    #: become an `init_chat_model` call.
    constructor_args: tuple[ProviderArgument, ...] = ()

    #: Keywords this vendor's constructor is always given, as `(keyword, value)`
    #: pairs. Constants — nothing here reads the environment, which is the
    #: difference from `constructor_args` above: that field asks *what does
    #: this machine supply*, this one states *what does this API require of
    #: everyone*.
    #:
    #: `stream_usage=True` for the OpenAI family is the case it was added for
    #: (`stable-beta-public/03`). Chat completions report streamed token usage
    #: only when the caller opts in, and `langchain_openai`'s own default for
    #: the opt-in depends on whether a base URL is configured — so a machine
    #: pointing `OPENAI_BASE_URL` at a gateway silently stopped reporting what
    #: its runs cost. Stating it here makes the opt-in ours rather than a
    #: library default that has already moved twice.
    #:
    #: **The cost, recorded rather than hidden:** an OpenAI-compatible proxy
    #: that rejects `stream_options` is now sent it. That is the same trade
    #: `langchain_openai` made in the other direction, and there is no
    #: environment variable to turn it off today; a proxy that needs one is a
    #: ticket, not a silent default.
    constructor_defaults: tuple[tuple[str, Any], ...] = ()

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
        return (
            f'Provider "{self.name}" has no credential — '
            f"set {self.credential_variables} in .env "
            f"(see `openstategraph env-example`)."
        )

    @property
    def credential_variables(self) -> str:
        """Every variable that would configure this, as one readable phrase.

        The knowledge — *any one of `env_vars` is enough* — is stated once
        here, so the two messages that quote it cannot come to disagree about
        whether a developer running their own daemon also needs a cloud key.
        """
        return " or ".join(self.env_vars)

    @property
    def install_hint(self) -> str:
        """The exact `pip install` line for this provider's integration."""
        return install_hint(self.extra)

    def missing_package_message(self) -> str:
        """The exact fix when the integration package is absent (ticket 38).

        Written to sit beside `missing_key_message` in the same voice and on
        the same one line — the two are the same event from the reader's seat
        ("I cannot talk to my model"), and the vendor's own
        `Initializing ChatOllama requires…` sentence is dropped rather than
        appended, exactly as `credential_error_from` drops a vendor's 401 text.
        """
        return (
            f'Provider "{self.name}" integration is not installed — '
            f"{self.install_hint}."
        )


@dataclass(frozen=True)
class ProviderGap:
    """Why a provider cannot be called on this machine, as one sentence.

    A value, not an exception: `providers.py` is the catalogue and knows the
    *copy*, while `chat_model` is the seam that decides what to raise. Keeping
    the two apart is why importing the provider list still costs four stdlib
    modules.
    """

    spec: ProviderSpec
    missing_package: bool
    missing_key: bool

    #: Required constructor arguments with no variable to fill them. A
    #: **third** wall, kept apart from `missing_key` rather than folded into
    #: it, because the two send a reader to different places: the key is
    #: present and correct in the case this field exists for, and a message
    #: saying "no credential" would send them to check the one thing that is
    #: already right (providers-and-credentials/18).
    missing_arguments: tuple[ProviderArgument, ...] = ()

    @property
    def argument_clause(self) -> str:
        """Every unfilled argument, named by variable, as one phrase."""
        return " and ".join(argument.variables for argument in self.missing_arguments)

    @property
    def message(self) -> str:
        """One line, naming every fix — never the first one discovered.

        The combined form leads with the package, because that is the wall
        that survives setting a variable, and a reader who fixes in that order
        never sees this message twice. The argument clause joins on the same
        rule: three walls, one sentence, one trip.
        """
        if self.missing_package and self.missing_key:
            return (
                f'Provider "{self.spec.name}" is not ready — its integration is not '
                f"installed ({self.spec.install_hint}) and it has no credential "
                f"(set {self.spec.credential_variables} in .env)."
                + (
                    f" It also needs {self.argument_clause} in .env."
                    if self.missing_arguments
                    else ""
                )
            )
        if self.missing_package:
            return self.spec.missing_package_message()
        if self.missing_key:
            return self.spec.missing_key_message()
        return (
            f'Provider "{self.spec.name}" has a credential but is not configured — '
            f"set {self.argument_clause} in .env "
            "(see `openstategraph env-example`). This is a missing setting rather "
            "than a missing or wrong credential: without it the provider's own "
            "client refuses to be built at all."
        )


@dataclass(frozen=True)
class ProviderEnvironment:
    """One provider **as this machine has it set up** — the half that is not data.

    `ProviderSpec` is a record: every member of it derives from its own fields,
    and none of them imports anything. Six members used to break that. They
    reached `os.environ` and `importlib`, which meant a frozen dataclass could
    not be exercised without arranging an environment first, and meant the same
    object answered both *"what is Anthropic"* and *"can I call it from here"* —
    two questions with different reasons to change, since the first moves when a
    vendor does and the second moves when a machine does (install-experience 20).

    `ProviderGap` was already the result type of the probing half, so the seam
    was half drawn; this is the other half of it.

    **`env` defaults to `None`, meaning the real process environment.** Passing
    a mapping is the whole point of the split — a test states the machine it is
    describing instead of mutating the one it is running on.
    """

    spec: ProviderSpec
    #: The environment to read. `None` is `os.environ`, resolved per call rather
    #: than captured at construction, so one of these held by a long-lived
    #: object still sees a credential set after it was built.
    env: Mapping[str, str] | None = None

    @property
    def _source(self) -> Mapping[str, str]:
        return os.environ if self.env is None else self.env

    def has_credential(self) -> bool:
        """Whether a variable this provider calls a key holds a value.

        Split out of `is_configured`, which used to be exactly this and is now
        the conjunction below. The two questions were the same while every
        provider was reachable on a credential alone; Azure is reachable on a
        credential **and** three settings, so a single method answering both
        had to lie about one of them (providers-and-credentials/18).

        This is the half `credential_source`, `/api/providers`'
        `configured_by` and `missing_key_message` are about — *is there a key*
        — and it must stay narrow, or a machine with a perfectly good key
        would be told to go and find one.
        """
        if not self.spec.requires_key:
            return True
        return any(str(self._source.get(name) or "").strip() for name in self.spec.env_vars)

    def argument_values(self) -> dict[str, str]:
        """The `init_chat_model` keywords this environment can supply.

        Precedence is tuple order, read rather than restated — the same rule
        `_endpoint_source` follows. An argument nothing supplies is **absent
        from the dict** rather than present and empty: passing `api_version=""`
        would defeat the vendor's own default and turn an optional argument
        into a broken one.
        """
        resolved: dict[str, str] = {}
        for argument in self.spec.constructor_args:
            for name in argument.env_vars:
                value = str(self._source.get(name) or "").strip()
                if value:
                    resolved[argument.keyword] = value
                    break
        return resolved

    def _missing_arguments(self) -> tuple[ProviderArgument, ...]:
        """Required constructor arguments no variable here fills.

        Private, and that is the public-surface ceiling doing its job rather
        than a name chosen to duck it: `readiness()` is how anything outside
        asks, and the answer it hands back carries the very same tuple on
        `ProviderGap.missing_arguments`. A second public spelling of one fact
        would have taken this class to eleven members for nothing.
        """
        supplied = self.argument_values()
        return tuple(
            argument
            for argument in self.spec.constructor_args
            if argument.required and argument.keyword not in supplied
        )

    def is_configured(self) -> bool:
        """Whether this provider could be called right now.

        **Both halves, because both are walls.** A credential with an unfilled
        required argument is the shape that produced a 500 with a pydantic
        traceback: the key was set, every readiness surface said so, and the
        vendor's constructor refused before a request was ever sent. Reporting
        that as configured is `providers-and-credentials/12`'s defect one field
        along — a surface claiming more than it measured.

        Unchanged for every provider that declares no arguments, which is
        every provider that existed before this line.
        """
        return self.has_credential() and not self._missing_arguments()

    def is_installed(self) -> bool:
        """Whether this provider's integration package is importable.

        `find_spec`, not `import_module`: this is asked on the path of every
        run and on `openstategraph providers`, and importing three vendor SDKs
        to discover that all three are present would undo the lean core the
        extras exist to protect.

        **True for a provider that declares no `integration_module`.** The
        question this answers is "do we know of a reason this cannot work",
        and for an undeclared module we do not — so the honest answer is to
        step aside and let `init_chat_model` fail with the package name it
        actually reached for.
        """
        if not self.spec.integration_module:
            return True
        try:
            return importlib.util.find_spec(self.spec.integration_module) is not None
        except (ImportError, ValueError):  # pragma: no cover - a broken parent package
            return False

    def credential_source(self) -> tuple[str, str] | None:
        """The variable that actually configured this, and a safe glance at it.

        `None` when nothing did. The **name** is the half a reader can act on
        and the half that was missing everywhere it mattered: `is_configured`
        is `any(env_vars)`, so Ollama is configured by its cloud key *or* by
        `OLLAMA_HOST`, and naming the first would send a developer running
        their own daemon to go and get a key they do not need.

        Split out of `key_hint` for the same reason `_endpoint_source` was
        split out of `base_url`: the precedence is *knowledge*, `/api/providers`
        needs the winning variable's name while a masked glance is all the
        editor may see, and two readings of one rule get one implementation.
        `/api/providers` had a third copy of this loop written inline against
        `os.getenv`, which is how a route ends up describing a machine other
        than the one a `ProviderEnvironment` was handed.

        A **secret** variable is reduced to its first two characters and a
        fixed mask. A **non-secret** one is shown whole: `OLLAMA_HOST` is a
        URL, and masking it would hide the single thing a developer debugging
        a mount needs to read.
        """
        for name in self.spec.env_vars:
            value = str(self._source.get(name) or "").strip()
            if not value:
                continue
            if not _is_secret(name):
                return name, _without_userinfo(value)
            return name, value[:HINT_PREFIX] + HINT_MASK
        return None

    def key_hint(self) -> str | None:
        """A glance at what configured this, or `None` when nothing did."""
        source = self.credential_source()
        return None if source is None else source[1]

    def base_url(self) -> str | None:
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
        source = self._endpoint_source()
        if source is not None:
            return source[1]
        return self.spec.default_endpoint or None

    def _endpoint_source(self) -> tuple[str, str] | None:
        """The variable that supplied this endpoint, and its value.

        `None` when nothing did and `default_endpoint` is what will be used.
        Split out of `base_url` rather than duplicated beside it because the
        precedence — tuple order, host before endpoint — is *knowledge*, and
        the message below needs the winning variable's **name** while the
        model builder needs only its value. Two readings of one rule, one
        implementation.
        """
        for name in self.spec.endpoint_env:
            value = str(self._source.get(name) or "").strip()
            if value:
                return name, value
        return None

    def unreachable_endpoint_message(self, url: str) -> str:
        """The address is configured and nothing is listening at it.

        The **fourth** shape, and Ollama's alone, because Ollama is the only
        provider whose address is a variable a developer types: absent, wrong
        and valid were the three ticket 03 enumerated, and a host set to a
        daemon that is not running is none of them. It arrived as
        `httpx.ConnectError: [Errno 61] Connection refused` — a sentence that
        names no provider, no variable and no fix
        (providers-and-credentials 08).

        Written in the same voice and on the same one line as
        `missing_key_message` and `missing_package_message`, and it says what
        it is *not* as well as what it is: *not a missing or wrong credential*
        is the whole reason this shape needed words of its own, since those
        two are what a developer will otherwise go and check.

        **The variable named is the one that actually supplied the address.**
        Naming `OLLAMA_HOST` to somebody who set `OLLAMA_ENDPOINT` sends them
        to edit a variable that is not in play — the precedence is tuple
        order and this reads it rather than restating it. With neither set the
        address is our default, so there is no variable to blame and the
        message offers the ones that would move it instead.
        """
        where = _without_userinfo(url)
        source = self._endpoint_source()
        if source is None:
            return (
                f'Provider "{self.spec.name}" could not be reached at {where} — '
                "nothing accepted a connection at its default endpoint. This is an "
                "unreachable endpoint rather than a missing or wrong credential: "
                f"check network access, or set {' or '.join(self.spec.endpoint_env)} "
                "to an address that is running."
            )
        variable = source[0]
        fallback = (
            f" (unset {variable} to fall back to {self.spec.default_endpoint})"
            if self.spec.default_endpoint
            else ""
        )
        return (
            f'Provider "{self.spec.name}" could not be reached at {where} — the address '
            f"is configured ({variable}) but nothing is listening there, so the "
            "connection was refused. This is an unreachable endpoint rather than a "
            f"missing or wrong credential: start the service at that address, or point "
            f"{variable} at one that is running{fallback}."
        )

    def model_string(self) -> str:
        """The full `provider:model` string, honouring the model env var."""
        name = self.spec.name
        override = str(self._source.get(self.spec.model_env_var) or "").strip()
        if override:
            # An override may be written either bare or already prefixed; both
            # spellings appear in the wild and neither is wrong.
            return override if override.startswith(f"{name}:") else f"{name}:{override}"
        return f"{name}:{self.spec.default_model}"

    def readiness(self) -> ProviderGap | None:
        """Everything standing between this provider and a model call.

        `None` when nothing does. Both checks are evaluated, never
        short-circuited: the whole of ticket 38 is that answering with the
        first wall you hit sends a developer round the loop once per wall.
        """
        gap = ProviderGap(
            spec=self.spec,
            missing_package=not self.is_installed(),
            # `has_credential`, not `is_configured` — the latter is now the
            # conjunction, so asking it here would report a missing key on a
            # machine whose key is present and whose api-version is not.
            missing_key=self.spec.requires_key and not self.has_credential(),
            missing_arguments=self._missing_arguments(),
        )
        return gap if gap.missing_package or gap.missing_key or gap.missing_arguments else None


@dataclass(frozen=True)
class ProviderDefault:
    """Which provider a run uses when nothing named one, **and why**.

    A value rather than a bare `ProviderSpec | None`, because the reason is
    read as often as the answer: `openstategraph providers` prints it, and it
    is the difference between *"why is it not using my key"* answered and
    guessed at. The sentence is composed once, here, so the CLI cannot invent
    a second wording (install-experience T2/T3).
    """

    #: The elected provider, or `None` when no integration is installed.
    spec: ProviderSpec | None
    #: The full `provider:model` string, or `None` with no election.
    model: str | None
    #: One clause, lower case, no full stop — it is printed after a dash.
    reason: str
    #: Whether the elected provider can be **called** right now. False is a
    #: real election: the extra chose the vendor and only the key is missing.
    configured: bool = False


@dataclass
class ProviderCatalogue:
    """Every known provider, in registration order.

    Order is the documented tiebreak, and it is meaningful only among
    providers that are installed *and* equally configured — see
    `elected_default`.
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

    def install_choices(self) -> str:
        """Every `pip install` line that would give this install a provider.

        One phrase, one owner. `cli.no_provider_warning`, `elected_default`'s
        no-candidate reason and `resolve_model`'s refusal all print it, and
        three copies of a sentence is three chances to fix two of them.
        """
        lines = [spec.install_hint for spec in self._specs.values()]
        if not lines:
            return "(no provider is registered at all)"
        return lines[0] if len(lines) == 1 else ", ".join(lines[:-1]) + f" or {lines[-1]}"

    def no_provider_message(self) -> str:
        """The one sentence for an install that can run nothing at all."""
        return (
            "no model provider integration is installed, so every run will fail — "
            f"{self.install_choices()}, then start again"
        )

    def elected_default(self, env: Mapping[str, str] | None = None) -> ProviderDefault:
        """The provider to use when nothing more specific was asked for.

        **The one rule, in the one place** (install-experience T2). Until this,
        `resolve_model` reimplemented the choice and this method carried the
        reasoning with no production caller — on a bare machine one answered
        `ollama:gpt-oss:120b-cloud` and the other answered `None`.

        Two signals, in different roles, and neither alone:

        - `is_installed()` is **candidacy**, a hard filter. Electing a
          provider that cannot be imported is electing a failure we have
          already detected — and, worse, sending the reader to a `pip install`
          line for a vendor they did not choose. An `[openai]` install with a
          stale `ANTHROPIC_API_KEY` exported by some other tool used to be told
          to install `[anthropic]`.
        - `is_configured()` is the **election**, ranking the candidates.
          Installed-only would ignore a key that is actually present.
        - Registration order is the **tiebreak**, as `builtin_specs` documents.

        Three passes, and the middle one is the rule this method has always
        carried: a *configured* key-requiring provider beats a keyless one
        whatever the order, or a keyless plugin registered early would make
        every later vendor unreachable by default however correctly its key was
        set. A keyless provider in turn beats a candidate that is installed and
        **not** configured, because it can actually be called.

        The last pass is what makes the install line a mental model:
        `pip install 'openstategraph[anthropic]'` with no key at all still
        elects Anthropic, so the single remaining wall names *their* vendor's
        variable instead of listing three strangers.
        """
        here = {spec.name: ProviderEnvironment(spec, env) for spec in self._specs.values()}
        candidates = [spec for spec in self._specs.values() if here[spec.name].is_installed()]
        if not candidates:
            return ProviderDefault(None, None, self.no_provider_message())

        ready = [spec for spec in candidates if here[spec.name].is_configured()]
        keyed = [spec for spec in ready if spec.requires_key]
        elected = keyed[0] if keyed else (ready[0] if ready else candidates[0])
        return ProviderDefault(
            spec=elected,
            model=here[elected.name].model_string(),
            reason=_default_reason(candidates, ready, elected, here[elected.name]),
            configured=any(spec is elected for spec in ready),
        )


def _default_reason(
    candidates: list[ProviderSpec],
    ready: list[ProviderSpec],
    elected: ProviderSpec,
    here: "ProviderEnvironment",
) -> str:
    """Why that provider, in one clause a person can act on.

    Four shapes, because four situations need different next steps: nothing to
    do, set a key, or stop the tiebreak from deciding for you. The
    more-than-one cases name the alternatives, because a default nobody can
    see is the *"why is it not using my key"* question this text exists to
    pre-empt.

    **It says "has a credential", never "configured", and that is the fix for
    providers-and-credentials 12.** This clause is the header of
    `openstategraph providers`, and it read *"3 integrations installed and
    configured"* on the strength of `is_configured()` — which asks whether a
    variable is set and cannot ask whether a request would be answered. A
    supervisor session read it as a verdict on running and acted on that. The
    count is the same count; only the claim narrowed to what was measured.
    """
    installed = len(candidates)
    configured = any(spec is elected for spec in ready)
    if not configured:
        # **What is actually missing, not what is usually missing.** A provider
        # can be unconfigured with its key set and correct — Azure needs an
        # endpoint and an api-version too — and telling that reader to set the
        # key sends them to check the one thing already right. The gap knows
        # which wall this is; this line reads it rather than assuming
        # (providers-and-credentials/18).
        gap = here.readiness()
        if gap is not None and not gap.missing_key and gap.missing_arguments:
            variables = gap.argument_clause
        else:
            variables = elected.credential_variables or "its credential"
        if installed == 1:
            return f"the only provider integration installed; set {variables} to use it"
        return (
            f"{installed} integrations installed and none configured; "
            f"set {variables} to use {elected.name}"
        )
    if installed == 1:
        return "the only provider integration installed, and it has a credential"
    if len(ready) == 1:
        return (
            f"the only one of {installed} installed integrations "
            "that has a credential"
        )
    names = ", ".join(spec.name for spec in ready)
    return (
        f"{len(ready)} of {installed} installed integrations have a credential "
        f"({names}); the first registered wins. Pin one with default_model: in "
        "openstategraph.yaml"
    )


def builtin_specs() -> tuple[ProviderSpec, ...]:
    """The bundled set — plain specs, no privileged type or field.

    Registration order is the historical default order and is preserved
    deliberately: a developer with both an Anthropic and an OpenAI key keeps
    getting Anthropic, exactly as before this module existed.

    **Azure is appended rather than filed beside OpenAI**, for that same
    reason and for no other. Order is the election tiebreak, so inserting a
    fourth vendor between two existing ones changes which provider a machine
    configured for both of them elects — a behaviour change nobody asked for,
    smuggled in with one that was. Last costs nothing: a machine configured
    only for Azure elects Azure whatever the position, because a configured
    key-requiring provider beats an unconfigured one before order is consulted
    at all.
    """
    return (
        ProviderSpec(
            name="anthropic",
            label="Anthropic",
            default_model="claude-haiku-4-5",
            extra="anthropic",
            integration_module="langchain_anthropic",
            env_vars=("ANTHROPIC_API_KEY",),
            aliases=("claude",),
        ),
        ProviderSpec(
            name="openai",
            label="OpenAI",
            default_model="gpt-4.1-mini",
            extra="openai",
            integration_module="langchain_openai",
            env_vars=("OPENAI_API_KEY",),
            # Streamed usage is opt-in on chat completions; see the field.
            constructor_defaults=(("stream_usage", True),),
            # `aliases=("azure_openai",)` used to sit here, and removing it is
            # the fix rather than a breaking change. An alias means *another
            # spelling of this provider*, and it was never that: it resolved
            # `azure_openai:` to a spec whose credential is `OPENAI_API_KEY`
            # and whose constructor is `ChatOpenAI`, so a service configured
            # for Azure was answered by the wrong class reading the wrong
            # variable. The **word survives** — `azure_openai` is a registered
            # provider below, `for_prefix` finds it by name before it looks at
            # anybody's aliases, and every string anyone typed keeps working.
            # What changed is that it now means what it says
            # (providers-and-credentials/18).
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
            integration_module="langchain_ollama",
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
        ProviderSpec(
            name="azure_openai",
            label="Azure OpenAI",
            # OpenAI models, deployed into somebody's own tenancy. The
            # `default_model` is the model *name*; what actually selects the
            # thing being called is `azure_deployment`, which is a customer's
            # own string and so can only come from their environment.
            default_model="gpt-4.1-mini",
            # Ships inside `langchain-openai` — `AzureChatOpenAI` is a sibling
            # of `ChatOpenAI` in the same package — so this is not a fourth
            # extra and an `[openai]` install already has it.
            extra="openai",
            integration_module="langchain_openai",
            # **Its own credential vocabulary.** `AZURE_OPENAI_API_KEY` is the
            # name the Azure portal prints and the name a person can rotate
            # there; `OPENAI_API_KEY` is a different vendor's key for a
            # different endpoint, and the two are not interchangeable however
            # much the SDK will accept either.
            env_vars=("AZURE_OPENAI_API_KEY",),
            # The same API behind a different door, so the same opt-in. Stated
            # on each spec rather than derived from `integration_module`: two
            # providers sharing a package is not a promise they share a
            # constructor, and `AzureChatOpenAI` accepting it is asserted
            # against the class in `test_chat_model.py`.
            constructor_defaults=(("stream_usage", True),),
            # **The key is not among these, and that is deliberate.** Azure's
            # own client reads `AZURE_OPENAI_API_KEY` from the environment,
            # so declaring it here would put a secret into a keyword dict for
            # no gain. It stays in `env_vars`, where it is masked, where
            # `credential_source` names it, and where the request allow-list
            # governs it.
            #
            # Endpoint and deployment are declared even though the SDK would
            # read the first itself: an ambient read is a value nothing can
            # report as missing, which is the omission the Ollama correction
            # in CLAUDE.md is about. Declared, they are named in the gap.
            constructor_args=(
                ProviderArgument("azure_endpoint", ("AZURE_OPENAI_ENDPOINT",)),
                ProviderArgument(
                    "api_version",
                    # This tuple *is* the reported defect. The vendor reads
                    # only the second; a person setting Azure up writes the
                    # first, and had to duplicate it under a name belonging to
                    # another vendor to be heard.
                    ("AZURE_OPENAI_API_VERSION", "OPENAI_API_VERSION"),
                ),
                ProviderArgument(
                    "azure_deployment",
                    ("AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_DEPLOYMENT_NAME"),
                    # Optional, and checked rather than assumed: a resource
                    # addressed at its non-deployment endpoint is a real setup
                    # and requiring this would refuse it. An absent deployment
                    # is omitted from the call, not passed empty.
                    required=False,
                ),
            ),
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
        # A constructor argument is the third kind of variable this file has to
        # name, and the reason the whole ticket exists: a value the vendor's
        # client cannot be built without, which nothing here had ever printed,
        # so the only way to discover it was a 500 (providers-and-credentials/18).
        # Every alternative is listed, most significant first, and only the
        # first is left uncommented — a file offering four `NAME=` lines for one
        # setting invites somebody to fill in two of them and wonder which won.
        for argument in spec.constructor_args:
            need = "Required" if argument.required else "Optional"
            alternatives = (
                f" Also read from {' then '.join(argument.env_vars[1:])}."
                if len(argument.env_vars) > 1
                else ""
            )
            lines.append(
                f"# {need} for {spec.name}: supplies the {argument.keyword!r} "
                f"argument its client is built with.{alternatives}"
            )
            lines.append(f"{argument.env_vars[0]}=")
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
    if spec is None or not spec.requires_key or ProviderEnvironment(spec).is_configured():
        return None
    return spec.missing_key_message()


def provider_readiness(model_string: str) -> ProviderGap | None:
    """Everything missing for the provider a model string names, else `None`.

    The superset of `missing_key_diagnosis`, and the one `build_chat_model`
    asks. `None` for an unknown prefix, for the same reason that one gives:
    `init_chat_model` already names the package it could not import, and a
    confidently wrong install line is worse than saying nothing.
    """
    spec = provider_catalogue().for_model(model_string)
    return None if spec is None else ProviderEnvironment(spec).readiness()


__all__ = [
    "ENV_EXAMPLE_BEGIN",
    "ENV_EXAMPLE_END",
    "OPTIONAL_ENV_VARS",
    "PROVIDERS_GROUP",
    "ProviderArgument",
    "ProviderCatalogue",
    "ProviderDefault",
    "ProviderEnvironment",
    "ProviderGap",
    "ProviderSpec",
    "builtin_specs",
    "credential_env_vars",
    "env_example_section",
    "load_provider_catalogue",
    "missing_key_diagnosis",
    "provider_catalogue",
    "provider_readiness",
    "reset_provider_catalogue",
]
