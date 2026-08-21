"""Optional dependencies, and the message an adopter gets when one is missing.

**Internal — not part of the public API. Stability is not guaranteed.**

The lean core is four dependencies (`docs/decisions/framework-packaging.md` §3.1).
Everything else — the deepagents harness, the MCP SDK, the web server, the
three provider SDKs, sqlite persistence — lives behind an extra and is
imported at its one call site rather than at module scope.

That only works if a missing extra *says so*. An adopter who installs
`openstategraph`, draws an `agent.deep` node and gets
`ModuleNotFoundError: No module named 'deepagents'` has to guess which of our
extras owns that name. So every optional import goes through `require_extra`,
whose error names the exact `pip install` line — the same "degrade loud, never
silent" rule the loader already follows for unresolved capabilities.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any

def provider_extras() -> dict[str, str]:
    """Model-string prefix -> the extra supplying its LangChain integration.

    `init_chat_model` imports the provider package by name, so a missing one
    surfaces as its own ImportError; `provider_extra_hint` turns that into our
    install line, because the adopter installed *us*, not `langchain-anthropic`.

    Derived from the provider catalogue (ticket 02) rather than the five-entry
    literal this used to be — a third-party provider's missing package now
    produces an install hint too, instead of falling through to "we don't know
    that prefix".
    """
    from openstategraph.providers import provider_catalogue

    return provider_catalogue().extras_by_prefix()




@dataclass(frozen=True)
class DocumentRequirements:
    """Which extras one document asks for, and which prefixes we could not place.

    Derived from the document alone — no import, no installation, no model call
    — so it answers for a package on a machine that has never run it. The two
    halves are the tolerant/strict pair CLAUDE.md asks for: every model string
    is read in both spellings the product accepts, and a prefix the provider
    catalogue does not know is *reported* rather than turned into a guessed
    install line.
    """

    #: Sorted extra names, e.g. `("anthropic", "deep")`.
    extras: tuple[str, ...] = ()
    #: Sorted prefixes that looked like a provider and are not one here.
    unknown_providers: tuple[str, ...] = ()
    #: Human-readable "why", one per extra: extra -> what in the document asks.
    reasons: tuple[tuple[str, str], ...] = ()


def _nodes(document: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = document.get("nodes")
    return [n for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else []


def document_extras(document: dict[str, Any]) -> DocumentRequirements:
    """The extras a document needs to run, from the document's own text.

    Three sources, and each is the one the runtime itself reads:

    - **`settings.model`** is the colon spelling `init_chat_model` takes.
    - **`data.model` on a node** is the *slash* spelling, and the two are not
      interchangeable (`examples/youtube-trend-digest/AGENTS.md`). A value with
      no `/`, or the provider `mock`, falls back to the document default at run
      time — `NodeRuntime._base_model` — so it names no provider here either.
    - **`data.tier == "deep"`** is the only thing that needs `[deep]`, and
      `settings.checkpointer == "sqlite"` the only thing that needs `[sqlite]`.
    """
    catalogue = provider_extras()
    found: dict[str, str] = {}
    unknown: dict[str, str] = {}

    def _provider(prefix: str, source: str) -> None:
        prefix = prefix.strip().lower()
        if not prefix or prefix == "mock":
            return
        extra = catalogue.get(prefix)
        if extra:
            found.setdefault(extra, source)
        else:
            unknown.setdefault(prefix, source)

    settings = document.get("settings")
    settings = settings if isinstance(settings, dict) else {}
    default_model = str(settings.get("model") or "")
    if default_model:
        _provider(default_model.split(":", 1)[0], f"settings.model: {default_model}")

    deep_nodes: list[str] = []
    for node in _nodes(document):
        data = node.get("data")
        data = data if isinstance(data, dict) else {}
        node_id = str(node.get("id") or "?")
        selection = str(data.get("model") or "")
        provider, sep, model_id = selection.partition("/")
        if sep and model_id:
            _provider(provider, f"node {node_id}: {selection}")
        if str(data.get("tier") or "") == "deep":
            deep_nodes.append(node_id)

    if deep_nodes:
        found["deep"] = f"deep-tier node(s): {', '.join(sorted(deep_nodes))}"
    if str(settings.get("checkpointer") or "") == "sqlite":
        found["sqlite"] = 'settings.checkpointer: "sqlite"'

    return DocumentRequirements(
        extras=tuple(sorted(found)),
        unknown_providers=tuple(sorted(unknown)),
        reasons=tuple((extra, found[extra]) for extra in sorted(found)),
    )


def install_hint(extra: str) -> str:
    """The exact line to type. One spelling, quoted for zsh's benefit."""
    return f"pip install 'openstategraph[{extra}]'"


def require_extra(module: str, extra: str, why: str) -> ModuleType:
    """Import `module`, or raise an ImportError naming the extra that has it.

    `why` completes the sentence "… is required for {why}" and should name the
    *document-level* thing the adopter did — `tier='deep' agent nodes`, not an
    internal function — because the document is what they can change.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise ImportError(
            f"{module} is required for {why} — {install_hint(extra)}"
        ) from exc


def provider_extra_hint(model_name: str) -> str | None:
    """The install line for the provider a model string names, if we know it.

    Returns None for an unrecognised prefix rather than guessing: a wrong
    install line is worse than none, and `init_chat_model`'s own error already
    names the package it could not import.
    """
    prefix = str(model_name or "").split(":", 1)[0].strip().lower()
    extra = provider_extras().get(prefix)
    return install_hint(extra) if extra else None


#: `PROVIDER_EXTRAS`, the module-level dict this used to export, is gone rather
#: than shimmed: a dict frozen at import time would lose every provider
#: registered afterwards, which is the exact closedness ticket 02 removed. This
#: module is internal (see the docstring), nothing imported the name, and
#: `provider_extras()` answers the same question against the live catalogue.
__all__ = [
    "DocumentRequirements",
    "document_extras",
    "install_hint",
    "provider_extra_hint",
    "provider_extras",
    "require_extra",
]
