"""The ladders a third party subclasses. **Tier 1 — semver-public.**

CLAUDE.md's non-negotiable is `I*` → `Abstract*` → `Base*` → concrete, and
every workflow package's `tools/*.py` already sits at the bottom of the tool
ladder. That made this the *most* public thing the framework ships — and it was
reachable only through deep module paths like `openstategraph.abc.tool`, from
an `__init__.py` that was empty. Adopters would have pinned those paths, and
then no file here could ever move.

So this is the blessed seam:

    from openstategraph.abc import BaseTool, NoArgs, ToolResult

    class ListTables(BaseTool):
        name = "list_tables"
        description = "Every table in the database."
        node_type = "tool.list-tables"
        Args = NoArgs

        def _execute(self, args) -> ToolResult:
            return ToolResult(content="…")

The deep paths keep working — this module re-exports rather than relocates, so
nothing that imports `openstategraph.abc.tool` breaks. New code should import
from here, because *this* name is the one covered by the stability contract in
`docs/stability.md`.

**What is here and what is not.** Every name below is a ladder an adopter
legitimately subclasses or constructs — a tool, a router, a grader, a
guardrail, an agent node, an orchestrator, a **node family** — plus the
collaborators those ladders compose
(`SystemPrompt`, `MiddlewareSlotTable`, `NodeBuildContext`). The registries
are **not** here and
are not public: entry points are the supported extension seam precisely so the
registry objects stay free to change shape.

`Field` is re-exported because a tool's `Args` model needs it and it would be
perverse to make an adopter import pydantic to write two lines against our
ladder. It is pydantic's own `Field`, unmodified.
"""

from __future__ import annotations

from openstategraph.abc.agent import (
    AbstractAgentNode,
    BaseAgentNode,
    CustomGraphNode,
    DeepAgentNode,
    IAgent,
    ReactAgentNode,
    agent_node_for_tier,
)
from openstategraph.abc.grader import BaseGrader, Grader, IGrader, Verdict
from openstategraph.abc.guardrail import (
    BaseGuardrail,
    Guardrail,
    GuardrailRule,
    IGuardrail,
    Redaction,
    Screening,
)
from openstategraph.abc.middleware import MiddlewareSlotTable
from openstategraph.abc.node_family import BaseNodeFamily, INodeFamily, NodeBuildContext
from openstategraph.abc.orchestrator import (
    Archetype,
    BaseOrchestrator,
    IOrchestrator,
    Orchestrator,
    Subtask,
)
from openstategraph.abc.prompt import SystemPrompt
from openstategraph.abc.router import BaseRouter, Classification, IRouter, Router
from openstategraph.abc.tool import BaseTool, Field, ITool, NoArgs, ToolField, ToolResult
# Not a ladder — the one thing a tool does *while* it runs. It lives here
# because this is the import line a tool author is given, and a second
# path for it would be a surface nobody finds.
from openstategraph.progress import Progress, report_progress

__all__ = [
    "AbstractAgentNode",
    "Archetype",
    "BaseAgentNode",
    "BaseGrader",
    "BaseGuardrail",
    "BaseNodeFamily",
    "BaseOrchestrator",
    "BaseRouter",
    "BaseTool",
    "Classification",
    "CustomGraphNode",
    "DeepAgentNode",
    "Field",
    "Grader",
    "Guardrail",
    "GuardrailRule",
    "IAgent",
    "IGrader",
    "IGuardrail",
    "INodeFamily",
    "IOrchestrator",
    "IRouter",
    "ITool",
    "MiddlewareSlotTable",
    "NoArgs",
    "NodeBuildContext",
    "Orchestrator",
    "Progress",
    "ReactAgentNode",
    "Redaction",
    "Router",
    "Screening",
    "Subtask",
    "SystemPrompt",
    "ToolField",
    "ToolResult",
    "Verdict",
    "agent_node_for_tier",
    "report_progress",
]
