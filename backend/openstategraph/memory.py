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


def _workflow_namespace() -> tuple[str, str]:
    """Findings scoped to the running workflow (its slug rides in config)."""
    from langgraph.config import get_config

    slug = ""
    try:
        slug = str((get_config().get("configurable") or {}).get("workflow_slug") or "")
    except Exception:
        pass
    return ("workflow-memory", slug.strip().lower().replace(".", "_") or "unsaved")


#: The shared pool — appwide knowledge and cross-workflow findings, exactly
#: one namespace so the root (which sits above every workflow) can aggregate.
APP_NAMESPACE: tuple[str, ...] = ("app-memory",)


def memory_tools() -> list[Any]:
    """The prebuilt long-term-memory tools, bound to agents when a store exists.

    Three scopes (user model, 2026-08-08): **user** — follows the person
    appwide; **workflow** — this workflow's own accumulated findings;
    **app** — shared knowledge every workflow can read, where the root/
    concierge deposits cross-workflow findings. Search reads all three and
    labels provenance, so an agent never guesses where a fact lives.
    """
    from langchain_core.tools import tool

    def _namespace_for(scope: str) -> tuple[str, ...]:
        cleaned = (scope or "user").strip().lower()
        if cleaned == "workflow":
            return _workflow_namespace()
        if cleaned == "app":
            return APP_NAMESPACE
        return _user_namespace()

    @tool
    def save_memory(fact: str, scope: str = "user") -> str:
        """Save a lasting fact. scope='user' for facts about this person
        (preferences, their name); scope='workflow' for findings specific to
        the current workflow's domain; scope='app' for knowledge useful to
        every workflow (used from the root assistant for cross-workflow
        findings)."""
        from langgraph.config import get_store

        store = get_store()
        if store is None:
            return "No memory store is configured."
        value: dict[str, Any] = {"fact": fact.strip()}
        cleaned = (scope or "user").strip().lower()
        if cleaned == "app":
            # The spine is auditable: any workflow may deposit an app-wide
            # learning (permissive read, deliberate write — owner decision
            # 2026-08-09), but every deposit records which workflow made it.
            value["workflow"] = _workflow_namespace()[1]
        store.put(_namespace_for(scope), str(uuid.uuid4()), value)
        return f"Remembered ({cleaned})."

    @tool
    def search_memory(query: str) -> str:
        """Look up previously saved facts across every scope — the user's,
        this workflow's, and the shared app pool. Results are labelled with
        where they came from."""
        from langgraph.config import get_store

        store = get_store()
        if store is None:
            return "No memory store is configured."
        rows: list[str] = []
        for label, namespace in (
            ("user", _user_namespace()),
            ("workflow", _workflow_namespace()),
            ("app", APP_NAMESPACE),
        ):
            try:
                # limit=4 per scope caps the whole block at 12 one-liners —
                # a hoarding workflow can never flood the calling prompt.
                hits = store.search(namespace, query=query, limit=4)
            except Exception:
                continue
            for item in hits:
                source = item.value.get("workflow", "")
                tag = f"{label} via {source}" if label == "app" and source else label
                rows.append(f"- [{tag}] {item.value.get('fact', '')}")
        return "\n".join(rows) if rows else "No saved memories match."

    return [save_memory, search_memory]


def build_store() -> Any:
    """The process-wide long-term store.

    In-memory by default (the dev tool's honest baseline). Setting
    ``OPENSTATEGRAPH_MEMORY_PATH=/path/to/memory.sqlite`` opts into a
    sqlite-backed store so memories survive a restart — the same opt-in
    shape as ``settings.checkpointer: "sqlite"``, and the same constraint:
    one uvicorn worker, one connection (``check_same_thread=False`` makes
    the single shared connection usable across request threads, not across
    processes). A PostgresStore drops into this same seam when hosting
    ever comes into scope. An unusable path degrades loudly to in-memory
    rather than failing startup.
    """
    import os

    from langgraph.store.memory import InMemoryStore

    raw_path = os.environ.get("OPENSTATEGRAPH_MEMORY_PATH", "").strip()
    if raw_path:
        try:
            import sqlite3

            from langgraph.store.sqlite import SqliteStore

            path = Path(raw_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                path,
                check_same_thread=False,
                isolation_level=None,  # autocommit — the store BEGINs itself
            )
            store = SqliteStore(conn)
            store.setup()
            return store
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "OPENSTATEGRAPH_MEMORY_PATH=%r unusable; falling back to in-memory store",
                raw_path,
            )
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
