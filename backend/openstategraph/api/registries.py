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



def build_tool_registry(
    workflow_store: Any,
    slug: str | None,
    *,
    knowledge_dir: Any = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Default tools, with installed plugins and then the workflow's own over.

    The defaults (Chinook) stay so documents that bind them — e.g. the
    chinook-nl-to-sql example mounted as a subgraph elsewhere — keep working
    from any workflow context. A slug adds
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

    `warnings` is an optional sink. Entry-point failures are process-level, not
    runtime-level, so they have no `NodeRuntime` field to land on — a caller
    that reports capability warnings (`load_workflow`) passes a list and gets
    them; every other caller gets the log line and nothing more.
    """
    from openstategraph.api.capability_discovery import discover_tool_registry
    from openstategraph.compile.node_runtime import chinook_tool_registry

    from openstategraph.prebuilt_sql import SQL_EXPLORER_TOOLS

    registry: dict[str, Any] = {}
    try:
        registry.update(chinook_tool_registry())
    except Exception:
        # The bundled Chinook tools live in `workflows/chinook-nl-to-sql/tools`,
        # which is only importable inside *this* checkout (pytest.ini puts that
        # directory on the path). Outside it — a consumer running their own
        # package through `load_workflow` — the import raises, and it used to
        # take the whole registry down before a single one of *their* tools was
        # discovered. Debug, not warning: a demo fixture being absent is normal
        # elsewhere, and a document that actually binds a chinook tool still
        # reports it loudly through `unresolved_tools`.
        logger.debug("Bundled Chinook tools unavailable in this environment", exc_info=True)
    # Prebuilt SQL Explorer (ticket 66): any workflow can point these at its
    # own .sqlite file — the user's N-tables-with-JOIN-rules case as config.
    registry.update({tool.node_type: tool for tool in SQL_EXPLORER_TOOLS})
    from openstategraph.prebuilt_platform import PLATFORM_TOOLS

    # Read-only platform introspection (ticket 67, user spec: "no write,
    # everything else") — list/describe workflows, jailed ls/read/grep.
    registry.update({tool.node_type: tool for tool in PLATFORM_TOOLS})
    from openstategraph.prebuilt_web import WEB_TOOLS

    # The open web, read-only (search + SSRF-guarded fetch) — the root
    # assistant's generic-chat requirement (ticket 67 refinement).
    registry.update({tool.node_type: tool for tool in WEB_TOOLS})
    from openstategraph.prebuilt_architect import ARCHITECT_TOOLS

    # The compiler as a tool (ticket 69): read-only compile-checking, the
    # Architect's revise-loop evidence.
    registry.update({tool.node_type: tool for tool in ARCHITECT_TOOLS})
    from openstategraph.prebuilt_email import EMAIL_TOOLS

    # Report delivery (full-sweep capability test): SMTP when configured,
    # loud .eml dry-run otherwise. Recipient is node config, never a model arg.
    registry.update({tool.node_type: tool for tool in EMAIL_TOOLS})
    from openstategraph.prebuilt_knowledge import knowledge_lookup_for

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
    # never an exception (`openstategraph.extensions`).
    from openstategraph.extensions import entry_point_tools

    discovered = entry_point_tools()
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
            registry.update(discover_tool_registry(workflow_store.directory_for(slug), slug))
        except Exception:
            logger.warning("Tool discovery failed for %r", slug, exc_info=True)
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



def runtime_warnings(runtime: Any) -> list[str]:
    """Every "this step silently lost a capability" condition, spelled out."""
    warnings: list[str] = []
    for tool_type in runtime.unresolved_tools:
        warnings.append(
            f'No implementation for tool "{tool_type}" — the agent ran without it, '
            "so its answer may not be grounded in that data source."
        )
    for fn_type in runtime.unresolved_functions:
        warnings.append(
            f'No function found for "{fn_type}" — the step passed its input through unchanged.'
        )
    for slug_name in runtime.unresolved_subgraphs:
        warnings.append(
            f'Subgraph workflow "{slug_name}" could not be loaded — the node produced nothing.'
        )
    for override_warning in getattr(runtime, "override_warnings", []):
        warnings.append(f"Mount override — {override_warning}")
    return warnings

