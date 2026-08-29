"""`human.approval` — the node that stops and waits for a person.

One family, one file: its one reason to change is LangGraph's `interrupt()`
contract, and nothing else in the compiler shares it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openstategraph.compile.workflow_compiler import (
    CompiledPlan,
)
from openstategraph.compile.context import (
    _text,
    rejection_feedback,
)
from openstategraph.compile.state import (
    RunState,
    _upstream_text,
    _upstream_verdict,
)

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


def _human_approval(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """Pauses the run and waits for a person, via LangGraph's own `interrupt()`.

    Same node-decides/edge-dispatches split as the router and the
    grader — this node *decides* `approved`/`rejected`, and the
    compiler's conditional edge (`workflow_compiler.py`) *dispatches* on
    whichever label it wrote to `state["decisions"]`. The difference
    from the grader is only *who* decides: a human, resumed via
    `Command(resume=...)`, instead of an LLM's own judgement.

    `interrupt()` requires the compiled graph to have a checkpointer
    (`WorkflowCompiler.build`'s `checkpointer` param) — without one,
    LangGraph raises before this ever pauses. Calling it more than once
    per node invocation is the documented anti-pattern (a resume re-runs
    the node from its own start), which is exactly why this calls it
    **exactly once**, unconditionally, rather than inside a retry loop.
    """
    # Recorded as the executor is built, so a caller one level up can ask
    # whether this document waits for anybody (`organisms-first-class` 65).
    self._holds_a_gate = True
    # The gate is the only node that can ask whether it is *below* the
    # thing it claims to authorise (`launch-readiness` 121).
    self._report_late_approval(node_id, plan)
    data = node.get("data") or {}
    message = _text(data, "message") or "Approve this result?"
    upstream = [src for src, dst in plan.edges if dst == node_id]
    # A grader reaches a gate along its `pass` branch, which is a
    # **conditional** edge and therefore absent from `plan.edges` — the
    # list above is empty for the shape this whole feature is about
    # (`workflow-gallery` 32, found by running it: the verdict was in state
    # and the lookup had nowhere to look). Static producers first, so the
    # node that actually wrote the candidate is preferred where both exist.
    producers = upstream + [
        src
        for src, branches in (plan.conditional or {}).items()
        if node_id in (branches or {}).values()
    ]

    def run(state: RunState) -> dict[str, Any]:
        from langgraph.types import interrupt

        candidate = _upstream_text(state, upstream) or state.get("answer", "")
        payload = {"message": message, "candidate": candidate}
        judgement = _upstream_verdict(state, producers)
        if judgement:
            payload.update(judgement)
        decision = interrupt(payload)

        approved = isinstance(decision, dict) and decision.get("decision") == "approve"
        feedback = ""
        if not approved:
            note = (decision or {}).get("feedback", "") if isinstance(decision, dict) else ""
            feedback = rejection_feedback(str(note))
        return {
            "decisions": {node_id: "approved" if approved else "rejected"},
            "feedback": feedback,
            "outputs": {node_id: candidate},
        }

    return run

