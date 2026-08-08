"""The memory system — tickets 65 (research) and 47, implemented.

Three kinds, each mapped to the construct the LangGraph docs prescribe
(`.scratch/fullstack-langgraph/research/65-memory-system.md`):

- **Long-term**: a `Store` injected once at ``compile(store=...)``, namespaced
  ``("memories", user_email)`` — the docs' canonical user-scoped pattern.
  ``thread_id``/``session_id`` never appear in a Store namespace; they scope
  the checkpointer only.
- **Episodic**: checkpointer threads. In-memory by default; a workflow opts
  into durability with ``settings.checkpointer: "sqlite"`` (ticket 47's
  decision — a file beside the run data, matching files-first persistence).
- **Procedural**: skills and Store-held instructions — surfaced through the
  middleware slot table, not this module (see ticket 66).

The two tools here are the docs' recommended surface for agent-driven
memory: plain LangChain tools that reach the running graph's store through
``langgraph.config.get_store()``, so they work bound to *any* agent in *any*
workflow with zero per-workflow code — a prebuilt in the exact sense the
project's minimum-viable-prebuilt rule demands.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

#: One namespace root for user facts, shared by both tools and any future
#: memory middleware. A tuple prefix, per the Store API.
USER_MEMORY_NAMESPACE = "memories"


def _user_namespace() -> tuple[str, str]:
    """The current run's memory namespace, derived from config — never state.

    ``user_email`` arrives via ``configurable`` (set by the chat clients,
    ticket 64). An anonymous user still gets a working namespace rather than
    an error: memory quietly scoped to "anonymous" degrades to per-deployment
    shared notes, which is honest for a user who declined to identify.
    """
    from langgraph.config import get_config

    email = ""
    try:
        email = str((get_config().get("configurable") or {}).get("user_email") or "")
    except Exception:
        pass
    cleaned = email.strip().lower().replace(".", "_") or "anonymous"
    # Store namespace labels forbid periods, and emails are full of them —
    # a deterministic substitution keeps one person one namespace.
    return (USER_MEMORY_NAMESPACE, cleaned)


def memory_tools() -> list[Any]:
    """The prebuilt long-term-memory tools, bound to agents when a store exists."""
    from langchain_core.tools import tool

    @tool
    def save_memory(fact: str) -> str:
        """Save a lasting fact about the user (a preference, their name, a
        standing instruction) so future conversations can recall it. Use it
        whenever the user tells you something worth remembering."""
        from langgraph.config import get_store

        store = get_store()
        if store is None:
            return "No memory store is configured."
        store.put(_user_namespace(), str(uuid.uuid4()), {"fact": fact.strip()})
        return "Remembered."

    @tool
    def search_memory(query: str) -> str:
        """Look up previously saved facts about the user. Use it when the
        user refers to something they told you before, or when personal
        context would improve the answer."""
        from langgraph.config import get_store

        store = get_store()
        if store is None:
            return "No memory store is configured."
        hits = store.search(_user_namespace(), query=query, limit=5)
        if not hits:
            return "No saved memories match."
        return "\n".join(f"- {item.value.get('fact', '')}" for item in hits)

    return [save_memory, search_memory]


def build_store() -> Any:
    """The process-wide long-term store. In-memory for the dev tool; the seam
    a PostgresStore drops into when hosting ever comes into scope."""
    from langgraph.store.memory import InMemoryStore

    return InMemoryStore()


def checkpointer_for(settings: dict[str, Any] | None, slug: str | None, fallback: Any) -> Any:
    """The thread checkpointer a document asked for.

    ``settings.checkpointer: "sqlite"`` opts into durability — threads
    survive a restart, which is what makes /chat conversations resumable.
    Anything else (or a missing sqlite package) keeps the shared in-memory
    saver, degrading loudly in the log rather than failing the run.
    """
    choice = str((settings or {}).get("checkpointer") or "").strip().lower()
    if choice != "sqlite":
        return fallback
    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        root = Path(".dev")
        root.mkdir(exist_ok=True)
        conn = sqlite3.connect(
            root / f"checkpoints-{slug or 'default'}.sqlite", check_same_thread=False
        )
        return SqliteSaver(conn)
    except Exception:  # pragma: no cover - environment-dependent
        import logging

        logging.getLogger(__name__).warning(
            "settings.checkpointer=sqlite requested but unavailable; using in-memory"
        )
        return fallback
