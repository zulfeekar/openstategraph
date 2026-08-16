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
from types import ModuleType

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
    "install_hint",
    "provider_extra_hint",
    "provider_extras",
    "require_extra",
]
