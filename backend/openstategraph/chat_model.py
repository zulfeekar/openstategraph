"""The single place a model string becomes a chat model.

Three things have to happen between `"ollama:gpt-oss:120b-cloud"` and an object
you can call, and before this module they happened in different places or not at
all:

1. **The credential gate.** A named provider with no credential fails here with
   the exact fix, rather than raising the vendor SDK's own error — which names
   *its* environment variable and knows nothing about our `.env.example`, so an
   adopter had to work out the two were the same thing.
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
    OpenStateGraphError,
    ProviderRefusedCredential,
)
from openstategraph.providers import provider_catalogue, provider_readiness

if TYPE_CHECKING:  # pragma: no cover - typing only
    from langchain_core.language_models import BaseChatModel

    from openstategraph.providers import ProviderSpec


def model_kwargs(model_name: str) -> dict[str, Any]:
    """Extra `init_chat_model` arguments this model's provider asks for.

    Empty for a provider that declares no endpoint, so Anthropic and OpenAI are
    passed exactly what they were passed before this existed. `None` from
    `base_url` means "the SDK's default is correct" and is deliberately not the
    same as passing a URL we believe to be that default.
    """
    spec = provider_catalogue().for_model(model_name)
    if spec is None:
        return {}
    base_url = spec.base_url()
    return {"base_url": base_url} if base_url else {}


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
        error = MissingProviderPackage if gap.missing_package else MissingProviderKey
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


#: HTTP statuses that mean "your credential was read and refused".
#: 403 counts: a key valid for the vendor but not for *this model* is the same
#: action for the reader — look at the key and the account behind it.
_REFUSED = (401, 403)


def _provider_of(exc: BaseException) -> "ProviderSpec | None":
    """Which registered provider raised this, by the SDK it came from.

    Matched on the exception's root module against each spec's name, extra and
    aliases — `openai.AuthenticationError` is `openai`'s. Returns `None` rather
    than guessing when nothing matches, the same rule
    `providers.missing_key_diagnosis` follows for an unknown prefix: a
    confidently wrong "set MYSTERY_API_KEY" is worse than saying nothing.
    """
    root = (type(exc).__module__ or "").split(".")[0].lower()
    if not root:
        return None
    for spec in provider_catalogue().list():
        if root in {spec.name.lower(), spec.extra.lower(), *(a.lower() for a in spec.aliases)}:
            return spec
    return None


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
    spec = _provider_of(exc)
    if spec is None or not spec.env_vars:
        return None
    return ProviderRefusedCredential(
        f'Provider "{spec.name}" refused the credential — check '
        f"{' or '.join(spec.env_vars)} in .env. The value was read and rejected, "
        "so this is a wrong or expired credential rather than a missing one."
    )


__all__ = [
    "UnconfiguredProvider",
    "build_chat_model",
    "credential_error_from",
    "model_kwargs",
]
