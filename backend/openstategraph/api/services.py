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

from typing import Any

from openstategraph.api.registries import (
    build_function_registry,
    build_tool_registry,
)
from openstategraph.schema import normalize_document
from openstategraph.api.workflow_store import WorkflowStore


class WorkflowServices:
    """Store + memory + the one runtime construction every transport shares.

    Every collaborator here is the caller's to supply. `store`, `tools`,
    `functions` and `middleware` are the injection seam behind
    `load_workflow`'s parameters of the same names; omitting one keeps the
    behaviour that existed before the parameter did (an env-driven
    `build_store()`, and discovery alone for capabilities).

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
        store: Any = None,
        checkpointer: Any = None,
        tools: dict[str, Any] | None = None,
        functions: dict[str, Any] | None = None,
        middleware: dict[str, Any] | None = None,
    ) -> None:
        from openstategraph.memory import build_store

        self.store = WorkflowStore(root=workflows_root)
        #: Long-term memory, process-wide (ticket 65): one Store shared by
        #: every run, namespaced per user inside the tools themselves.
        #: Injectable, because its sibling the checkpointer always was: a
        #: caller who owns their own durability must be able to own both, and
        #: a `build_store()` call hidden in a constructor made the memory half
        #: unreachable — an `InMemoryStore` that looks like it works and loses
        #: every fact on restart.
        self.memory_store = store if store is not None else build_store()
        #: Ownership, recorded at construction rather than inferred at close.
        #: What we opened, we close; what the caller injected stays theirs and
        #: is still in use after we are done with it. Inferring this later
        #: (say, "close it if it has a `.conn`") would close a caller's own
        #: sqlite saver and break the process that lent it to us.
        self._owns_memory_store = store is None
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
        self._workflow_checkpointers: dict[str, Any] = {}
        # Copied, not aliased: a caller's dict must not become live state that
        # a later mutation of theirs changes mid-run.
        self._injected_tools = dict(tools or {})
        self._injected_functions = dict(functions or {})
        self._injected_middleware = dict(middleware or {})

    @property
    def checkpointer(self) -> Any:
        """The one saver every transport compiles against, built on first ask.

        Durable by default — `build_checkpointer` puts it under this services
        object's own workflows root, and says so in one log line. A caller who
        passed `checkpointer=` owns durability instead, and nothing is opened.
        """
        if self._checkpointer is None:
            from openstategraph.memory import build_checkpointer

            self._checkpointer = build_checkpointer(self.store.root)
        return self._checkpointer

    def checkpointer_for(self, settings: dict[str, Any] | None, slug: str | None) -> Any:
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

        key = slug or ""
        if key in self._workflow_checkpointers:
            return self._workflow_checkpointers[key]
        resolved = checkpointer_for(settings, slug, self.checkpointer)
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

        Deliberately does **not** touch `self._checkpointer` through the
        property: resolving it here would open the very file it is about to
        close.
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
        if self._owns_memory_store and self.memory_store is not None:
            close_resource(self.memory_store)
            self._owns_memory_store = False

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
        advisor: bool = False,
        knowledge_dir: Any = None,
        warnings: list[str] | None = None,
    ) -> Any:
        """One NodeRuntime construction shared by run/stream/resume — and now
        by MCP — so the call sites can never disagree about capabilities again.

        `advisor` is the editor-only capability-gap flag: it turns the tool
        catalogue into an extra agent context block (see `advisor_context`).
        Passed per call rather than baked in, because the same process serves
        the editor, `/chat` and MCP, and only one of them may ever propose
        edits to the canvas.

        `knowledge_dir` is `load_workflow`'s explicit second-brain override.
        None — every transport but the artifact loader — keeps the convention
        (`<package>/knowledge`). It applies to THIS workflow only: a routed
        child still seeks its own package's knowledge, the same isolation
        ticket 67 established for skills.
        """
        from openstategraph.api.capability_discovery import discover_skills
        from openstategraph.compile.node_runtime import (
            NodeRuntime,
            PackageAssets,
            RuntimeServices,
        )
        from openstategraph.api.registries import suggestible_tool_catalog

        # Built once. `build_tool_registry` globs `tools/*.py` and
        # `exec_module`s every one of them (it deliberately bypasses
        # `sys.modules`), so calling it twice — as the `advisor=True` path did,
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
        if warnings is not None:
            warnings.extend(capability_warnings)
        store = self.store

        runtime = NodeRuntime(
            services=RuntimeServices(
                model=model,
                tools=tools,
                functions=self.function_registry_for(slug),
                document_loader=lambda child_slug: normalize_document(store.load(child_slug)),
                package_loader=lambda child_slug: PackageAssets(
                    tools=self.tool_registry_for(child_slug),
                    functions=self.function_registry_for(child_slug),
                    skills_context=discover_skills(store.directory_for(child_slug)),
                    workflow_middleware=self.middleware_for(child_slug),
                    # A routed child seeks ITS OWN second brain, never the
                    # parent's — the same isolation as skills (ticket 67).
                    knowledge_dir=store.directory_for(child_slug),
                ),
                store=self.memory_store,
                skills_context=(discover_skills(store.directory_for(slug)) if slug else ""),
                workflow_middleware=self.middleware_for(slug),
                # Ambient knowledge seeking: a non-empty knowledge/ under the
                # open package auto-binds the lookup tool to every agent.
                knowledge_package_dir=(store.directory_for(slug) if slug else None),
                knowledge_dir_override=knowledge_dir,
                advisor_catalog=(suggestible_tool_catalog(tools) if advisor else ""),
            )
        )
        runtime.capability_warnings.extend(capability_warnings)
        return runtime


# No `__all__` here on purpose. In Python `__all__` reads as "this is the
# public surface", and this module is Tier 3 — internal, no stability
# guarantee (see `openstategraph/api/__init__.py`). The names it exported
# were the ones it hands its own siblings, and a third party would have read
# that as a promise. `openstategraph.__all__` and `openstategraph.abc` are
# the promises.
