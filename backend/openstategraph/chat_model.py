"""The single place a model string becomes a chat model.

Three things have to happen between `"ollama:gpt-oss:120b-cloud"` and an object
you can call, and before this module they happened in different places or not at
all:

1. **The credential gate.** A named provider with no credential fails here with
   the exact fix, rather than raising the vendor SDK's own error — which names
   *its* environment variable and knows nothing about `openstategraph
   env-example`, so an adopter had to work out the two were the same thing.
2. **The endpoint.** `ProviderSpec.base_url` decides where the request goes.
   Without this, `ollama.Client` silently dialled `127.0.0.1:11434` — which is
   how "Ollama means cloud, never local" was violated by omission.
3. **The extras hint.** A missing integration package names our install line,
   not just the import that failed.

**Why a module and not a helper on `ProviderSpec`.** `providers.py` is a
catalogue: it imports `os`, `dataclasses` and `typing`, and nothing else. Giving
it a method that constructs a LangChain object would make importing the provider
list drag in the model layer, and the catalogue is imported by things that only
want to know what a prefix means.

**Why every caller must come through here.** Step 1 existed only in
`loader.py`, so the HTTP, MCP and per-node paths each called `init_chat_model`
directly and got the vendor's error instead of ours — the same "one behaviour,
several spellings" defect the provider catalogue was built to end
(providers-and-credentials ticket 02).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from openstategraph.errors import (
    MissingProviderKey,
    MissingProviderPackage,
    MissingProviderSetting,
    OpenStateGraphError,
    ProviderRefusedCredential,
    ProviderUnreachable,
)
from openstategraph.providers import (
    ProviderEnvironment,
    provider_catalogue,
    provider_readiness,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from langchain_core.language_models import BaseChatModel

    from openstategraph.providers import ProviderSpec


def model_kwargs(model_name: str) -> dict[str, Any]:
    """Extra `init_chat_model` arguments this model's provider asks for.

    Empty for a provider that declares neither an endpoint nor an argument, so
    Anthropic and OpenAI are passed exactly what they were passed before this
    existed. `None` from `base_url` means "the SDK's default is correct" and is
    deliberately not the same as passing a URL we believe to be that default.

    **The single place `constructor_args` becomes a call**
    (providers-and-credentials/18). A vendor whose constructor needs a keyword
    no `provider:model` string can carry — Azure's endpoint, deployment and
    api-version — declares it on its spec, and it arrives here. Nothing else in
    the package builds an `init_chat_model` argument, which is what keeps a
    second spelling of the same knowledge from growing on another surface.

    **The two do not collide.** `base_url` is Ollama's and `constructor_args`
    is Azure's; a spec declaring both would be naming one endpoint twice under
    two keywords, and the explicit one wins — a keyword a spec wrote out is
    more specific than one derived from `endpoint_env`.

    **`constructor_defaults` goes in first, and is overridden by everything
    else** (`stable-beta-public/03`). It is what this *API* requires of every
    caller — OpenAI's `stream_usage`, without which a streamed run reports no
    tokens at all — where the two above are what this *machine* supplies. A
    constant a machine can also name should lose to the machine, which is what
    the ordering says.
    """
    spec = provider_catalogue().for_model(model_name)
    if spec is None:
        return {}
    here = ProviderEnvironment(spec)
    kwargs: dict[str, Any] = dict(spec.constructor_defaults)
    base_url = here.base_url()
    if base_url:
        kwargs["base_url"] = base_url
    kwargs.update(here.argument_values())
    return kwargs


class UnconfiguredProvider:
    """Stands in for a model this machine cannot call, whatever is missing.

    **Why a stand-in rather than raising immediately.** A workflow with no
    model-calling node runs fine with no credentials at all, and that is a
    property worth keeping — `input.text → output.formatted` needs nobody's
    API key. Raising at construction took it away, because every run builds a
    model before it knows whether any node will ask for one.

    So the rule is: *a provider is required at the moment a model is used, not
    at the moment one is built*. Any attribute access raises, which covers
    `invoke`, `stream`, `bind_tools`, `with_structured_output` and anything
    else a node reaches for, while a run that never touches it is unaffected.

    **The error is a parameter, and that is workflow-gallery ticket 38.** A
    missing *credential* and a missing *integration package* are the same
    event from the reader's seat and used to arrive by different mechanisms —
    one deferred to first use, the other a LangChain traceback out of
    `load_workflow`. Both come through here now, so fixing the first cannot
    change the shape of the second.
    """

    __slots__ = ("_diagnosis", "_error")

    def __init__(
        self,
        diagnosis: str,
        error: type[OpenStateGraphError] = MissingProviderKey,
    ) -> None:
        self._diagnosis = diagnosis
        self._error = error

    def __getattr__(self, name: str) -> Any:
        raise self._error(self._diagnosis)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise self._error(self._diagnosis)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<UnconfiguredProvider: {self._diagnosis}>"


def build_chat_model(model_name: str) -> "BaseChatModel":
    """`provider:model` in, a callable model out — or an error that says why.

    **One pre-flight check, both walls.** A provider that has no credential
    *or* no integration package comes back as an `UnconfiguredProvider`
    carrying one line that names every fix, and raising on first use rather
    than at construction — see that class for why. Ticket 38: these were two
    checks in a fixed order, so a developer who set the key discovered the
    extra only on the next run, as a 34-line LangChain traceback.

    The `except` below is now the **undetectable** case only: a provider that
    declares no `integration_module`, or an integration that imports and then
    fails on something of its own. `init_chat_model`'s own error names the
    package it actually reached for, which is more than we could guess, so it
    is kept and our install line appended.
    """
    from langchain.chat_models import init_chat_model

    from openstategraph._extras import provider_extra_hint

    gap = provider_readiness(model_name)
    if gap is not None:
        # Three walls, three types, in the order a reader fixes them. The
        # third is providers-and-credentials/18: a credential that is present
        # and a constructor that still refuses is neither of the other two,
        # and typing it as a `CredentialError` would tell somebody to go and
        # replace a key that is correct.
        if gap.missing_package:
            error: type[OpenStateGraphError] = MissingProviderPackage
        elif gap.missing_key:
            error = MissingProviderKey
        else:
            error = MissingProviderSetting
        return UnconfiguredProvider(gap.message, error)  # type: ignore[return-value]

    try:
        return cast("BaseChatModel", init_chat_model(model_name, **model_kwargs(model_name)))
    except ImportError as exc:
        # Provider SDKs are extras (framework-packaging §3.1). The adopter
        # installed *us*, not `langchain-anthropic`, so name our install line
        # rather than leaving them to map a package to an extra.
        hint = provider_extra_hint(model_name)
        raise MissingProviderPackage(
            f"{exc} — model {model_name!r} needs its provider integration"
            + (f": {hint}" if hint else "")
        ) from exc


def verify_provider(here: ProviderEnvironment) -> str | None:
    """Make **one real call** to this provider. `None` if it answered.

    The only certain answer to *"will this run"*, and the reason it cannot be
    part of a status listing: it costs money and latency, so it belongs behind
    something a person opted into — `POST /api/providers/{name}/verify` in the
    editor, `openstategraph providers --check` on a terminal
    (providers-and-credentials 12).

    **One implementation, because it was about to be two.** The route had this
    inline; the CLI needed the same three steps — refuse early when no
    credential is set, send the smallest possible prompt, report the failure in
    the product's own words. Two spellings of one behaviour is the defect the
    provider catalogue itself was built to end, and a divergence here would
    mean the editor and the terminal disagreeing about whether a key works.

    The failure string never carries a stack trace and never carries the
    credential — `describe_failure` and `credential_error_from` between them
    are what keep that true, including for OpenAI's own masked fragment.
    """
    from openstategraph.compile.workflow_compiler import describe_failure

    # `has_credential`, not `is_configured`: refusing early is about *not
    # spending a call we know will fail*, and both of the things that make a
    # provider unconfigured qualify. The gap composes the sentence, so a
    # missing api-version reads as a missing setting rather than as a missing
    # key (providers-and-credentials/18).
    if not here.is_configured():
        gap = here.readiness()
        return gap.message if gap is not None else here.spec.missing_key_message()
    try:
        # The smallest thing that proves the credential is accepted. A single
        # token of output is all this needs to learn.
        build_chat_model(here.model_string()).invoke("hi")
    except Exception as exc:  # noqa: BLE001 — reported, never raised at a user
        return describe_failure(exc)
    return None


#: HTTP statuses that mean "your credential was read and refused".
#: 403 counts: a key valid for the vendor but not for *this model* is the same
#: action for the reader — look at the key and the account behind it.
_REFUSED = (401, 403)


def _providers_of(exc: BaseException) -> tuple["ProviderSpec", ...]:
    """Which registered providers could have raised this, by the SDK it came from.

    Matched on the exception's root module against each spec's name, extra and
    aliases — `openai.AuthenticationError` is `openai`'s. Empty rather than a
    guess when nothing matches, the same rule `providers.missing_key_diagnosis`
    follows for an unknown prefix: a confidently wrong "set MYSTERY_API_KEY" is
    worse than saying nothing.

    **Plural, because one SDK can belong to two providers.** `openai` and
    `azure_openai` both ship in `langchain-openai` and both raise
    `openai.AuthenticationError`, so the module — the only thing an exception
    carries — cannot separate them. This was found by running a workflow rather
    than by reading the code: a service configured for Azure and given a bad
    key was told to *"check OPENAI_API_KEY"*, on a machine where that variable
    was not set at all (providers-and-credentials/18).

    The **environment** is what separates them, and narrowing by it is this
    project's tolerant/strict rule at the size of two lines: read what the SDK
    gives, then resolve it against what this machine actually holds. Where two
    still claim it, both are returned and both are named — guessing between two
    live credentials is worse than naming two.
    """
    root = (type(exc).__module__ or "").split(".")[0].lower()
    if not root:
        return ()
    matches = [
        spec
        for spec in provider_catalogue().list()
        if root in {spec.name.lower(), spec.extra.lower(), *(a.lower() for a in spec.aliases)}
    ]
    if len(matches) < 2:
        return tuple(matches)
    # `has_credential`, not `is_configured`: a provider whose key was *read and
    # rejected* is by definition holding one, and may well be the one whose
    # api-version is also missing.
    holding = [spec for spec in matches if ProviderEnvironment(spec).has_credential()]
    return tuple(holding) or tuple(matches)


def _was_refused(exc: BaseException) -> bool:
    for attribute in ("status_code", "status", "http_status"):
        if getattr(exc, attribute, None) in _REFUSED:
            return True
    name = type(exc).__name__
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return True
    text = str(exc)
    return "401" in text or "Unauthorized" in text


def credential_error_from(exc: BaseException) -> ProviderRefusedCredential | None:
    """A vendor's auth failure, translated into one of ours. Else `None`.

    **The adapter at the edge of the hierarchy.** Returns an *error*, not a
    string, so the translation happens once here and every surface downstream
    treats it exactly like an error we raised — asking it for a developer or a
    customer message rather than each one re-deciding what an
    `AuthenticationError` from some vendor means.

    **The vendor's own text is dropped, not appended.** OpenAI's 401 embeds a
    fragment of the key — `sk-defin****************-key` — and this project
    redacts credentials everywhere it controls; passing one through because it
    arrived from outside would be a leak we merely did not author. What the
    vendor said adds nothing here anyway: the status already carries the
    meaning, and the variable to fix is ours to name.
    """
    if not _was_refused(exc):
        return None
    specs = [spec for spec in _providers_of(exc) if spec.env_vars]
    if not specs:
        return None
    # One name and one variable list in the ordinary case, word for word as
    # before. Two only where two providers genuinely share an SDK *and* both
    # hold a credential, which is the case that would otherwise be answered
    # with a confident guess.
    who = " or ".join(f'"{spec.name}"' for spec in specs)
    variables = " or ".join(dict.fromkeys(name for spec in specs for name in spec.env_vars))
    return ProviderRefusedCredential(
        f"Provider {who} refused the credential — check "
        f"{variables} in .env. The value was read and rejected, "
        "so this is a wrong or expired credential rather than a missing one."
    )


#: Exception type names that mean "no connection was established", by the two
#: libraries every provider integration in this project reaches the network
#: through. Matched on the name rather than imported, because `httpx` is a
#: transitive dependency of the integrations and not one of ours — importing it
#: to build a translator would make the lean core depend on a vendor's SDK to
#: describe that vendor's failure.
_UNREACHABLE = ("ConnectError", "ConnectTimeout", "ConnectionRefusedError")


def _failing_url(exc: BaseException) -> str | None:
    """Where the request that failed was going, if the exception says.

    Tolerant in reading, and the chain is why: the raising library annotates
    `httpx.ConnectError` with its `request`, but a wrapper may re-raise its own
    exception `from` it, so the address is one or two links down. Three links
    is the cap — beyond that the exception being read is no longer plausibly
    about this request.

    `None` when nothing carries an address, which is the strict half: without
    one there is no way to tell a dead Ollama daemon from a dead anything else,
    and a confidently wrong "start your Ollama" is worse than the raw error.
    """
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and len(seen) < 3:
        request = getattr(current, "request", None)
        url = getattr(request, "url", None)
        if url is not None:
            return str(url)
        seen.append(current)
        current = current.__cause__ or current.__context__
    return None


def _authority(url: str) -> str | None:
    """`host:port` for a URL, or `None` if it does not parse as one.

    The comparison is deliberately not the whole string: the configured
    endpoint is an origin (`http://127.0.0.1:11434`) and the failing request
    carries a path (`/api/chat`), so equality would never match. Scheme is
    dropped too — a developer who wrote `https` against a plaintext daemon has
    the same unreachable daemon.
    """
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url if "//" in url else f"//{url}")
    except ValueError:  # pragma: no cover - urlsplit is forgiving
        return None
    return parts.netloc.rpartition("@")[2].lower() or None


def unreachable_endpoint_error_from(exc: BaseException) -> ProviderUnreachable | None:
    """A dead endpoint at a **configured** provider address, translated. Else `None`.

    The sibling of `credential_error_from`, and the fourth shape ticket 03's
    matrix had no room for: `OLLAMA_HOST` set, pointing at a daemon that is not
    running. That is not absent (an address is configured) and not wrong (no
    credential was rejected), so neither existing translator claimed it and a
    developer read `ConnectError: [Errno 61] Connection refused` — a sentence
    naming no provider, no variable and no fix.

    **Attributed by address, not by module.** `credential_error_from` matches
    the SDK an exception came from, which works because a vendor's auth error
    is a vendor's class. A connection failure is `httpx`'s for every provider
    alike, so the module says nothing; the address says everything, and it is
    the one thing the developer configured.

    **Strict in trusting.** Both halves must hold — a connect-shaped failure
    *and* an address that equals a provider's resolved endpoint. A tool calling
    some unrelated service is left exactly as it was, which matters because
    this handler sits on the generic node error path where every failure in a
    workflow passes through.
    """
    if type(exc).__name__ not in _UNREACHABLE:
        return None
    url = _failing_url(exc)
    if url is None:
        return None
    authority = _authority(url)
    if authority is None:
        return None
    for spec in provider_catalogue().list():
        environment = ProviderEnvironment(spec)
        endpoint = environment.base_url()
        if endpoint and _authority(endpoint) == authority:
            # The **configured** address, not the failing request's URL. They
            # differ by the integration's path (`/api/chat`), and quoting a
            # path a developer never wrote back at them beside "the address is
            # configured (OLLAMA_HOST)" invites them to go looking for it in
            # the variable.
            return ProviderUnreachable(environment.unreachable_endpoint_message(endpoint))
    return None


__all__ = [
    "UnconfiguredProvider",
    "build_chat_model",
    "credential_error_from",
    "unreachable_endpoint_error_from",
    "model_kwargs",
]
