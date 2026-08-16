"""Capability assembly: documents, tool/function registries, runtime warnings (ticket 72 split)."""

from __future__ import annotations

import logging
from typing import Any

from openstategraph.schema import normalize_document

logger = logging.getLogger(__name__)


#: **Deprecated alias.** The real implementation moved to the public
#: `openstategraph.schema.normalize_document` (ticket 03: the documented public
#: loader must not import an underscore-prefixed name out of the internal HTTP
#: tree). Kept as a re-export, not a second function, so anything still
#: importing this name gets the *same* object and the version guard has one
#: seam rather than two. Import `openstategraph.schema` in new code.
_document_of = normalize_document



#: The part of the tool registry that cannot change while the process runs:
#: the bundled tools, and the tools installed distributions contribute.
#:
#: Cached because it was being rebuilt on **every** run, stream and subgraph
#: child, and `importlib.metadata.entry_points()` re-walks every installed
#: distribution's metadata each time it is called. Measured on this checkout:
#: `WorkflowServices.runtime_for` cost 14.8 ms steady-state, 12.2 ms of it in
#: that one scan — 82% of the call spent rediscovering an answer that only a
#: `pip install` can change, and a `pip install` means a restart (the dev
#: server reloads on any file save; a deployment redeploys).
#:
#: **What remains cached here is the BUNDLED half only.** The entry-point half
#: moved to `openstategraph.extensions._CACHE`, which is where an earlier note
#: on this constant said it belonged: the tools group was never the only one
#: paying that scan — `entry_point_knowledge_builders` and
#: `entry_point_providers` each re-walked every distribution on every call, and
#: memoising the mechanism at one of its three call sites left the other two
#: paying full price for a shared answer. So `extensions` owns the discovery
#: cache and this module keeps only what is genuinely its own: the assembled
#: built-in layer (`chinook_tool_registry()` plus five prebuilt families), whose
#: cost is imports rather than a `sys.path` walk.
_PROCESS_LAYER: tuple[dict[str, Any], Any] | None = None


def reset_process_tool_layer() -> None:
    """Drop every process-lifetime discovery cache. For tests that fake plugins.

    `conftest.py` calls this between every test, so a fake plugin installed by
    one test can never survive into the next — the failure mode a
    process-lifetime cache introduces if nobody names it.

    It now clears **all three** entry-point groups, not just tools. When the
    cache covered one group the name was accurate; the moment providers and
    knowledge builders are memoised too, a hook that resets only the tool layer
    is worse than none — it looks like isolation and is not, so a test faking a
    provider entry point would leak into every test that ran after it.
    """
    global _PROCESS_LAYER
    _PROCESS_LAYER = None

    from openstategraph.extensions import reset_entry_point_cache

    reset_entry_point_cache()


