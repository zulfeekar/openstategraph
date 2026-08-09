"""Prebuilt knowledge lookup — the runtime face of the second brain.

One tool, ``tool.knowledge-lookup``, bound per open workflow to that
package's ``knowledge/`` directory (see ``build_tool_registry``: the slug's
validated directory is injected at registry-build time, the same jail
``WorkflowStore.directory_for`` enforces everywhere else — a canvas can
never point this tool outside ``workflows/``).

**On demand, never prompt-stuffed**: the agent calls this with a topic the
moment it needs it, instead of every topic riding along in every system
prompt (the ``skills/`` failure mode at scale). An unknown topic answers
with the list of available topics, so a wrong table name costs one tool
round-trip, not a dead end.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, ToolResult
from openstategraph.knowledge import PackageKnowledge, UnknownTopicError


class KnowledgeLookupArgs(BaseModel):
    model_config = {"extra": "forbid"}
    topic: str = Field(
        description="The topic to look up — usually an exact table name."
    )


class KnowledgeLookupTool(BaseTool):
    """Reads one topic from the open workflow's second brain."""

    name = "knowledge_lookup"
    node_type = "tool.knowledge-lookup"
    description = (
        "Before querying a table, look up its knowledge: business meaning, "
        "column semantics, JOIN rules, and caveats. Pass the table name as "
        "the topic. An unknown topic returns the list of available topics."
    )
    Args = KnowledgeLookupArgs

    def __init__(self, package_dir: Path | None = None) -> None:
        self._package_dir = Path(package_dir) if package_dir else None
        self._knowledge = PackageKnowledge(package_dir) if package_dir else None

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, KnowledgeLookupArgs)
        if self._knowledge is None:
            return ToolResult.failure(
                "No workflow package is bound — knowledge lookup only works "
                "for a saved, open workflow."
            )
        try:
            return ToolResult(content=self._knowledge.lookup(args.topic))
        except UnknownTopicError as exc:
            if not exc.available:
                return ToolResult.failure(
                    "This workflow has no knowledge docs yet. Use 'Build "
                    "second brain' on the Knowledge node (or add "
                    "knowledge/<topic>.md files) to create them."
                )
            return ToolResult.failure(
                f"No knowledge for topic '{args.topic}'. Available topics: "
                + ", ".join(exc.available)
            )


def knowledge_lookup_for(package_dir: Path | None) -> dict[str, Any]:
    """The registry fragment: node type → a tool bound to one package dir."""
    return {KnowledgeLookupTool.node_type: KnowledgeLookupTool(package_dir=package_dir)}


__all__ = ["KnowledgeLookupArgs", "KnowledgeLookupTool", "knowledge_lookup_for"]
