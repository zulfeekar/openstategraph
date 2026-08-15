"""The per-workflow runtime assembly, factored out of `create_app`.

One process may expose the platform through more than one *transport* — HTTP
(`api/main.py`) and MCP (`mcp_server.py`) — and both need exactly the same
thing underneath: a `WorkflowStore`, one process-wide memory `Store`, and the
single `NodeRuntime` construction that decides which tools, functions, skills,
middleware and knowledge a run can see.

That construction used to be two closures inside `create_app`, which meant a
second transport could only get at it by starting FastAPI or by copying the
assembly. Copying it is the failure mode worth preventing: the run, stream and
resume endpoints already had to be pulled onto one shared `runtime_for` once
before, precisely because three call sites had drifted about capabilities.

So this is a **collaborator, not a base class** — `create_app` holds one, the
MCP server holds one, neither inherits anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Types only — `from __future__ import annotations` keeps these out of
    # the runtime import graph, the same pattern `loader.py` established.
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.store.base import BaseStore

from openstategraph.api.registries import (
    build_function_registry,
    build_tool_registry,
)
from openstategraph.principal import IPrincipals, principals_from_env
from openstategraph.schema import normalize_document
from openstategraph.api.workflow_store import WorkflowStore


class WorkflowServices:
    """Store + memory + the one runtime construction every transport shares.

    Every collaborator here is the caller's to supply. `memory_store`,
    `tools`, `functions` and `middleware` are the injection seam behind
    `load_workflow`'s parameters of the same names; omitting one keeps the
    behaviour that existed before the parameter did (an env-driven
    `build_store()`, and discovery alone for capabilities).

    **`memory_store`, not `store`** (install-experience ticket 12). The
    keyword used to be `store=` while `self.store` is the filesystem
    `WorkflowStore` set sixteen lines below it, so `WorkflowServices(root,
    store=X)` did not set `.store` — the class was self-inconsistent before
    any caller was involved. Renamed outright rather than shimmed: this class
    is Tier 3 and `docs/stability.md` names it among the things that are
    deliberately *not* public, so a compatibility keyword here would be a
    promise we have said we are not making. `load_workflow(store=)` **is**
    public and keeps its spelling.

    **Injection is the most specific source, so it wins.** The registry order
    is built-in < plugin < package-local < caller: the filesystem describes
    what a package *shipped*, while an argument describes what *this process*
    is to run, and only the caller can know which of the two is right. It is
    also the only ordering that makes substitution possible at all — anything
    else would mean a vendored package could veto the host application.
    """

    def __init__(
        self,
        workflows_root: Any = None,
        *,
        memory_store: BaseStore | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        tools: dict[str, Any] | None = None,
        functions: dict[str, Any] | None = None,
        middleware: dict[str, Any] | None = None,
        principals: IPrincipals | None = None,
    ) -> None:
        from openstategraph.api.catalogue_events import CatalogueBroadcaster

        self.store = WorkflowStore(root=workflows_root)
        #: Live catalogue changes — the fan-out behind `GET /api/events`, so an
        #: open `/chat` picker or Workflows panel sees a publish without a
        #: reload. A **collaborator**, not behaviour on this class: it is here
        #: because this is the assembly point every transport already shares,
        #: exactly like the checkpointer and the memory Store. In-process, so
        #: it reaches this worker only — which is the documented ceiling
        #: anyway (see `catalogue_events` for the limits and the upgrade path).
        self.events = CatalogueBroadcaster()
        #: Long-term memory, process-wide (ticket 65): one Store shared by
        #: every run, namespaced per user inside the tools themselves.
        #: Injectable, because its sibling the checkpointer always was: a
        #: caller who owns their own durability must be able to own both, and
        #: a `build_store()` call hidden in a constructor made the memory half
        #: unreachable — an `InMemoryStore` that looks like it works and loses
        #: every fact on restart.
        #: Resolved lazily and cached (see the property), for the reason its
        #: sibling the checkpointer already is: now that the default opens a
        #: file, merely *constructing* services must not create a state
        #: directory for a caller who was about to hand us their own store, or
        #: who never touches memory at all.
        self._memory_store = memory_store
        #: Ownership, recorded at construction rather than inferred at close.
        #: What we opened, we close; what the caller injected stays theirs and
        #: is still in use after we are done with it. Inferring this later
        #: (say, "close it if it has a `.conn`") would close a caller's own
        #: sqlite saver and break the process that lent it to us.
        self._owns_memory_store = memory_store is None
        #: Thread checkpoints — what makes a `human.approval` pause resumable
        #: (ticket 05). It lives here, beside its sibling the memory Store,
        #: because this is the assembly point every transport already shares:
        #: it used to be a module-level `InMemorySaver` in `api/main.py`, which
        #: MCP and `load_workflow` could not reach and no test could scope, and
        #: which lost every paused approval on restart. Resolved lazily and
        #: cached (see the property) so constructing services never opens a
        #: file a caller was about to replace.
        self._checkpointer = checkpointer
        self._owns_checkpointer = checkpointer is None
        #: slug -> the saver `settings.checkpointer: "sqlite"` opened for it.
        #: Always ours, by construction: an entry only exists when this object
        #: opened a per-workflow file.
        #:
        #: **Bounded by the store, not by a cap** (ticket 06). It has no
        #: eviction short of `close()`, and each entry holds an open sqlite
        #: descriptor — so what keeps it finite has to be the *key domain*:
        #: the key is always a slug (the guard in `checkpointer_for`), and the
        #: run endpoints 404 a slug naming no package before they reach here,
        #: so entries are bounded by the packages on disk. An LRU was the
        #: alternative and is worse: evicting means closing, and closing a
        #: saver a live run is checkpointing against fails that run.
        self._workflow_checkpointers: dict[str, BaseCheckpointSaver[Any]] = {}
        # Copied, not aliased: a caller's dict must not become live state that
        # a later mutation of theirs changes mid-run.
        self._injected_tools = dict(tools or {})
        self._injected_functions = dict(functions or {})
        self._injected_middleware = dict(middleware or {})
        #: Who a run is for (ticket 01). A collaborator like every other
        #: here — the default refuses to identify anyone unless the
        #: environment named a trusted proxy header, because the value it
        #: replaced was a text box in the browser.
        self.principals = principals if principals is not None else principals_from_env()

    @property
    def memory_store(self) -> BaseStore:
        """The one long-term Store every transport compiles against.

        Durable by default since install-experience wave 2 — `build_store`
        puts it under this services object's own workflows root, beside the
        checkpointer, and says so in one log line. A caller who passed
        `memory_store=`
        owns durability instead, and nothing is opened.

        Built on first ask for the same reason the checkpointer is: the
        location depends on `self.store.root`, and a constructor that opened a
        file would make merely *asking for* services a write.
        """
        if self._memory_store is None:
            from openstategraph.memory import build_store

            self._memory_store = build_store(self.store.root)
        return self._memory_store

    @property
    def checkpointer(self) -> BaseCheckpointSaver[Any]:
        """The one saver every transport compiles against, built on first ask.

        Durable by default — `build_checkpointer` puts it under this services
        object's own workflows root, and says so in one log line. A caller who
        passed `checkpointer=` owns durability instead, and nothing is opened.
        """
        if self._checkpointer is None:
            from openstategraph.memory import build_checkpointer

            self._checkpointer = build_checkpointer(self.store.root)
        return self._checkpointer

    def checkpointer_for(
        self, settings: dict[str, Any] | None, slug: str | None
    ) -> BaseCheckpointSaver[Any]:
        """The saver a document asked for — opened once per workflow, not per call.

        `memory.checkpointer_for` is a pure resolver: given a document's
        settings it decides whether to open a per-workflow sqlite file. Every
        transport called it on **every** request, so a workflow with
        `settings.checkpointer: "sqlite"` opened a new connection to the same
        file per run, per stream, per resume — none of them closed. Keeping the
        cache here rather than in `memory` is the ownership rule again: the
        module that *opens* knows how, the object that *lives* decides when.

        It is correctness as well as economy: `SqliteSaver`'s only concurrency
        control is a `threading.Lock` held per instance, so two savers over one
        file are two locks guarding nothing.
        """
        from openstategraph.memory import checkpointer_for
        from openstategraph.api.workflow_store import InvalidSlugError, is_slug

        key = slug or ""
        if key and not is_slug(key):
            # The last mile of install-experience ticket 06. The transports
            # validate the slug where it enters — but this is the method that
            # turns one into `checkpoints-<slug>.sqlite`, and it is reachable
            # from MCP and from `load_workflow` as well as from HTTP, so the
            # rule is restated by the code that would break it. Raising, not
            # coercing: `slugify` would happily turn `../etc` into a fine slug
            # and open somebody else's file.
            raise InvalidSlugError(f"{slug!r} is not a valid workflow slug")
        if key in self._workflow_checkpointers:
            return self._workflow_checkpointers[key]
        resolved = checkpointer_for(
            settings, slug, self.checkpointer, workflows_root_dir=self.store.root
        )
        if resolved is self.checkpointer:
            # No per-workflow file was opened; nothing to own or to cache,
            # and caching it would pin a saver a later `close()` replaced.
            return resolved
        self._workflow_checkpointers[key] = resolved
        return resolved

    def close(self) -> None:
        """Release the sqlite handles this object opened. Idempotent.

        A long-lived transport builds one of these and keeps it; a script, a
        test or `load_workflow` builds one per use, and without this each one
        left a file descriptor open until the process died — langgraph's
        sqlite saver and store have no `close()` of their own.

        Deliberately does **not** touch `self._checkpointer` or
        `self._memory_store` through their properties: resolving either here
        would open the very file it is about to close. Both are lazy now, so
        this is a rule about two fields rather than one.
        """
        from openstategraph.memory import close_resource

        if self._owns_checkpointer and self._checkpointer is not None:
            close_resource(self._checkpointer)
            # Cleared so a second close is a no-op and a resurrected use gets a
            # fresh saver rather than a closed one.
            self._checkpointer = None
        for saver in self._workflow_checkpointers.values():
            close_resource(saver)
        self._workflow_checkpointers.clear()
        if self._owns_memory_store and self._memory_store is not None:
            close_resource(self._memory_store)
            # Cleared, exactly like the saver above: a second close is a no-op,
            # and a resurrected use gets a fresh store rather than a closed one
            # — which is also why `_owns_memory_store` is *not* flipped here.
            # It records who built the thing, not whether one is open.
            self._memory_store = None

    def __enter__(self) -> "WorkflowServices":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def tool_registry_for(
        self,
        slug: str | None,
        *,
        knowledge_dir: Any = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        registry = build_tool_registry(
            self.store, slug, knowledge_dir=knowledge_dir, warnings=warnings
        )
        # Last, therefore highest. A collision with a discovered tool is a
        # deliberate substitution and is deliberately NOT a warning: `warnings`
        # means "this run lost a capability", and filling it with something the
        # caller asked for is how a list that matters gets ignored.
        registry.update(self._injected_tools)
        return registry

    def function_registry_for(self, slug: str | None) -> dict[str, Any]:
        """`function.<name>` -> callable, discovery then the caller's over it.

        A method rather than a bare `build_function_registry` call at each use
        site, mirroring `tool_registry_for`, so the override is applied in one
        place and the parent runtime and a routed child cannot disagree.
        """
        registry = build_function_registry(self.store, slug)
        registry.update(self._injected_functions)
        return registry

    def middleware_for(self, slug: str | None) -> dict[str, Any]:
        """Slot name -> middleware: the package's `middlewares/`, caller over.

        Keyed by slot name exactly as `discover_middlewares` is, so an
        injected entry fills or replaces a slot by the same rule a file does
        (`middlewares/summarization.py`). The base still owns the canonical
        slot *order*; nothing here expresses a position.
        """
        from openstategraph.api.capability_discovery import discover_middlewares

        found = discover_middlewares(self.store.directory_for(slug), slug) if slug else {}
        found.update(self._injected_middleware)
        return found

    def runtime_for(
        self,
        slug: str | None,
        document: dict[str, Any],
        model: Any,
        *,
        audience: Any = None,
        knowledge_dir: Any = None,
        warnings: list[str] | None = None,
    ) -> Any:
        """One NodeRuntime construction shared by run/stream/resume — and now
        by MCP — so the call sites can never disagree about capabilities again.

        `audience` is the **generation** half of the audience boundary (see
        `api/audience.py`): only a `DEVELOPER` run gets the tool catalogue as
        an extra agent context block, so a customer run's agents are never
        told to propose an edit in the first place. The transport half lives
        in `streaming._stream_run`, which splits the fence out of the answer
        whatever the audience — two gates because they fail differently, one
        stopping us asking for it and one stopping it arriving anyway.

        Passed per call rather than baked in, because the same process serves
        the editor, `/chat` and MCP, and only one of them may ever propose
        edits to the canvas. Defaults to `CUSTOMER`: a caller that forgets
        gets the safe run, not the loud one.

        `knowledge_dir` is `load_workflow`'s explicit second-brain override.
        None — every transport but the artifact loader — keeps the convention
        (`<package>/knowledge`). It applies to THIS workflow only: a routed
        child still seeks its own package's knowledge, the same isolation
        ticket 67 established for skills.
        """
        from openstategraph.api.audience import Audience, resolve as resolve_audience
        from openstategraph.api.capability_discovery import discover_skills
        from openstategraph.compile.diagnostics import Finding
        from openstategraph.compile.node_runtime import (
            NodeRuntime,
            PackageAssets,
            RuntimeServices,
        )
        from openstategraph.api.registries import suggestible_tool_catalog

        for_audience = resolve_audience(audience)

        # Built once. `build_tool_registry` globs `tools/*.py` and
        # `exec_module`s every one of them (it deliberately bypasses
        # `sys.modules`), so calling it twice — as the developer path did,
        # once for `tools` and again for `advisor_catalog` — re-executed every
        # tool module of the open package on every editor run.
        # Every capability that failed to LOAD lands here — a half-installed
        # plugin (ticket 05) and a tool class discovery could not instantiate
        # (ticket 07) alike. The sink is created here rather than taken from
        # the caller so that *every* transport gets these, not only the one
        # that remembered to pass a list: they are hung on the runtime below,
        # and `runtime_warnings()` carries them to the run response, the CLI
        # and `CompiledWorkflow.warnings`. A caller's own list is still filled,
        # for compatibility — such a caller must not then add
        # `runtime_warnings()` on top, or it will report each finding twice.
        capability_warnings: list[str] = []
        tools = self.tool_registry_for(
            slug, knowledge_dir=knowledge_dir, warnings=capability_warnings
        )
        # The document's memory declaration, and everything it could not
        # honour. Both findings go on the same channel every other unresolved
        # capability uses, so a typo'd scope and a missing tool are reported
        # the same way rather than one of them being silent (ticket 03).
        from openstategraph.memory import memory_preconditions, memory_settings

        declared, memory_findings = memory_settings(document.get("settings"))
        capability_warnings.extend(memory_findings)
        capability_warnings.extend(memory_preconditions(declared, store=self.memory_store))
        if warnings is not None:
            warnings.extend(capability_warnings)
        # Named for what it is. It was `store = self.store` seventeen lines
        # above `store=self.memory_store`, in one function body — the
        # collision ticket 12 was opened for, in the class every transport
        # goes through.
        packages = self.store

        runtime = NodeRuntime(
            services=RuntimeServices(
                model=model,
                tools=tools,
                functions=self.function_registry_for(slug),
                document_loader=lambda child_slug: normalize_document(packages.load(child_slug)),
                package_loader=lambda child_slug: PackageAssets(
                    tools=self.tool_registry_for(child_slug),
                    functions=self.function_registry_for(child_slug),
                    skills_context=discover_skills(packages.directory_for(child_slug)),
                    workflow_middleware=self.middleware_for(child_slug),
                    # A routed child seeks ITS OWN second brain, never the
                    # parent's — the same isolation as skills (ticket 67).
                    knowledge_dir=packages.directory_for(child_slug),
                ),
                memory_store=self.memory_store,
                memory=declared,
                skills_context=(discover_skills(packages.directory_for(slug)) if slug else ""),
                workflow_middleware=self.middleware_for(slug),
                # Ambient knowledge seeking: a non-empty knowledge/ under the
                # open package auto-binds the lookup tool to every agent.
                knowledge_package_dir=(packages.directory_for(slug) if slug else None),
                knowledge_dir_override=knowledge_dir,
                advisor_catalog=(
                    suggestible_tool_catalog(tools)
                    if for_audience is Audience.DEVELOPER
                    else ""
                ),
            )
        )
        for capability_warning in capability_warnings:
            runtime.diagnostics.record(Finding.CAPABILITY_FAILED, capability_warning)
        return runtime


# No `__all__` here on purpose. In Python `__all__` reads as "this is the
# public surface", and this module is Tier 3 — internal, no stability
# guarantee (see `openstategraph/api/__init__.py`). The names it exported
# were the ones it hands its own siblings, and a third party would have read
# that as a promise. `openstategraph.__all__` and `openstategraph.abc` are
# the promises.
