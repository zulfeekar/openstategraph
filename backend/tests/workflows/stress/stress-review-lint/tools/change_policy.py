"""The written change policy, as clauses with ids, so a citation can be checked."""

from __future__ import annotations

from pydantic import BaseModel, Field

from openstategraph.abc import BaseTool, ToolResult

CLAUSES: dict[str, str] = {
    "CP-1": "Any change touching a service classified as PCI cardholder data requires a named second reviewer from outside the owning team.",
    "CP-2": "A service with a 99.99% availability SLO may not be deployed outside the change-advisory-board window.",
    "CP-3": "A schema migration and an application release must be separate changes, deployed at least one release apart.",
    "CP-4": "A canary deployment must define an automatic abort threshold before it starts.",
    "CP-5": "A change that removes a dependency must name every service listed as depending on the changed service.",
}


class PolicyArgs(BaseModel):
    clause: str = Field(description="A clause id such as CP-1, or the word 'all'.")


class ChangePolicyTool(BaseTool):
    """Returns the text of one change-policy clause, or all of them."""

    name = "change_policy"
    side_effecting = False
    node_type = "tool.change-policy"
    description = (
        "Read the change policy. Give a clause id (CP-1 .. CP-5) for one clause, "
        "or 'all' for every clause. There are exactly five clauses and no others."
    )
    Args = PolicyArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        key = str(getattr(args, "clause", "")).strip().upper()
        if key in ("ALL", ""):
            return ToolResult(
                content="\n".join(f"{cid}: {text}" for cid, text in CLAUSES.items())
            )
        text = CLAUSES.get(key)
        if text is None:
            return ToolResult(
                content=(
                    f"There is no clause {key}. The policy has exactly five "
                    "clauses: CP-1, CP-2, CP-3, CP-4, CP-5."
                )
            )
        return ToolResult(content=f"{key}: {text}")
