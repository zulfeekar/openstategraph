"""Capability assembly: documents, tool/function registries, runtime warnings (ticket 72 split)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _document_of(workflow: dict[str, Any]) -> dict[str, Any]:
    """Accepts a bare document or the store's `{…, document}` envelope.

    The store saves `{version, name, savedAt, document}`; the editor's export
    posts the bare document. Both arrive at the run endpoints, and compiling
    the *envelope* silently produces a zero-node graph — so every endpoint
    unwraps through this one helper, resume included.
    """
    inner = workflow.get("document")
    return inner if isinstance(inner, dict) else workflow



def build_tool_registry(workflow_store: Any, slug: str | None) -> dict[str, Any]:
    """Default tools, with the open workflow's own tools layered over.

    The defaults (Chinook) stay so documents that bind them — the
    intent-routed demo — keep working from any workflow context. A slug adds
    that workflow's `tools/`, keyed by each tool's own `node_type`
    declaration (ticket 33); same-type collisions resolve workflow-wins,
    mirroring the frontend's local-shadows-global registry rule. A failed
    discovery degrades to the defaults with a log line, never a crash —
    `NodeRuntime.unresolved_tools` keeps missing bindings loud.
    """
    from openstategraph.api.capability_discovery import discover_tool_registry
    from openstategraph.compile.node_runtime import chinook_tool_registry

    from openstategraph.prebuilt_sql import SQL_EXPLORER_TOOLS

    registry: dict[str, Any] = chinook_tool_registry()
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
    if slug:
        try:
            registry.update(discover_tool_registry(workflow_store.directory_for(slug), slug))
        except Exception:
            logger.warning("Tool discovery failed for %r", slug, exc_info=True)
    return registry



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
    return warnings

