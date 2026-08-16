"""Which model a run uses — one place (ticket 72 split)."""

from __future__ import annotations

import os
from typing import Any, Callable, MutableMapping

from openstategraph.providers import (
    ProviderEnvironment,
    _is_secret,
    credential_env_vars,
    provider_catalogue,
)

#: The Ollama model to use — a **cloud** model, never a local one.
#:
#: Standing project instruction: local models are not performant enough for this
#: workload, and the evidence is direct. `llama3.1:8b` locally could not hold
#: structured output at all, took minutes per run, and produced a confidently
#: wrong answer about global music revenue when asked a database question. The
#: same workflow on `gpt-oss:120b-cloud` wrote a correct two-join `GROUP BY` and
#: answered in 23s.
#:
#: So `ollama:` resolves to cloud wherever it is written. Anyone wanting a
#: local model has to name it explicitly in the request, which is the right
#: amount of friction for a choice that changes the result this much.
#:
#: **This is a name, not a fallback** (install-experience T2). It used to be
#: the literal `resolve_model` returned when nothing else matched, which named
#: Ollama whatever you had installed; the default is elected now
#: (`ProviderCatalogue.elected_default`) and nothing reaches Ollama by *not*
#: choosing. Kept exported because it is imported elsewhere; the value belongs
#: to the Ollama `ProviderSpec` so there is one place to change it.
OLLAMA_CLOUD_MODEL = "ollama:gpt-oss:120b-cloud"


def expand_model_reference(requested: str | None) -> str | None:
    """One written model reference, in full — or `None` for "nothing was asked".

    Axis B of install-experience ticket 01: **how a model reference is
    spelled**, decided in one place so a document, a request and a config file
    cannot come to disagree about what `"ollama:"` means.

    | Written | Resolves to |
    | --- | --- |
    | *(absent, or blank)* | `None` — the caller elects the instance default |
    | `"anthropic"` | `anthropic:claude-haiku-4-5` |
    | `"ollama:"` | `ollama:gpt-oss:120b-cloud` |
    | `"anthropic:claude-opus-4-1"` | itself |
    | `"gpt-4o"` | itself — `init_chat_model` infers the provider |
    | `"nosuchvendor:"` | `UnknownProvider`, naming it |

    Expansion goes through `ProviderSpec.model_string()`, which already knows
    each provider's default *and* its `OPENSTATEGRAPH_<PROVIDER>_MODEL`
    override — so this creates no second table of defaults. An alias
    (`claude:`, `azure_openai:`) is a prefix and expands to the provider that
    owns it.

    **A prefix with an empty model name is refused; an unprefixed name is
    not.** The asymmetry is the whole judgement here. `"nosuchvendor:"` names
    no model, so nothing downstream can rescue it and the honest answer is a
    refusal that says which providers exist. `"gpt-4o"` is a model name
    LangChain resolves on its own, and refusing it would re-narrow the open
    provider set `providers.py` was written to open.
    """
    text = (requested or "").strip()
    if not text:
        return None

    prefix, colon, model = text.partition(":")
    if colon and model.strip():
        return text  # fully spelled — ours to pass on, not to interpret

    spec = provider_catalogue().for_prefix(prefix)
    if spec is not None:
        return ProviderEnvironment(spec).model_string()
    if colon:
        from openstategraph.errors import UnknownProvider

        registered = ", ".join(sorted(provider_catalogue().extras_by_prefix())) or "(none)"
        raise UnknownProvider(
            f'Unknown provider "{prefix}" — {text!r} names no model, and no registered '
            f"provider answers to that prefix. Registered prefixes: {registered}."
        )
    return text  # a bare model name; init_chat_model resolves an unambiguous one


