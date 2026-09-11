"""The card that offers a timeout is the card whose body can honour one.

**Two halves of one fact, in two languages, and nothing held them together.**
The editor decides which cards show `Timeout, seconds`; the compiler decides
whether a timeout survives to `add_node`. Before `langchain-drift-watch` 01 and
02 the two disagreed completely — the editor offered it everywhere, the library
refuses it for a synchronous body, and the refusal is at *compile* time, so a
document that took the offer could not be loaded at all.

Fixing each half separately leaves the same defect one migration away. The day
a seventh family gains an `async def` body, or a sixth loses one, the flag in
`NodeSpec` and the behaviour of `is_interruptible` part company again and every
test on both sides stays green.

So this asks the two questions of the same node and compares:

- what the **editor** offers, read from the generated `port_specs.json` — the
  artifact CI already gates against the TypeScript it came from, so reading it
  here is reading the editor's answer rather than a copy of it;
- what the **compiler** would keep, by building that node type's body and
  asking `is_interruptible`, which is the predicate the fix actually calls.

Neither side is restated. A type list written into this file would be the third
description of something two already disagree about.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from openstategraph.compile.node_doors import is_interruptible, with_both_doors
from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import CompiledPlan

ARTIFACT = (
    pathlib.Path(__import__("openstategraph").__file__).parent
    / "compile"
    / "port_specs.json"
)

#: Types whose body cannot be built without something this test has no business
#: constructing, with the reason. Recorded rather than skipped silently, in the
#: style of the ceiling tables: a silent skip is how a census stops covering the
#: thing it was written for.
#:
#: A mount is the only one. Building it compiles a *child package*, which needs
#: a workflow library on disk and would make this a test of package loading.
#: `test_mount_composition_preview.py` owns that, and the mount's body is
#: `async def` in `compile/nodes/mount.py` where anyone can read it.
CANNOT_BUILD_IN_ISOLATION: dict[str, str] = {
    "workflow.subgraph": "building it compiles a child package from disk",
}


def _editor_offers_timeout() -> dict[str, bool]:
    """Per node type, whether the editor shows the timeout field."""
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    return {
        entry["type"]: "timeoutSeconds" in (entry.get("field_keys") or [])
        for entry in artifact["node_types"]
        if entry.get("kind") == "standard" and not entry.get("editor_only")
    }


def _compiler_would_keep_timeout(node_type: str) -> bool | None:
    """Whether a body of this type can carry a timeout, or `None` if unbuildable."""
    runtime = NodeRuntime(model=None, tools={})
    node: dict[str, Any] = {"id": "n1", "type": node_type, "data": {}}
    try:
        body = runtime.builder_for(node_type)("n1", node, CompiledPlan())
    except Exception:
        return None
    return is_interruptible(with_both_doors(body))


def test_the_two_halves_agree_on_every_type_that_can_be_built() -> None:
    disagreements: list[str] = []
    unbuildable: list[str] = []

    for node_type, offered in sorted(_editor_offers_timeout().items()):
        if node_type in CANNOT_BUILD_IN_ISOLATION:
            continue
        kept = _compiler_would_keep_timeout(node_type)
        if kept is None:
            unbuildable.append(node_type)
            continue
        if kept != offered:
            disagreements.append(
                f"{node_type}: editor offers={offered}, compiler keeps={kept}"
            )

    assert disagreements == [], (
        "the editor and the compiler disagree about which nodes can honour a "
        f"timeout: {disagreements}. Set or clear `interruptible` on the spec in "
        "`src/nodes/`, regenerate `port_specs.json`, and do not add a list here."
    )

    assert unbuildable == [], (
        "these types could not be built in isolation and are not recorded as "
        f"exceptions: {unbuildable}. Add each to CANNOT_BUILD_IN_ISOLATION with "
        "the reason, rather than letting the census quietly stop covering them."
    )


def test_something_is_offered_a_timeout() -> None:
    """The agreement above is also satisfiable by offering it to nobody."""
    offered = [t for t, yes in _editor_offers_timeout().items() if yes]

    assert offered, "no node type offers a timeout — the feature is gone, not gated"
    assert "agent.llm" in offered, "an agent is the node a timeout is most for"


@pytest.mark.library_contract
def test_the_types_the_editor_offers_are_ones_langgraph_accepts() -> None:
    """End of the chain: the library takes a timeout on those bodies.

    The two tests above agree with each other and could both be wrong together
    if `is_interruptible` stopped meaning what LangGraph checks. This asks
    LangGraph.
    """
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import TimeoutPolicy

    from openstategraph.compile.node_runtime import RunState

    offered = [
        node_type
        for node_type, yes in _editor_offers_timeout().items()
        if yes and node_type not in CANNOT_BUILD_IN_ISOLATION
    ]
    assert offered, "nothing to check"

    for node_type in offered:
        runtime = NodeRuntime(model=None, tools={})
        body = with_both_doors(
            runtime.builder_for(node_type)(
                "n1", {"id": "n1", "type": node_type, "data": {}}, CompiledPlan()
            )
        )
        builder = StateGraph(RunState)
        builder.add_node("n", body, timeout=TimeoutPolicy(run_timeout=1))
        builder.add_edge(START, "n")
        builder.add_edge("n", END)
        builder.compile()  # raises if the library disagrees


def test_a_document_written_before_the_field_was_withdrawn_still_validates() -> None:
    """The backward-compatibility promise, asserted rather than intended.

    Every document saved before `langchain-drift-watch` 02 carries
    `"timeoutSeconds": ""` on **every** node, because the field was injected
    onto every executable type and saved blank. Withdrawing the field from most
    types therefore turned a key that was ours into a key nothing declares —
    and `unknown_fields` is a *finding*, not an advisory, so every shipped
    package and every user document began failing `validate` with exit 1.

    That is a far worse break than the defect being fixed: the defect stopped a
    document compiling only if somebody had typed a number, while this would
    have failed every document ever saved.

    The execution overrides are graph-assembly keys the compiler owns, not
    fields of a node type, so they are legitimate in any node's `data`
    regardless of which cards offer them. The catalogue says so, generated from
    the editor's own list rather than hand-kept on this side — the same
    argument `legacy_data_keys` records.
    """
    from openstategraph.compile.node_catalogue import CATALOGUE

    assert "timeoutSeconds" in CATALOGUE.execution_override_keys, (
        "the catalogue does not carry the compiler-owned override keys, so a "
        "document that predates the field's withdrawal is invalid"
    )