def _process_tool_layer() -> tuple[dict[str, Any], Any]:
    """`(built-in tools, Discovered plugin tools)` — built at most once."""
    global _PROCESS_LAYER
    if _PROCESS_LAYER is not None:
        return _PROCESS_LAYER

    from openstategraph.compile.node_runtime import chinook_tool_registry
    from openstategraph.extensions import entry_point_tools
    from openstategraph.prebuilt_architect import ARCHITECT_TOOLS
    from openstategraph.prebuilt_email import EMAIL_TOOLS
    from openstategraph.prebuilt_mcp import MCP_TOOLS
    from openstategraph.prebuilt_platform import PLATFORM_TOOLS
    from openstategraph.prebuilt_session import SESSION_TOOLS
    from openstategraph.prebuilt_sql import SQL_EXPLORER_TOOLS
    from openstategraph.prebuilt_web import WEB_TOOLS
    from openstategraph.prebuilt_youtube import YOUTUBE_TOOLS

    builtin: dict[str, Any] = {}
    try:
        builtin.update(chinook_tool_registry())
    except Exception:
        # The bundled Chinook tools live in `workflows/chinook-assistant/tools`,
        # which is only importable inside *this* checkout (pytest.ini puts that
        # directory on the path). Outside it — a consumer running their own
        # package through `load_workflow` — the import raises, and it used to
        # take the whole registry down before a single one of *their* tools was
        # discovered. Debug, not warning: a demo fixture being absent is normal
        # elsewhere, and a document that actually binds a chinook tool still
        # reports it loudly through `unresolved_tools`.
        logger.debug("Bundled Chinook tools unavailable in this environment", exc_info=True)
    for family in (
        # Prebuilt SQL Explorer (ticket 66): any workflow can point these at its
        # own .sqlite file — the user's N-tables-with-JOIN-rules case as config.
        SQL_EXPLORER_TOOLS,
        # Read-only platform introspection (ticket 67, user spec: "no write,
        # everything else") — list/describe workflows, jailed ls/read/grep.
        PLATFORM_TOOLS,
        # The open web, read-only (search + SSRF-guarded fetch) — the root
        # assistant's generic-chat requirement (ticket 67 refinement).
        WEB_TOOLS,
        # One video's captions as plain text (workflow-gallery ticket 09).
        # Beside the web family because it is the same promise — keyless,
        # read-only, no account — but it cannot be `web_fetch`: the only route
        # that returns caption text is a JSON POST to InnerTube followed by a
        # GET of the URL that answer issues, and a POST body is not a `url`.
        YOUTUBE_TOOLS,
        # The compiler as a tool (ticket 69): read-only compile-checking, the
        # Architect's revise-loop evidence.
        ARCHITECT_TOOLS,
        # Report delivery (full-sweep capability test): SMTP when configured,
        # loud .eml dry-run otherwise. Recipient is node config, never a model arg.
        EMAIL_TOOLS,
        # Who is asking and which conversation this is (ticket 03). Identity
        # already rode in `configurable` and already namespaced memory; this
        # is the one seam that lets a prompt read it — and, like the email
        # recipient, it takes no arguments, so the model can ask but never
        # claim.
        SESSION_TOOLS,
        # One card, a whole MCP server's tools (mcp-connect ticket 02). The
        # only member of this registry that discovers what it contributes over
        # the network, and therefore the only one that can contribute *none*
        # and say why — see `McpTool.as_langchain_tools`.
        MCP_TOOLS,
    ):
        builtin.update({tool.node_type: tool for tool in family})

    _PROCESS_LAYER = (builtin, entry_point_tools())
    return _PROCESS_LAYER


def process_tool_layer() -> tuple[dict[str, Any], Any]:
    """`(built-in tools, Discovered plugin tools)` — a copy of the layer above.

    The read-only door onto the cache `build_tool_registry` itself layers, for
    surfaces that need to *describe* what the runtime can bind rather than bind
    it (the capabilities endpoint, register PK-06). Same objects, one source:
    a palette fed from here can never offer a tool the runtime lacks, which is
    exactly the failure a second, hand-kept list would eventually produce.

    The built-in dict is copied on the way out for the same reason
    `build_tool_registry` copies it — one caller's mutation must not become
    every later caller's registry.
    """
    builtin, discovered = _process_tool_layer()
    return dict(builtin), discovered


