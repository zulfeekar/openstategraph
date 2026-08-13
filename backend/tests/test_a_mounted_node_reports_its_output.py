"""A frame from inside a mount carries that node's output, not `null`.

Ticket 34 gave a mounted child's frames a `path`, so the child's canvas could
finally tell *which* card a frame was about. It stopped one step short: the
frame's `output` — the value the card renders — was still looked up under the
wrong key, so every node inside a mount glowed and then showed nothing.

The lookup used `node_id`, which is deliberately resolved through the
**narrow** map (`{safe_name(id): id}` for the document the run was launched
against). That narrowness is correct for `node`: widening it would make the
parent's canvas glow on a card it does not contain, which is what ticket 01
fixed. But the *update dict* being read belongs to whichever document produced
the frame, and its keys are that document's canvas ids. So for a child node:

    raw_name             = "agent_sql"      (safe_name mangles the hyphen)
    node_id              = "agent_sql"      (narrow map has no such key)
    update["outputs"]    = {"agent-sql": …} (the child's own canvas id)
    → .get("agent_sql")  = None

Captured off the wire on a real `?w=concierge` run (2026-08-13): every frame
from inside the mount — `agent_sql`, `grader_sql` — carried `"output": null`,
while `in1` and `out1` carried theirs. Those two only worked because the
parent and child *share* those ids, so the narrow map happened to answer. A
bug hidden by a name collision is still a bug, and renaming one node in either
document would have exposed it.

`path` already answers this question correctly for every level, and its last
entry is this frame's own card in its own document. That is the key to read.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from openstategraph.api.audience import Audience
from openstategraph.api.streaming import _run_frames
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

#: Hyphenated on purpose — `safe_name` rewrites the hyphen, and an id that
#: survived it unchanged would hide the defect. Deliberately does NOT share
#: `out1` with the parent, so no collision can answer the lookup by accident.
CHILD: dict[str, Any] = {
    "version": 2,
    "name": "child",
    "nodes": [
        {"id": "c-in", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "agent-sql",
            "type": "output.formatted",
            "position": {"x": 200, "y": 0},
            "data": {},
        },
    ],
    "edges": [
        {
            "source": {"nodeId": "c-in", "portId": "text"},
            "target": {"nodeId": "agent-sql", "portId": "result"},
        }
    ],
}

PARENT: dict[str, Any] = {
    "version": 2,
    "name": "parent",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "wf-music",
            "type": "workflow.subgraph",
            "position": {"x": 200, "y": 0},
            "data": {"workflow": "child-flow"},
        },
        {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "wf-music", "portId": "candidate"},
        },
        {
            "source": {"nodeId": "wf-music", "portId": "report"},
            "target": {"nodeId": "out1", "portId": "result"},
        },
    ],
}

QUESTION = "Which five artists have the highest total invoice revenue?"


def _update_frames() -> list[dict[str, Any]]:
    runtime = NodeRuntime(document_loader={"child-flow": CHILD}.__getitem__)
    compiler = WorkflowCompiler()
    plan = compiler.plan(PARENT)
    graph = compiler.build(
        PARENT, RunState, runtime.factory(PARENT), checkpointer=InMemorySaver()
    )
    frames: list[dict[str, Any]] = []
    for raw in _run_frames(
        graph,
        {"question": QUESTION, "attempts": 0, "decisions": {}, "outputs": {}},
        {"configurable": {"thread_id": "t1", "workflow_slug": "parent-flow"}},
        plan,
        {safe_name(n): n for n in plan.nodes},
        runtime,
        "t1",
        Audience.DEVELOPER,
    ):
        head, _, body = raw.partition("\n")
        if head == "event: update":
            frames.append(json.loads(body.partition("data: ")[2]))
    return frames


def _for(frames: list[dict[str, Any]], canvas_id: str) -> dict[str, Any]:
    """The frame whose own card — the deepest entry of its path — is this id."""
    matches = [f for f in frames if (f.get("path") or [None])[-1] == canvas_id]
    assert matches, f"no frame arrived for {canvas_id!r}"
    return matches[-1]


class TestAMountedNodeReportsItsOutput:
    def test_a_child_node_carries_its_own_output(self) -> None:
        """The defect itself: this frame used to be `"output": null`."""
        frame = _for(_update_frames(), "agent-sql")
        assert frame["output"], "a node inside a mount reported no output at all"
        assert QUESTION in frame["output"]

    def test_the_frame_still_names_the_step_the_runtime_named(self) -> None:
        """The fix must not widen `node`: a parent canvas keyed off it would
        start glowing on cards it does not contain (ticket 01)."""
        frame = _for(_update_frames(), "agent-sql")
        assert frame["node"] == safe_name("agent-sql")
        assert frame["activeNode"] == "wf-music"
        assert frame["internal"] is True

    def test_a_top_level_node_is_unaffected(self) -> None:
        frames = _update_frames()
        assert QUESTION in _for(frames, "in1")["output"]
        assert _for(frames, "out1")["output"]
