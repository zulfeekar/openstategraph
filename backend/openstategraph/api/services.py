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
    """Store + memory + the one runtime construction every transport shares."""

    def __init__(self, workflows_root: Any = None) -> None:
        from openstategraph.memory import build_store

        self.store = WorkflowStore(root=workflows_root)
        #: Long-term memory, process-wide (ticket 65): one Store shared by
        #: every run, namespaced per user inside the tools themselves.
        self.memory_store = build_store()

    def tool_registry_for(self, slug: str | None) -> dict[str, Any]:
        return build_tool_registry(self.store, slug)

    def runtime_for(
        self,
        slug: str | None,
        document: dict[str, Any],
        model: Any,
        *,
        advisor: bool = False,
    ) -> Any:
        """One NodeRuntime construction shared by run/stream/resume — and now
        by MCP — so the call sites can never disagree about capabilities again.

        `advisor` is the editor-only capability-gap flag: it turns the tool
        catalogue into an extra agent context block (see `advisor_context`).
        Passed per call rather than baked in, because the same process serves
        the editor, `/chat` and MCP, and only one of them may ever propose
        edits to the canvas.
        """
        from openstategraph.api.capability_discovery import discover_middlewares, discover_skills
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
        tools = self.tool_registry_for(slug)
        store = self.store

        return NodeRuntime(
            services=RuntimeServices(
                model=model,
                tools=tools,
                functions=build_function_registry(store, slug),
                document_loader=lambda child_slug: normalize_document(store.load(child_slug)),
                package_loader=lambda child_slug: PackageAssets(
                    tools=self.tool_registry_for(child_slug),
                    functions=build_function_registry(store, child_slug),
                    skills_context=discover_skills(store.directory_for(child_slug)),
                    workflow_middleware=discover_middlewares(
                        store.directory_for(child_slug), child_slug
                    ),
                    # A routed child seeks ITS OWN second brain, never the
                    # parent's — the same isolation as skills (ticket 67).
                    knowledge_dir=store.directory_for(child_slug),
                ),
                store=self.memory_store,
                skills_context=(discover_skills(store.directory_for(slug)) if slug else ""),
                workflow_middleware=(
                    discover_middlewares(store.directory_for(slug), slug) if slug else {}
                ),
                # Ambient knowledge seeking: a non-empty knowledge/ under the
                # open package auto-binds the lookup tool to every agent.
                knowledge_package_dir=(store.directory_for(slug) if slug else None),
                advisor_catalog=(suggestible_tool_catalog(tools) if advisor else ""),
            )
        )


# No `__all__` here on purpose. In Python `__all__` reads as "this is the
# public surface", and this module is Tier 3 — internal, no stability
# guarantee (see `openstategraph/api/__init__.py`). The names it exported
# were the ones it hands its own siblings, and a third party would have read
# that as a promise. `openstategraph.__all__` and `openstategraph.abc` are
# the promises.