def build_tool_registry(
    workflow_store: Any,
    slug: str | None,
    *,
    knowledge_dir: Any = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Default tools, with installed plugins and then the workflow's own over.

    The defaults (Chinook) stay so documents that bind them — e.g. the
    chinook-assistant example mounted as a subgraph by the gateway — keep
    working from any workflow context. A slug adds
    that workflow's `tools/`, keyed by each tool's own `node_type`
    declaration (ticket 33); same-type collisions resolve workflow-wins,
    mirroring the frontend's local-shadows-global registry rule. A failed
    discovery degrades to the defaults with a log line, never a crash —
    `NodeRuntime.unresolved_tools` keeps missing bindings loud.

    **Three sources, in one fixed order: built-in < third-party <
    workflow-local** (ticket 05, `openstategraph.extensions`). Installing a
    plugin is how you replace a bundled default; nothing installed can outrank
    a package's own `tools/`, or a workflow's behaviour would depend on an
    unrelated `pip install`.

    `warnings` is an optional sink for **everything that failed to load** —
    entry-point failures (ticket 05) and, since ticket 07, workflow-local
    discovery findings: a tool module that would not import, a class left
    abstract, two classes claiming one `node_type`. A caller that passes a list
    gets them; a caller that does not still gets the log lines. In practice
    every transport passes one, because `WorkflowServices.runtime_for` supplies
    the list and hangs it on `NodeRuntime.capability_warnings`, from where
    `runtime_warnings()` carries it to the run response, `load_workflow`'s
    `CompiledWorkflow.warnings` and the CLI.
    """
    from openstategraph.api.capability_discovery import discover_tool_registry
    from openstategraph.prebuilt_knowledge import knowledge_lookup_for

    builtin, discovered = _process_tool_layer()
    # Copied, never handed out: the built-in layer is shared across every run
    # in the process, and one caller's `registry[...] = ...` would otherwise
    # become every later caller's tool.
    registry: dict[str, Any] = dict(builtin)

    # The second brain (knowledge layer): registered unbound so the node type
    # always resolves, then re-bound below to the open workflow's own
    # knowledge/ directory — the same validated jail every slug path uses.
    # `knowledge_dir` is the explicit override a consumer passed to
    # `load_workflow`; it names the topic directory itself and wins over the
    # slug's conventional `knowledge/`, exactly as a positional argument
    # should win over a discovered default.
    registry.update(knowledge_lookup_for(None, knowledge_dir=knowledge_dir))

    # Third party, layered over every built-in above and under the package's
    # own tools below. Jailed: a broken distribution contributes a warning,
    # never an exception (`openstategraph.extensions`). Resolved once per
    # process — see `_process_tool_layer`.
    registry.update(discovered.values)
    if warnings is not None:
        warnings.extend(discovered.warnings)

    if slug:
        try:
            registry.update(
                knowledge_lookup_for(
                    workflow_store.directory_for(slug), knowledge_dir=knowledge_dir
                )
            )
        except Exception:
            logger.warning("Knowledge binding failed for %r", slug, exc_info=True)
        try:
            registry.update(
                discover_tool_registry(
                    workflow_store.directory_for(slug), slug, warnings=warnings
                )
            )
        except Exception as exc:
            # The whole discovery pass failing (an unreadable directory, a
            # store that cannot resolve the slug) loses every tool the package
            # ships, so it is surfaced too, not only logged — ticket 07's rule
            # applied to the outermost skip in this chain.
            message = (
                f"Tool discovery failed for workflow {slug!r} "
                f"({type(exc).__name__}: {exc}) — none of its own tools are available."
            )
            logger.warning(message, exc_info=True)
            if warnings is not None:
                warnings.append(message)
    return registry



#: Tool families an advisor may propose adding to a running workflow.
#:
#: A prefix allow-list rather than "everything in the registry": a suggestion
#: is only useful if the editor can place the node with **no configuration** —
#: `tool.chinook-*` is bound to one bundled database and a discovered
#: `tool.<workflow>-*` needs the file that defines it, so proposing either
#: would produce a node that looks wired and answers nothing. The families
#: below are self-contained (web, platform introspection) or carry their own
#: config field the developer fills in afterwards (email's recipient).
SUGGESTIBLE_TOOL_PREFIXES = (
    "tool.web-",
    "tool.platform-",
    "tool.sql-",
    "tool.email-",
    "tool.knowledge-",
)


def suggestible_tool_catalog(registry: dict[str, Any]) -> str:
    """The advisor's menu: one `- <node_type> — <description>` line per tool.

    Built from the registry the run itself was given, never a hand-kept list,
    so a tool added to `build_tool_registry` becomes suggestible by existing
    and cannot drift out of sync with what the runtime can actually bind.
    Descriptions come from each tool's own `description`, which is the same
    text the model already sees when the tool *is* bound — so "what this tool
    would give me" reads identically before and after the wiring.
    """
    lines: list[str] = []
    for node_type in sorted(registry):
        if not node_type.startswith(SUGGESTIBLE_TOOL_PREFIXES):
            continue
        description = " ".join(str(getattr(registry[node_type], "description", "")).split())
        lines.append(f"- {node_type} — {description}" if description else f"- {node_type}")
    return "\n".join(lines)


def build_function_registry(workflow_store: Any, slug: str | None) -> dict[str, Any]:
    """`function.<name>` -> callable, from the workflow's own `functions/`.

    Mirrors `build_tool_registry`: slug-scoped, degrade-loud (the runtime
    records an unresolved function; discovery failures log and return {}).
    """
    from openstategraph.api.capability_discovery import discover_function_callables

    if not slug:
        return {}
    try:
        return discover_function_callables(workflow_store.directory_for(slug), slug)
    except Exception:
        logger.warning("Function discovery failed for %r", slug, exc_info=True)
        return {}



class CapabilityRegistries:
    """What a run inside a package may reach: tools, functions, middleware.

    One object because it is one question asked three ways, with one rule
    running through all three answers — **discovery first, the caller's
    injection last and therefore highest**. Built-in < plugin < package-local <
    caller: the filesystem describes what a package *shipped*, an argument
    describes what *this process* is to run, and only the caller can know which
    of the two is right.

    Extracted from `WorkflowServices` (install-experience 20), where the same
    three methods were public members with no caller outside the class — three
    public factories serving one internal `runtime_for` a few lines below them,
    which is an injection cluster behind a public door. It has its own reason to
    change (what a capability is, and who outranks whom) and it does not move
    when the store, the checkpointer or the lifecycle does, which is what makes
    it a collaborator rather than a grouping invented to satisfy a count.
    """

    def __init__(
        self,
        store: Any,
        *,
        tools: dict[str, Any] | None = None,
        functions: dict[str, Any] | None = None,
        middleware: dict[str, Any] | None = None,
    ) -> None:
        self._store = store
        # Copied, not aliased: a caller's dict must not become live state that
        # a later mutation of theirs changes mid-run.
        self._tools = dict(tools or {})
        self._functions = dict(functions or {})
        self._middleware = dict(middleware or {})

    def tools(
        self,
        slug: str | None,
        *,
        knowledge_dir: Any = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        registry = build_tool_registry(
            self._store, slug, knowledge_dir=knowledge_dir, warnings=warnings
        )
        # Last, therefore highest. A collision with a discovered tool is a
        # deliberate substitution and is deliberately NOT a warning: `warnings`
        # means "this run lost a capability", and filling it with something the
        # caller asked for is how a list that matters gets ignored.
        registry.update(self._tools)
        return registry

    def functions(self, slug: str | None) -> dict[str, Any]:
        """`function.<name>` -> callable, discovery then the caller's over it.

        A method rather than a bare `build_function_registry` call at each use
        site, mirroring `tools`, so the override is applied in one place and
        the parent runtime and a routed child cannot disagree.
        """
        registry = build_function_registry(self._store, slug)
        registry.update(self._functions)
        return registry

    def middleware(self, slug: str | None) -> dict[str, Any]:
        """Slot name -> middleware: the package's `middlewares/`, caller over.

        Keyed by slot name exactly as `discover_middlewares` is, so an
        injected entry fills or replaces a slot by the same rule a file does
        (`middlewares/summarization.py`). The base still owns the canonical
        slot *order*; nothing here expresses a position.
        """
        from openstategraph.api.capability_discovery import discover_middlewares

        found = discover_middlewares(self._store.directory_for(slug), slug) if slug else {}
        found.update(self._middleware)
        return found


def runtime_warnings(runtime: Any) -> list[str]:
    """Every "this step silently lost a capability" condition, spelled out.

    A pass-through now. This function used to reach across into seven separate
    lists on `NodeRuntime` and build the sentences itself — three of them via
    `getattr(runtime, name, [])`, because it could not rely on the attribute
    being there (reviews-2026-08-14 ticket 07). The findings and the sentences
    they produce live together on `CompileDiagnostics`.

    Kept as a function rather than deleted: it is the name the API layer and
    the adoption interface call, and what a warning *is* should not be a
    detail those layers have to know.
    """
    return list(runtime.diagnostics.warnings())

