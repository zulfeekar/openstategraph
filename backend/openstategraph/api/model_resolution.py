"""Which model a run uses — one place (ticket 72 split)."""

from __future__ import annotations

import os
from typing import Any, Callable, MutableMapping

from openstategraph.providers import credential_env_vars, provider_catalogue

#: The Ollama model to use — a **cloud** model, never a local one.
#:
#: Standing project instruction: local models are not performant enough for this
#: workload, and the evidence is direct. `llama3.1:8b` locally could not hold
#: structured output at all, took minutes per run, and produced a confidently
#: wrong answer about global music revenue when asked a database question. The
#: same workflow on `gpt-oss:120b-cloud` wrote a correct two-join `GROUP BY` and
#: answered in 23s.
#:
#: So a bare `ollama:` fallback must resolve to cloud. Anyone wanting a local
#: model has to name it explicitly in the request, which is the right amount of
#: friction for a choice that changes the result this much.
#:
#: Kept as a name because it is imported elsewhere; the value now comes from
#: the Ollama `ProviderSpec` so there is one place to change it.
OLLAMA_CLOUD_MODEL = "ollama:gpt-oss:120b-cloud"


def resolve_model(requested: str | None) -> str:
    """Picks a model, preferring an explicit request.

    **The provider set is open** (ticket 02): this used to be an `if
    os.getenv(...)` chain naming three vendors, so a fourth could never be a
    default however it was configured. It now asks
    the provider catalogue, which a third party contributes to with an entry
    point and no fork.

    **Precedence** (ticket 03), lowest to highest, pinned pair by pair in
    `tests/test_config_file.py::TestPrecedence`::

        config file < environment < workflow settings.model
                    < node's own model < caller's `model=` argument

    The top three collapse into `requested` before they reach here — call
    sites spell it `request.model or workflow_default_model(document)`, and
    the node layer overrides afterwards in `NodeRuntime._resolve_model`. What
    this function owns is the bottom two: environment, then config file, then
    the keyless fallback.

    **Ollama is still the default *name*, and that is all this decides.**
    Naming a model is cheap and total; whether it can be *called* is
    `chat_model.build_chat_model`'s question, and since
    providers-and-credentials ticket 02 the answer needs `OLLAMA_API_KEY` or
    `OLLAMA_HOST`.

    Until that ticket this docstring said Ollama "authenticates from its own
    local credentials", offered as reassurance that zero configuration worked.
    It was true, and it was the defect: those credentials belonged to a
    logged-in local daemon and could not be read, moved or revoked from an
    environment — and on a machine without that daemon the "working model with
    zero configuration" was a connection refused.

    This never falls back to a *local* model — see `OLLAMA_CLOUD_MODEL` — and
    an explicit `model` argument still always wins, so a surprise provider is
    only possible by asking for one.
    """
    if requested:
        return requested

    catalogue = provider_catalogue()

    # 1. Environment. A credential actually present on this machine names a
    #    provider, and outranks a file a colleague committed.
    for spec in catalogue.list():
        if spec.requires_key and spec.is_configured():
            return spec.model_string()

    # 2. The config file's own default, if it declares one.
    from openstategraph.config_file import active_config

    settings = active_config()
    if settings is not None and settings.default_model:
        return settings.default_model

    # 3. The keyless fallback — Ollama cloud, so a developer with no
    #    credentials at all still gets a working model.
    for spec in catalogue.list():
        if not spec.requires_key:
            return spec.model_string()

    return os.getenv("OPENSTATEGRAPH_OLLAMA_MODEL") or OLLAMA_CLOUD_MODEL


def accepted_credential_keys() -> frozenset[str]:
    """The only credential names a request may set, from the live catalogue.

    An allow-list, not a pass-through: a request must never be able to write an
    arbitrary environment variable into the server process. Registering a
    provider is what makes its key forwardable — before ticket 02 this was a
    four-name literal, so a fourth vendor's key was silently dropped.
    """
    return credential_env_vars()


#: Back-compatible snapshot of :func:`accepted_credential_keys` for callers that
#: import the name. Computed once at import, so it reflects the built-ins plus
#: whatever was installed at that moment; `apply_credentials` calls the
#: function instead, and is therefore correct for a provider registered later.
ACCEPTED_CREDENTIAL_KEYS = credential_env_vars()


def apply_credentials(
    credentials: dict[str, str] | None,
    env: MutableMapping[str, str] | None = None,
) -> list[str]:
    """Fills in **absent** provider credentials from a request, and no others.

    The editor stores keys in the browser (`CredentialsDialog`), so without
    this a key pasted there does nothing for a backend run. It is applied as a
    *fallback*, never an override, and the direction is deliberate:

    - A server-side env var is deployment configuration, chosen by whoever
      operates the server. A browser value arrives from a client on every
      request, and `os.environ` is process-global rather than request-scoped —
      if the client won, one request could silently repoint a shared
      deployment at another account's key for every later run in that process.
    - So the rule is: absent → fill; present → leave alone.

    Returns the **names** that were filled, never the values. Nothing here
    logs, returns or echoes a credential value.
    """
    target: MutableMapping[str, str] = os.environ if env is None else env
    accepted = accepted_credential_keys()
    filled: list[str] = []
    for name, value in (credentials or {}).items():
        if name not in accepted:
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        if target.get(name):
            continue  # already configured server-side — configuration wins
        target[name] = value.strip()
        filled.append(name)
    return filled


#: Injectable so tests can exercise the HTTP layer without a provider.
GraphFactory = Callable[[str], Any]



def workflow_default_model(document: dict[str, Any]) -> str | None:
    """The document's own default model, from `settings.model` (ticket 36)."""
    settings = document.get("settings")
    if isinstance(settings, dict):
        value = settings.get("model")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

