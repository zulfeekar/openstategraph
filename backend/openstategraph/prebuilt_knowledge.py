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
        default="",
        description=(
            "The topic to look up — usually an exact table name. Omit it, "
            "or pass an empty string, to get the free index tier: every "
            "topic name with its one-line hint, at no cost of a wrong "
            "guess."
        ),
    )


class KnowledgeLookupTool(BaseTool):
    """Reads one topic from the open workflow's second brain."""

    name = "knowledge_lookup"
    #: Reads only — `launch-readiness` 121. Running it twice changes nothing.
    side_effecting = False
    node_type = "tool.knowledge-lookup"
    description = (
        "Before querying a table, look up its knowledge: business meaning, "
        "column semantics, JOIN rules, and caveats. Pass the table name as "
        "the topic. Call with no topic (or an empty topic) first to see the "
        "free index of every topic and its one-line hint — this always "
        "succeeds, even when nothing has been indexed yet. An unknown named "
        "topic also returns the list of available topics."
    )
    Args = KnowledgeLookupArgs

    def __init__(
        self,
        package_dir: Path | str | None = None,
        *,
        knowledge_dir: Path | str | None = None,
    ) -> None:
        self._package_dir = Path(package_dir) if package_dir else None
        self._knowledge_dir = Path(knowledge_dir) if knowledge_dir else None
        #: `None` when nothing is bound; every read guards for it.
        self._knowledge: PackageKnowledge | None
        if self._knowledge_dir is not None:
            self._knowledge = PackageKnowledge(knowledge_dir=self._knowledge_dir)
        elif self._package_dir is not None:
            self._knowledge = PackageKnowledge(self._package_dir)
        else:
            self._knowledge = None

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, KnowledgeLookupArgs)
        if self._knowledge is None:
            return ToolResult.failure(
                "No workflow package is bound — knowledge lookup only works "
                "for a saved, open workflow."
            )
        if not args.topic.strip():
            return self._index_reply()
        try:
            return ToolResult(content=self._knowledge.lookup(args.topic))
        except UnknownTopicError as exc:
            if not exc.available:
                return ToolResult.failure(self._no_docs_yet_message())
            return ToolResult.failure(
                f"No knowledge for topic '{args.topic}'. Available topics:\n"
                f"{self._listing(exc.available)}"
            )

    def _index_reply(self) -> ToolResult:
        """The free index tier, asked for directly — a first-class call that
        always succeeds, unlike the miss-menu it shares its formatting with.
        """
        assert self._knowledge is not None
        topics = self._knowledge.topics()
        if not topics:
            return ToolResult(content=self._no_docs_yet_message())
        return ToolResult(content=f"Available topics:\n{self._listing(topics)}")

    @staticmethod
    def _listing(entries: list[Any]) -> str:
        return "\n".join(
            f"- {entry.name} — {entry.hint}" if entry.hint else f"- {entry.name}"
            for entry in entries
        )

    @staticmethod
    def _no_docs_yet_message() -> str:
        return (
            "This workflow has no knowledge docs yet. Use 'Build second "
            "brain' on the Knowledge node (or add knowledge/<topic>.md "
            "files) to create them."
        )


def knowledge_lookup_for(
    package_dir: Path | None, *, knowledge_dir: Path | str | None = None
) -> dict[str, Any]:
    """The registry fragment: node type → a tool bound to one package dir.

    `knowledge_dir` is the explicit override (`load_workflow(knowledge_dir=)`)
    and names the directory of topic files itself; convention is the default.
    """
    return {
        KnowledgeLookupTool.node_type: KnowledgeLookupTool(
            package_dir=package_dir, knowledge_dir=knowledge_dir
        )
    }


def ambient_knowledge_tool(
    package_dir: Path | str | None, *, knowledge_dir: Path | str | None = None
) -> KnowledgeLookupTool | None:
    """The ambient-seeking rule: knowledge is a capability by configuration.

    Exactly mirroring how the memory tools auto-attach when the runtime's
    store is present: when the workflow package's ``knowledge/`` directory is
    non-empty, every agent and worker in that workflow gets the lookup tool
    — no Knowledge atom wiring required. The atom stays as the visible
    canvas declaration and the Build-second-brain button's home; wiring it
    explicitly must not double-bind (callers dedupe by tool name).

    None when there is nothing to look up — an always-failing tool would be
    worse than no tool.
    """
    if knowledge_dir is not None:
        directory = Path(knowledge_dir)
    elif package_dir is not None:
        directory = Path(package_dir) / "knowledge"
    else:
        return None
    if not any(directory.glob("*.md")):
        return None
    return KnowledgeLookupTool(package_dir=package_dir, knowledge_dir=knowledge_dir)


__all__ = [
    "KnowledgeLookupArgs",
    "KnowledgeLookupTool",
    "ambient_knowledge_tool",
    "knowledge_lookup_for",
]
