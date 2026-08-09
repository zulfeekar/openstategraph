"""Which model a run uses — one place (ticket 72 split)."""

from __future__ import annotations

import os
from typing import Any, Callable, MutableMapping


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
OLLAMA_CLOUD_MODEL = "ollama:gpt-oss:120b-cloud"


def resolve_model(requested: str | None) -> str:
    """Picks a model, preferring an explicit request.

    **Ollama cloud is the default**, not an opt-in — a developer with neither
    an Anthropic nor an OpenAI key still gets a working model with zero
    configuration, because `ollama` authenticates from its own local
    credentials (verified live: `init_chat_model("ollama:gpt-oss:120b-cloud")`
    works with no `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`OLLAMA_HOST` env vars
    set at all). This never falls back to a *local* model — see
    `OLLAMA_CLOUD_MODEL`'s own comment for why that standing rule exists —
    and an explicit `model` argument still always wins, so a surprise
    provider is only possible by asking for one.
    """
    if requested:
        return requested
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic:claude-haiku-4-5"
    if os.getenv("OPENAI_API_KEY"):
        return "openai:gpt-4.1-mini"
    return os.getenv("OPENSTATEGRAPH_OLLAMA_MODEL") or OLLAMA_CLOUD_MODEL


#: The only credential names a request may set. An allow-list, not a
#: pass-through: a request must never be able to write an arbitrary
#: environment variable into the server process.
ACCEPTED_CREDENTIAL_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OLLAMA_API_KEY",
        "OLLAMA_HOST",
    }
)


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
    filled: list[str] = []
    for name, value in (credentials or {}).items():
        if name not in ACCEPTED_CREDENTIAL_KEYS:
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

