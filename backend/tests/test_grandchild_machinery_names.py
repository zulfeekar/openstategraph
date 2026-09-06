"""A grandchild's machinery must be withholdable too.

Ticket 25 closed a real leak: a customer read the raw branch name
`data_query` in their answer, because a *mounted* child's router streamed
through the parent's one SSE stream and the fold had no way to know that frame
was machinery rather than the reply. The fix was to merge the child's
`machinery_nodes` up into the parent, since the parent's fold is the only
place that can withhold them.

It was merged one line too early. `_subgraph` did::

    child_factory = child_runtime.factory(child_document)
    self.machinery_nodes |= child_runtime.machinery_nodes      # <- here
    child_graph = WorkflowCompiler().build(child_document, ...)

`factory()` populates the set for the child's **own** document. A mount
*inside* the child is resolved during `build()`, so a grandchild's names land
on `child_runtime` only after that call — after this union had already read
it. For A mounts B mounts C, C's router and grader names never reached the
top-level fold, and the ticket-25 leak stayed open exactly one level deeper.

The sibling map `node_ids_by_name` was moved after `build()` for precisely
this reason, and its comment says so; this line kept a comment claiming
`factory()` was what populated the set, which is true only for the first
level. That comment was the bug's best disguise.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

#: The innermost document. Its router is the node whose *name* must be
#: withholdable from a customer reading the outermost stream.
GRANDCHILD: dict[str, Any] = {
    "version": 2,
    "name": "grandchild",
    "nodes": [
        {"id": "gin", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "g-router",
            "type": "route.classifier",
            "position": {"x": 200, "y": 0},
            "data": {"branches": [{"id": "b-one", "name": "one"}], "fallback": "one"},
        },
        {"id": "gout", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "gin", "portId": "text"},
            "target": {"nodeId": "g-router", "portId": "question"},
        },
        {
            "source": {"nodeId": "g-router", "portId": "branch:b-one"},
            "target": {"nodeId": "gout", "portId": "result"},
        },
    ],
}

CHILD: dict[str, Any] = {
    "version": 2,
    "name": "child",
    "nodes": [
        {"id": "cin", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "c-mount",
            "type": "workflow.subgraph",
            "position": {"x": 200, "y": 0},
            "data": {"workflow": "grandchild-flow"},
        },
        {"id": "cout", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "cin", "portId": "text"},
            "target": {"nodeId": "c-mount", "portId": "candidate"},
        },
        {
            "source": {"nodeId": "c-mount", "portId": "report"},
            "target": {"nodeId": "cout", "portId": "result"},
        },
    ],
}

PARENT: dict[str, Any] = {
    "version": 2,
    "name": "parent",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "analyst",
            "type": "workflow.subgraph",
            "position": {"x": 200, "y": 0},
            "data": {"workflow": "child-flow"},
        },
        {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "analyst", "portId": "candidate"},
        },
        {
            "source": {"nodeId": "analyst", "portId": "report"},
            "target": {"nodeId": "out1", "portId": "result"},
        },
    ],
}

DOCUMENTS = {"child-flow": CHILD, "grandchild-flow": GRANDCHILD}


def _compiled_top_level() -> NodeRuntime:
    """Compile the whole three-level chain and hand back the outer runtime."""
    runtime = NodeRuntime(document_loader=DOCUMENTS.__getitem__)
    WorkflowCompiler().build(PARENT, RunState, runtime.factory(PARENT))
    return runtime


class TestMachineryNamesReachTheOutermostFold:
    def test_the_childs_machinery_is_known_to_the_parent(self) -> None:
        """One level down — what ticket 25 fixed. Kept as the control, so a
        regression here cannot be mistaken for the grandchild case."""
        runtime = _compiled_top_level()
        # The child has no router; its mount is the machinery-bearing node one
        # level further in, so this asserts the chain is wired at all.
        assert runtime.machinery_nodes, "no machinery names were merged upward at all"

    def test_the_grandchilds_router_is_known_to_the_parent(self) -> None:
        """The defect. A router two mounts deep streams through this same
        fold, so the fold must be able to name it."""
        runtime = _compiled_top_level()
        assert "g-router" in runtime.machinery_nodes

    def test_the_runtimes_own_spelling_is_known_too(self) -> None:
        """Both spellings, because the wire carries the compiler's.

        A frame names the step as LangGraph called it — `safe_name`, so
        `g-router` arrives as `g_router`. Withholding on the canvas id alone
        would match nothing that actually streams.
        """
        runtime = _compiled_top_level()
        assert safe_name("g-router") in runtime.machinery_nodes

    def test_the_grandchilds_output_is_not_machinery(self) -> None:
        """The set must stay a claim about *machinery*, not a list of every
        node the chain can reach. An output node carries the reply itself, so
        withholding it would empty the answer.

        `gin` is deliberately *not* asserted absent: `input.text` **is** in
        `MACHINERY_NODE_TYPES`, because an entry node re-emits the question and
        QA read exactly that — the echo of their own message — in a customer's
        answer. This assertion was written the other way round first, and the
        pre-fix failure output (`machinery_nodes == {'cin', 'in1'}`) is what
        corrected it: both of those are entry nodes, already withheld one level
        up.
        """
        runtime = _compiled_top_level()
        assert "gout" not in runtime.machinery_nodes
        assert safe_name("gout") not in runtime.machinery_nodes
