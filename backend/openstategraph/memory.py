"""The memory system — tickets 65 (research) and 47, implemented.

Three kinds, each mapped to the construct the LangGraph docs prescribe
(`.scratch/fullstack-langgraph/research/65-memory-system.md`):

- **Long-term**: a `Store` injected once at ``compile(store=...)``, namespaced
  ``("memories", user_email)`` — the docs' canonical user-scoped pattern.
  ``thread_id``/``session_id`` never appear in a Store namespace; they scope
  the checkpointer only.
- **Episodic**: checkpointer threads. **Durable by default** since ticket 05 —
  ``build_checkpointer`` puts one sqlite file under the workflows root, shared
  by every transport, so a paused ``human.approval`` survives the restart the
  dev stack performs on each file save. ``OPENSTATEGRAPH_CHECKPOINT_PATH``
  moves it or (``=memory``) opts out, loudly. A single workflow can still
  claim its own file with ``settings.checkpointer: "sqlite"`` (ticket 47).
- **Procedural**: skills and Store-held instructions — surfaced through the
  middleware slot table, not this module (see ticket 66).

The two tools here are the docs' recommended surface for agent-driven
memory: plain LangChain tools that reach the running graph's store through
``langgraph.config.get_store()``, so they work bound to *any* agent in *any*
workflow with zero per-workflow code — a prebuilt in the exact sense the
project's minimum-viable-prebuilt rule demands.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any


def _log() -> logging.Logger:
    """One logger for this module's degradation warnings.

    Named, not `logging.warning`, so a deployment can raise the level on
    exactly this module and a test can assert against exactly this logger —
    both of which matter for messages whose entire job is to be noticed.
    """
    return logging.getLogger(__name__)

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
        except ImportError:
            # Same undeclared-dependency trap as `checkpointer_for`: the user
            # set a path, so they expect memories on disk. Name the extra.
            from openstategraph._extras import install_hint

            _log().warning(
                "OPENSTATEGRAPH_MEMORY_PATH=%r asked for a durable store, but "
                "langgraph-checkpoint-sqlite is not installed — falling back to an "
                "IN-MEMORY store, so saved memories will NOT survive a restart. "
                "Install it with: %s",
                raw_path,
                install_hint("sqlite"),
            )
        except Exception:
            _log().warning(
                "OPENSTATEGRAPH_MEMORY_PATH=%r unusable; falling back to an "
                "IN-MEMORY store, so saved memories will NOT survive a restart.",
                raw_path,
                exc_info=True,
            )
    return InMemoryStore()


#: The deployment's explicit answer for where thread checkpoints live. An
#: absolute (or cwd-relative) sqlite path, or the literal ``memory`` to opt
#: OUT of durability on purpose — a stateless container, or a test suite that
#: must not leave files behind. Deliberately a *stated* opt-out rather than a
#: silent one: "in-memory" is a real loss of work and has to be chosen.
CHECKPOINT_PATH_ENV = "OPENSTATEGRAPH_CHECKPOINT_PATH"

#: The one value of the above that means "do not persist". ``:memory:`` is
#: accepted too, since that is sqlite's own spelling and someone will type it.
IN_MEMORY_CHECKPOINT = "memory"

#: The process's own state, kept beside the content it is state *about*, and
#: dotted so `WorkflowStore.list` (which requires a `workflow.json`) and every
#: `ls` treat it as plumbing rather than a workflow.
STATE_DIR_NAME = ".openstategraph"
CHECKPOINT_FILE_NAME = "checkpoints.sqlite"


def checkpoint_path(workflows_root_dir: Any = None) -> Path | None:
    """Where the process-wide checkpointer writes, or None for in-memory.

    Two sources, in order: the env var above, then the **default** —
    ``<workflows root>/.openstategraph/checkpoints.sqlite``.

    The default is durable rather than in-memory, and that is the ticket-05
    decision: ``openstategraph serve`` run by a stranger must not lose a
    `human.approval` pause because someone saved a file. The workflows root is
    the right home for it because it is the one directory this process already
    owns and already writes to, it is resolved correctly both inside a
    checkout and inside an installed wheel (`workflows_root()` — see that
    module for what a frozen constant cost), and it is per-project, so two
    projects on one machine never share a thread namespace.
    """
    import os

    from openstategraph.workflows_root import workflows_root

    raw = os.environ.get(CHECKPOINT_PATH_ENV, "").strip()
    if raw:
        if raw.lower() in {IN_MEMORY_CHECKPOINT, ":memory:"}:
            return None
        return Path(raw).expanduser()
    root = Path(workflows_root_dir) if workflows_root_dir else workflows_root()
    return root / STATE_DIR_NAME / CHECKPOINT_FILE_NAME


def _open_sqlite_saver(path: Path, asked_by: str) -> Any | None:
    """A `SqliteSaver` on `path`, or None having said loudly why not.

    One implementation for both callers — the process default and a
    document's own ``settings.checkpointer: "sqlite"`` — because the
    degradation message is knowledge, and two copies is how one of them ends
    up describing a symptom instead of naming the fix.
    """
    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        # The one degradation this codebase was getting wrong. `langgraph-
        # checkpoint-sqlite` is not a transitive of `langgraph` and was never
        # declared, so *every install that existed* answered "yes" to
        # `settings.checkpointer: "sqlite"` and quietly gave the user an
        # in-process saver. They asked for durability, got a log line nobody
        # reads, and find out when a restart eats a conversation.
        #
        # It is a declared extra now — and, since ticket 05, part of `[server]`
        # as well, because the server's default *is* sqlite — so the message
        # can name the fix instead of describing the symptom.
        from openstategraph._extras import install_hint

        _log().warning(
            "%s asked for durable threads, but langgraph-checkpoint-sqlite is not "
            "installed — falling back to an IN-MEMORY saver, so approvals and "
            "conversations will NOT survive a restart. Install it with: %s",
            asked_by,
            install_hint("sqlite"),
        )
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        saver = SqliteSaver(conn)
        # Eager, though `SqliteSaver` would do it lazily on first use: it is
        # what makes the file and its tables exist *now*, so the startup line
        # below reports a location that is true rather than intended.
        saver.setup()
        return saver
    except Exception:  # pragma: no cover - environment-dependent
        _log().warning(
            "%s requested a durable checkpointer at %s, but it could not be opened; "
            "falling back to an IN-MEMORY saver, so approvals and conversations "
            "will NOT survive a restart.",
            asked_by,
            path,
            exc_info=True,
        )
        return None


def build_checkpointer(workflows_root_dir: Any = None) -> Any:
    """The process-wide thread checkpointer, and the one line that states it.

    Held by `WorkflowServices` (the assembly point) and shared by HTTP, MCP
    and `load_workflow`. It replaces the module-level `InMemorySaver` that
    `api/main.py` used to own, whose two failures were the same failure: a
    paused approval died on restart, and a second uvicorn worker got a second,
    empty copy.

    Exactly one status line is emitted, at INFO when the checkpoints are on
    disk and at WARNING when they are not, because a limitation a user
    discovers by losing work is not a stated limitation. (INFO rather than
    print: a library consumer who never configured logging stays quiet, while
    the server — which calls `basicConfig(INFO)` — always says it.)
    """
    from langgraph.checkpoint.memory import InMemorySaver

    path = checkpoint_path(workflows_root_dir)
    saver = _open_sqlite_saver(path, "the default checkpointer") if path is not None else None
    if saver is not None:
        _log().info("approvals persist at %s", path)
        return saver
    _log().warning(
        "approvals are in-memory and will NOT survive a restart%s",
        f" ({CHECKPOINT_PATH_ENV}={IN_MEMORY_CHECKPOINT})" if path is None else "",
    )
    return InMemorySaver()


def close_resource(resource: Any) -> None:
    """Release the OS handle behind a saver or a store. Safe to call twice.

    This lives here because this module is what opened the connection, and
    because the knowledge is not obvious: neither langgraph's `SqliteSaver`
    nor its `SqliteStore` defines `close()` or `__exit__`, so there is no
    library-blessed way to release the handle — both simply hold the
    `sqlite3.Connection` we handed their constructor as `.conn`. An
    `InMemorySaver`/`InMemoryStore` has no `.conn` at all and correctly does
    nothing here.

    `SqliteStore` also runs a TTL sweeper thread when one is configured; its
    `stop_ttl_sweeper` is called first where present, because closing the
    connection out from under a live sweeper is how a background thread
    raises into a log nobody is reading.
    """
    stop = getattr(resource, "stop_ttl_sweeper", None)
    if callable(stop):
        try:
            stop()
        except Exception:  # pragma: no cover - defensive, thread-timing dependent
            _log().debug("could not stop the store's TTL sweeper", exc_info=True)
    conn = getattr(resource, "conn", None)
    if conn is None:
        return
    try:
        conn.close()
    except Exception:  # pragma: no cover - already-closed or foreign connection
        _log().debug("could not close %r", resource, exc_info=True)


def checkpointer_for(settings: dict[str, Any] | None, slug: str | None, fallback: Any) -> Any:
    """The thread checkpointer a document asked for.

    ``settings.checkpointer: "sqlite"`` opts a single workflow into its **own**
    file, separate from the process default — threads survive a restart either
    way now, but a document that names sqlite keeps the per-workflow database
    it has always had. Anything else keeps `fallback`, which since ticket 05
    is the durable process-wide saver rather than a per-process `InMemorySaver`.
    """
    choice = str((settings or {}).get("checkpointer") or "").strip().lower()
    if choice != "sqlite":
        return fallback
    root = Path(".dev")
    saver = _open_sqlite_saver(
        root / f"checkpoints-{slug or 'default'}.sqlite", "settings.checkpointer='sqlite'"
    )
    return saver if saver is not None else fallback
