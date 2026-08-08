"""Which model a run uses — one place (ticket 72 split)."""

from __future__ import annotations

import os
from typing import Any, Callable


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

