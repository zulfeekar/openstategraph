"""`memory.segment` — the node that reads and writes across threads.

One family, one reason to change: what a segment of memory is and which store
it reaches. It is the only builder that deliberately does **not** use
`self.services.memory_store`, and the docstring below says why; that exception
is this module's whole subject.

Named for the node type, not for `openstategraph.memory` — the settings module
it configures from — which is the one confusion a reader can have here.

`compile/nodes/__init__.py` carries the argument for the package and the
binding mechanism.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openstategraph.compile.workflow_compiler import CompiledPlan
from openstategraph.compile.upstream import upstream_sources
from openstategraph.compile.state import RunState, _upstream_text
from openstategraph.compile.context import _text

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


def _memory_segment(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """A tollbooth: what crosses is furnished, recorded and passed onward.

    A **real state-transforming graph node**, and the deterministic half of
    memory. The other half — a write the *model* decides to make — is
    `save_memory`, bound to every agent when a store is present, and the
    atom-forge interview's first redirect is what keeps the two apart. A
    node whose position on the canvas implies a guarantee the model was
    free to ignore is the drawn thing that lies.

    ## What makes it a node and not configuration

    It reads and appends a workflow-scoped Store namespace **at a drawn
    position**, which nothing else in the catalogue does. Everything about
    the ledger itself lives in `openstategraph.memory_segment`; this
    factory is state plumbing and nothing else.

    ## The store is fetched at run time, not held from compile time

    `get_store()` reads the store the compiled graph was built with, which
    is what makes one implementation work identically in a parent and in a
    mounted child — and a child resolves its *own* `workflow_slug`, so a
    mount's segments are the mount's, exactly as isolation implies.

    `self.services.memory_store` is deliberately not used: it is the parent's
    object, and reading it here would make a subgraph's tollbooth write to
    the wrong ledger in the one case nobody tests by hand.

    ## What it cannot reach, stated rather than implied

    An outbound Guardrail scrubs `outputs`; it does not reach the Store. A
    segment placed downstream of unredacted content records that content
    durably, and the redaction that happens later cannot retrieve it. This
    is the guardrail work's own "a node cannot act on what left before it
    ran", pointed the other way, and the card says so.
    """
    from openstategraph.memory_segment import MemorySegment, parse_retention

    data = node.get("data") or {}
    segment = MemorySegment(
        name=_text(data, "segment"),
        retention=parse_retention(data.get("retention")),
    )
    # A tollbooth placed after a grader, an approval or a guardrail is
    # reached over a *conditional* edge, which `plan.edges` does not
    # carry — the same gap `_agent`, `_output` and `_guardrail` close.
    sources = upstream_sources(plan, node_id)

    def run(state: RunState) -> dict[str, Any]:
        from langgraph.config import get_store

        from openstategraph.memory import UNSAVED_SLUG, workflow_scope_slug

        text = _upstream_text(state, sources) or state.get("question", "")
        try:
            store = get_store()
        except Exception:
            # No store configured for this run. `MemorySegment.cross`
            # owns what that means and says it in the one sentence a
            # model can act on; taking the run down instead would make a
            # missing optional backend into an outage.
            store = None
        # A ledger key, not a memory namespace, so the fallback is spelled
        # here (2026-08-16). `workflow_scope_slug()` answers None for a run
        # that does not know its workflow, and `("workflow-memory", ...)`
        # now refuses rather than bucketing such a run — but a placed
        # segment card must still record what crossed it on an unsaved
        # canvas, which is the case the editor exercises most. So this one
        # keeps the shared bucket, visibly and on purpose. It is the last
        # place a nameless run shares a key.
        slug = workflow_scope_slug() or UNSAVED_SLUG
        crossing = segment.cross(store, slug, text=text, node=node_id)
        # `outputs` only. The node introduces no state key, so there is no
        # multi-writer question to answer and no reducer to name — the
        # cheapest way to satisfy that rule is not to need it.
        return {"outputs": {node_id: crossing.text}}

    return run