def resolve_model(requested: str | None) -> str:
    """Picks a model, preferring an explicit request.

    **The provider set is open** (ticket 02): this used to be an `if
    os.getenv(...)` chain naming three vendors, so a fourth could never be a
    default however it was configured. It now asks
    the provider catalogue, which a third party contributes to with an entry
    point and no fork.

    **Precedence** (ticket 03), lowest to highest, pinned pair by pair in
    `tests/test_config_file.py::TestPrecedence`::

        instance default < config file < workflow settings.model
                         < node's own model < caller's `model=` argument

    The top three collapse into `requested` before they reach here — call
    sites spell it `request.model or workflow_default_model(document)`, and
    the node layer overrides afterwards in `NodeRuntime._resolve_model`. What
    this function owns is the bottom two, and it owns only **which of them**:
    who the instance default *is* belongs to
    `ProviderCatalogue.elected_default`, which is the one place that decides.

    **A statement of intent outranks an inference** (install-experience T4).
    The bottom pair used to read the other way round — a credential merely
    *present* in the environment beat a `default_model:` somebody had written
    down for the project — so exporting an unrelated key silently changed
    which model a committed workflow used. A credential is a fact about what
    you have, not a request about what to use.

    This is a carve-out, not a reversal of "the environment beats the file".
    `OPENSTATEGRAPH_WORKFLOWS_ROOT` still beats `workflows_dir:`, and
    `OPENSTATEGRAPH_<PROVIDER>_MODEL` is untouched — it is consumed inside
    `ProviderSpec.model_string` and modifies whichever provider wins, so
    "which vendor" and "which of that vendor's models" stay separate
    questions.

    **A request is expanded, not merely echoed** (install-experience T1). See
    `expand_model_reference`: `"ollama:"` and `"anthropic"` are the same
    request as their provider's default, and until it existed they reached the
    vendor SDK verbatim (workflow-gallery ticket 12).

    **Nothing installed raises rather than answering.** Until T2 the last line
    here was `os.getenv("OPENSTATEGRAPH_OLLAMA_MODEL") or OLLAMA_CLOUD_MODEL`,
    which named Ollama whatever you had installed — and the "keyless fallback"
    branch above it, described in this docstring as *"so a developer with no
    credentials at all still gets a working model"*, had been unreachable since
    providers-and-credentials 02 made all three providers require a key. Both
    are gone: a model name nobody can call is not an answer.
    """
    expanded = expand_model_reference(requested)
    if expanded is not None:
        return expanded

    # 1. The config file's declared default. Somebody wrote it for this
    #    project, on purpose; expanded like every other spelling.
    from openstategraph.config_file import active_config

    settings = active_config()
    if settings is not None and settings.default_model:
        declared = expand_model_reference(settings.default_model)
        if declared is not None:
            return declared

    # 2. The elected instance default — what is installed, and configured.
    default = provider_catalogue().elected_default()
    if default.model:
        return default.model

    from openstategraph.errors import NoProviderInstalled

    raise NoProviderInstalled(default.reason)


def accepted_credential_keys() -> frozenset[str]:
    """The only credential names a request may set, from the live catalogue.

    An allow-list, not a pass-through: a request must never be able to write an
    arbitrary environment variable into the server process. Registering a
    provider is what makes its key forwardable — before ticket 02 this was a
    four-name literal, so a fourth vendor's key was silently dropped.

    **Secrets only — never an address** (reviews-2026-08-14 ticket 01). A
    provider's `env_vars` legitimately include where it lives as well as how to
    authenticate: Ollama declares `OLLAMA_HOST` beside `OLLAMA_API_KEY`, and
    `OLLAMA_ENDPOINT` is optional beside both. Accepting those from a request
    was a redirection dressed as a fallback — on the documented cloud setup the
    host is *absent*, so `apply_credentials`' "absent → fill" rule wrote a
    client-supplied address into `os.environ`, which is process-global, and
    every later run in that process sent the operator's key and the user's
    prompt to it.

    A key a client sends can only ever lose to the server's own, so it is
    harmless. An address is not that kind of value, so it is not forwardable at
    all. Nothing in the product sends one: the editor's
    `collectRuntimeCredentials` reads each provider's `runtimeCredentialKey`,
    which is always a `*_API_KEY`.
    """
    return frozenset(name for name in credential_env_vars() if _is_secret(name))


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

