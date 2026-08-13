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
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

if TYPE_CHECKING:
    # Types only. `from __future__ import annotations` above keeps every
    # annotation a string, so naming these costs no import at runtime and the
    # lazy-import guarantee this module relies on is untouched — the same
    # pattern, and the same reasoning, as `loader.py`.
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.store.base import BaseStore


class MemoryRecord(TypedDict):
    """What one saved memory looks like in the Store.

    The record schema is *knowledge* and was previously implicit in a
    `dict[str, Any]` literal — so the app-scope provenance stamp (`workflow`)
    existed only in the one branch that wrote it, and nothing typed it as
    optional-but-meaningful.
    """

    fact: str
    #: Only on app-scope deposits: which workflow made this one.
    workflow: NotRequired[str]


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

    **The two ways of arriving at "anonymous" are logged apart** (ticket 07).
    A person who declined to identify is normal; ``configurable`` failing to
    reach this code is a bug, and before this the two were the same silence —
    which is what would let a future refactor collapse every user into one
    namespace with nothing to notice it by.
    """
    from langgraph.config import get_config

    email = ""
    try:
        email = str((get_config().get("configurable") or {}).get("user_email") or "")
    except Exception as exc:
        _log().debug("no run config to read user_email from (%s); memory is anonymous", exc)
    else:
        if not email:
            _log().debug("run config carries no user_email; memory is anonymous")
    cleaned = email.strip().lower().replace(".", "_") or "anonymous"
    # Store namespace labels forbid periods, and emails are full of them —
    # a deterministic substitution keeps one person one namespace.
    return (USER_MEMORY_NAMESPACE, cleaned)


def _workflow_namespace() -> tuple[str, str]:
    """Findings scoped to the running workflow (its slug rides in config).

    Logged apart for the same reason as `_user_namespace`: "unsaved" reached
    by an unsaved document and "unsaved" reached by config never arriving are
    different facts, and the second one also silently defeats the app-scope
    provenance stamp (ship-it 47's rider).
    """
    from langgraph.config import get_config

    slug = ""
    try:
        slug = str((get_config().get("configurable") or {}).get("workflow_slug") or "")
    except Exception as exc:
        _log().debug("no run config to read workflow_slug from (%s); scope is 'unsaved'", exc)
    else:
        if not slug:
            _log().debug("run config carries no workflow_slug; scope is 'unsaved'")
    return ("workflow-memory", slug.strip().lower().replace(".", "_") or "unsaved")


#: The shared pool — appwide knowledge and cross-workflow findings, exactly
#: one namespace so the root (which sits above every workflow) can aggregate.
APP_NAMESPACE: tuple[str, ...] = ("app-memory",)


def _app_namespace() -> tuple[str, ...]:
    """The app pool, as a resolver so every scope is declared the same way."""
    return APP_NAMESPACE


# `MemoryScope` — the whole scope set, declared once, each member carrying how
# it resolves. The rationale lives in this comment rather than in the class
# docstring **because the docstring is shipped to the model**: Pydantic renders
# it as the `scope` parameter's description, so every paragraph here would ride
# in every agent's prompt on every request. Keep the docstring one line.
#
# It used to be the same knowledge in four places — an if/elif chain, a
# hardcoded tuple in `search_memory`, and prose in two docstrings — with two
# consequences, both silent:
#
#   - A scope outside the set fell through the chain into the **user**
#     namespace, and the tool confirmed the scope the caller *asked for* rather
#     than the one it wrote. `save_memory(fact, scope="global")` filed a
#     cross-workflow finding in one person's private namespace and answered
#     "Remembered (global)." That is the RouterNode lesson in tool form: a
#     machine-owned answer must describe what happened.
#   - Adding a scope meant editing this module's body in several places — the
#     **O** violation ship-it ticket 03 fixed for workflow-scoped node families,
#     quoting the same rule.
#
# Deriving the tool signature from this enum is also what hands the model a
# JSON-Schema `enum` instead of three scope names buried in prose, so an
# out-of-set value is a validation error the agent can see and retry.
#
# Deliberately **not** a `Registry`. A plugin contributing a fourth memory scope
# is not a designed capability the way a node type is, and registry machinery
# for a set of three would be ceremony. A new scope is one member plus its
# resolver — one site — which is as open as this should be.
#
# Matching is exact: "App " and "User" are refused rather than normalised. The
# model is given the closed set, so a near-miss is a bug to surface rather than
# spelling to guess at.
class MemoryScope(str, Enum):
    """Where a memory lives: the person, this workflow, or every workflow."""

    #: Annotation only — an `Enum` treats a bare annotation as a non-member,
    #: which is how a member can carry data without becoming a member itself.
    _resolver: Callable[[], tuple[str, ...]]

    def __new__(cls, value: str, resolver: Callable[[], tuple[str, ...]]) -> MemoryScope:
        member = str.__new__(cls, value)
        member._value_ = value
        member._resolver = resolver
        return member

    USER = ("user", _user_namespace)
    WORKFLOW = ("workflow", _workflow_namespace)
    APP = ("app", _app_namespace)

    @property
    def namespace(self) -> tuple[str, ...]:
        """This scope's Store namespace, resolved from the running config."""
        return self._resolver()


def memory_tools() -> list[BaseTool]:
    """The prebuilt long-term-memory tools, bound to agents when a store exists.

    Three scopes (user model, 2026-08-08): **user** — follows the person
    appwide; **workflow** — this workflow's own accumulated findings;
    **app** — shared knowledge every workflow can read, where the root/
    concierge deposits cross-workflow findings. Search reads all three and
    labels provenance, so an agent never guesses where a fact lives.
    """
    from langchain_core.tools import tool

    @tool
    def save_memory(fact: str, scope: MemoryScope = MemoryScope.USER) -> str:
        """Save a lasting fact. scope='user' for facts about this person
        (preferences, their name); scope='workflow' for findings specific to
        the current workflow's domain; scope='app' for knowledge useful to
        every workflow (used from the root assistant for cross-workflow
        findings)."""
        from langgraph.config import get_store

        store = get_store()
        if store is None:
            return "No memory store is configured."
        value: MemoryRecord = {"fact": fact.strip()}
        if scope is MemoryScope.APP:
            # The spine is auditable: any workflow may deposit an app-wide
            # learning (permissive read, deliberate write — owner decision
            # 2026-08-09), but every deposit records which workflow made it.
            value["workflow"] = _workflow_namespace()[1]
        store.put(scope.namespace, str(uuid.uuid4()), dict(value))
        # Names the scope that was *written*, which before this was not
        # guaranteed to be the scope that was asked for.
        return f"Remembered ({scope.value})."

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
        # Iterating the enum is what keeps this from being a second copy of
        # the scope set; declaration order is the order the agent reads.
        for scope in MemoryScope:
            label, namespace = scope.value, scope.namespace
            try:
                # limit=4 per scope caps the whole block at 12 one-liners —
                # a hoarding workflow can never flood the calling prompt.
                hits = store.search(namespace, query=query, limit=4)
            except Exception as exc:
                # A warning, not a debug line: the other scopes still answer,
                # so the caller sees a plausible result that is quietly missing
                # a third of memory. That is precisely the failure that needs
                # to be noticeable from outside.
                _log().warning("memory scope %s is unreadable (%s); skipped", namespace, exc)
                continue
            for item in hits:
                source = item.value.get("workflow", "")
                tag = f"{label} via {source}" if label == "app" and source else label
                rows.append(f"- [{tag}] {item.value.get('fact', '')}")
        return "\n".join(rows) if rows else "No saved memories match."

    return [save_memory, search_memory]


def build_store() -> BaseStore:
    """The process-wide long-term store.

    In-memory by default (the dev tool's honest baseline). Setting
    ``OPENSTATEGRAPH_MEMORY_PATH=/path/to/memory.sqlite`` opts into a
    sqlite-backed store so memories survive a restart — the same opt-in
    shape as ``settings.checkpointer: "sqlite"``, and the same constraint:
    one uvicorn worker, one connection (``check_same_thread=False`` makes
    the single shared connection usable across request threads, not across
    processes). An unusable path degrades loudly to in-memory rather than
    failing startup.

    ``OPENSTATEGRAPH_POSTGRES_URL`` (ticket 06, the ``[postgres]`` extra) puts
    the same store in a database instead — the seam this docstring used to
    promise, now filled. It ranks *below* ``OPENSTATEGRAPH_MEMORY_PATH``
    because that names one file outright and is therefore the more specific
    answer; a deployment that set both meant the file. Unlike every other
    backend here, a broken Postgres **raises** rather than degrading: see
    `openstategraph.postgres` for why.
    """
    import os

    from langgraph.store.memory import InMemoryStore

    from openstategraph import postgres

    raw_path = os.environ.get("OPENSTATEGRAPH_MEMORY_PATH", "").strip()
    postgres_url = postgres.postgres_url()
    if not raw_path and postgres_url:
        return cast("BaseStore", postgres.store(postgres_url))
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

#: Re-exported, not redefined. `state_dir` owns the whole write-location
#: question since ticket 03 (scale-and-adopt); this name stays importable from
#: here because that is where every caller and test already reaches for it.
from openstategraph.state_dir import STATE_DIR_NAME as STATE_DIR_NAME  # noqa: F401
from openstategraph.state_dir import state_dir

CHECKPOINT_FILE_NAME = "checkpoints.sqlite"


def checkpoint_path(workflows_root_dir: Path | str | None = None) -> Path | None:
    """Where the process-wide checkpointer writes, or None for in-memory.

    Two sources, in order: the env var above, then ``state_dir()`` — which is
    ``<workflows root>/.openstategraph`` inside a checkout and the platform's
    per-user state directory when installed. `CHECKPOINT_PATH_ENV` stays the
    most specific answer there is, above `STATE_DIR_ENV` and above both.

    The default is durable rather than in-memory, and that is the ticket-05
    decision: ``openstategraph serve`` run by a stranger must not lose a
    `human.approval` pause because someone saved a file. What ticket 03 changed
    is only *where*: durability must not be bought by writing into a directory
    the user merely asked us to read (see `state_dir`).
    """
    import os

    raw = os.environ.get(CHECKPOINT_PATH_ENV, "").strip()
    if raw:
        if raw.lower() in {IN_MEMORY_CHECKPOINT, ":memory:"}:
            return None
        return Path(raw).expanduser()
    return state_dir(workflows_root_dir) / CHECKPOINT_FILE_NAME


def _open_sqlite_saver(path: Path, asked_by: str) -> BaseCheckpointSaver[Any] | None:
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


def build_checkpointer(workflows_root_dir: Path | str | None = None) -> BaseCheckpointSaver[Any]:
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

    Three backends now, in one order of specificity (ticket 06):
    ``OPENSTATEGRAPH_CHECKPOINT_PATH`` names one file — or opts out with
    ``memory`` — and wins outright; ``OPENSTATEGRAPH_POSTGRES_URL`` is next;
    the state directory's sqlite file is the convention underneath both. The
    opt-out has to stay on top: a stateless container that said "no
    persistence" must not be handed a database because a sibling variable
    happened to be in the environment too.
    """
    import os

    from langgraph.checkpoint.memory import InMemorySaver

    from openstategraph import postgres

    postgres_url = postgres.postgres_url()
    if postgres_url and not os.environ.get(CHECKPOINT_PATH_ENV, "").strip():
        return cast("BaseCheckpointSaver[Any]", postgres.checkpointer(postgres_url))

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


def checkpointer_for(
    settings: dict[str, Any] | None,
    slug: str | None,
    fallback: BaseCheckpointSaver[Any],
    *,
    workflows_root_dir: Path | str | None = None,
) -> BaseCheckpointSaver[Any]:
    """The thread checkpointer a document asked for.

    ``settings.checkpointer: "sqlite"`` opts a single workflow into its **own**
    file, separate from the process default — threads survive a restart either
    way now, but a document that names sqlite keeps the per-workflow database
    it has always had. Anything else keeps `fallback`, which since ticket 05
    is the durable process-wide saver rather than a per-process `InMemorySaver`.

    `workflows_root_dir` scopes that file the same way it scopes the
    process-wide one, so a transport serving root A and a script pointed at
    root B never share a per-workflow database. It goes through `state_dir()`:
    the *file* is per workflow, but *where state lives* is one answer for the
    whole process (scale-and-adopt ticket 03).
    """
    choice = str((settings or {}).get("checkpointer") or "").strip().lower()
    if choice != "sqlite":
        return fallback
    # `Path(".dev")` until ticket 03 (scale-and-adopt) — relative to the
    # *working directory*, so a workflow run from someone's home directory
    # created `~/.dev/`. A per-workflow checkpoint file is state exactly as the
    # process-wide one is, and it goes where all state goes.
    saver = _open_sqlite_saver(
        state_dir(workflows_root_dir) / f"checkpoints-{slug or 'default'}.sqlite",
        "settings.checkpointer='sqlite'",
    )
    return saver if saver is not None else fallback
