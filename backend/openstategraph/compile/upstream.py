"""Which nodes are wired into a node — over *either* edge table.

A plan carries two: `plan.edges` for the static ones, and `plan.conditional`
for the ones a branch decides at runtime (a grader's `pass`, a guard's `pass`,
an approval's `approved`, a classifier's branch). A builder that reads only
the first sees a node fed by a routed edge as a node fed by nothing.

That has now been the same defect three times — `launch-readiness/66` in
`_agent`, `_output`, `_guardrail` and `_subgraph`; then `_discovered_function`;
then `osg-agent-experience/51`, where the report join's fallback fell through
to *"nothing was dispatched to this join"* on a wired, drawn, validated graph.
Each was fixed by writing the same two comprehensions out again beside the
next builder, which is why the fourth arrived. This is the one reader, so the
next builder inherits the answer instead of re-deriving half of it.

Order is static-then-conditional and is deliberate: `_upstream_text` joins the
texts in the order it is handed, so this preserves byte-for-byte what every
already-correct builder produced when it wrote the pair by hand.
"""

from __future__ import annotations

from openstategraph.compile.workflow_compiler import CompiledPlan


def upstream_sources(plan: CompiledPlan, node_id: str) -> list[str]:
    """Every node that feeds `node_id`, static edges first, then conditional.

    A conditional source counts only for the branch that actually lands here:
    a guard whose `pass` goes elsewhere and whose `revise` comes back is not
    an upstream of this node. Tolerant in reading both tables, strict about
    which branch is a source.
    """
    static = [src for src, dst in plan.edges if dst == node_id]
    conditional = [
        src for src, dests in plan.conditional.items() if node_id in dests.values()
    ]
    return static + conditional
