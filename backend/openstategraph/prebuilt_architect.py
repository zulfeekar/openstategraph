"""The Workflow Architect's instruments — ticket 69.

Dynamic workflows rest on one fact this platform arranged deliberately: a
workflow is *data*, and the compiler validates data without running anything.
``validate_workflow`` exposes exactly that as a tool — the Architect composes
a document, this tool compile-checks it, and the verdict (entry points,
routes, bindings, warnings, unknown types) is the **evidence** its revise
loop feeds on. Loop on evidence, never on the model's confidence — the
platform's own adopted rule, applied to workflow creation itself.

Read-only like everything the concierge reaches: validation plans a graph in
memory and throws it away. Nothing here can save, run, or mutate.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, ToolResult

#: Node types the runtime genuinely implements. Kept as data so the check
#: below cannot drift from `NodeRuntime._builders` silently — the test pins
#: them against each other.
KNOWN_NODE_TYPES = frozenset({
    "input.text", "input.markdown", "input.skill", "agent.llm", "route.classifier",
    "route.grader", "human.approval", "orchestrate.supervisor",
    "orchestrate.worker", "function.format_report", "output.formatted",
    "workflow.subgraph", "team.workflow",
})

KNOWN_PREFIXES = ("tool.", "function.")


class ValidateArgs(BaseModel):
    model_config = {"extra": "forbid"}
    document: str = Field(
        description="The complete workflow document as a JSON string: "
        '{"version": 2, "name": ..., "nodes": [...], "edges": [...]}.'
    )


class ValidateWorkflowTool(BaseTool):
    """Compile-checks a composed document; the verdict is revise evidence."""

    name = "validate_workflow"
    node_type = "tool.validate-workflow"
    description = (
        "Compile-check a workflow document you have composed. Returns the "
        "planned topology (entries, exits, routes, tool bindings) plus every "
        "warning and unknown node type. ALWAYS call this before presenting a "
        "workflow — a document you have not validated is a guess."
    )
    Args = ValidateArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, ValidateArgs)
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        try:
            document = json.loads(args.document)
        except json.JSONDecodeError as exc:
            return ToolResult.failure(f"Not valid JSON: {exc}")
        if not isinstance(document, dict):
            return ToolResult.failure("The document must be a JSON object.")
        document = document.get("document", document)

        problems: list[str] = []
        nodes = document.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            return ToolResult.failure("The document needs a non-empty 'nodes' list.")
        for node in nodes:
            node_type = str(node.get("type", ""))
            if node_type not in KNOWN_NODE_TYPES and not node_type.startswith(KNOWN_PREFIXES):
                problems.append(f"unknown node type '{node_type}' on '{node.get('id')}'")

        try:
            plan = WorkflowCompiler().plan(document)
        except Exception as exc:
            return ToolResult.failure(f"Compile failed: {type(exc).__name__}: {exc}")

        problems.extend(plan.warnings)
        if not plan.entry:
            problems.append("no entry point — some node must have no incoming control edge")
        if not plan.exits:
            problems.append("no exit — some node must flow toward the end")

        report = [
            "VALID" if not problems else "PROBLEMS FOUND:",
            *(f"- {p}" for p in problems),
            "",
            f"Topology: {len(plan.nodes)} graph nodes · entry {plan.entry} · exits {plan.exits}",
            f"Routes: { {k: list(v) for k, v in plan.conditional.items()} or 'none'}",
            f"Tool bindings: {plan.tool_bindings or 'none'}",
            f"Fan-out: {plan.fan_out or 'none'}",
        ]
        content = "\n".join(report)
        return ToolResult(content=content) if not problems else ToolResult.failure(content)


ARCHITECT_TOOLS: list[Any] = [ValidateWorkflowTool()]
