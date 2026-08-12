"""A run frame must name every canvas it is happening on, not only the top one.

Tickets 33/34, and the same defect both wear: **the editor renders what was
saved, not what is happening.** Opening a mounted workflow while it works
showed a static diagram, and this file pins the reason on the wire rather than
in the browser.

A frame from inside a mount used to answer "where is the run" twice, and
neither answer was usable by the child's own canvas:

- `node` is whatever LangGraph called the step. Inside an agent's compiled loop
  that is literally `model` or `tools`; inside a mounted document it is
  `safe_name(id)`, so the child's `agent-sql` arrives as `agent_sql` — a string
  the child document does not contain, because canvas ids keep their hyphens.
- `activeNode` is the *top-level* owner, so it is the mount's card, which the
  child document does not contain either.

The information was never missing — it was in the **namespace**, which reads
`wf_music:<checkpoint> / agent_sql:<checkpoint>` — but nothing resolved it, and
nothing could, because the only name→id map the stream held was the parent's.

So `path` is added: the chain of canvas node ids from the outermost document
inward, resolved against every document in the run rather than only the one
that started it. A client walks it outermost-first and stops at the first id
the document *it* has open contains. The parent finds the mount, the child
finds the step inside it, and neither needs to know the other exists.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from openstategraph.api.audience import Audience
from openstategraph.api.streaming import _run_frames
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

#: Hyphenated ids on purpose. `safe_name` rewrites every non-alphanumeric
#: character to `_`, so `agent-sql` compiles to the graph node `agent_sql` —
#: and an id that survived the mangling unchanged (`in1`) would have hidden
#: the whole bug, which is how it reached a browser.
CHILD: dict[str, Any] = {
    "version": 2,
    "name": "child",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "agent-sql",
            "type": "output.formatted",
            "position": {"x": 200, "y": 0},
            "data": {},
        },
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "agent-sql", "portId": "result"},
        }
    ],
}

#: Shares `in1` and `out1` with the child, which is not incidental: the shipped
#: `concierge` and `chinook-assistant` do exactly this, and it is why "does the
#: open document contain this id" cannot be the whole rule on its own.
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
        {
            "id": "out1",
            "type": "output.formatted",
            "position": {"x": 400, "y": 0},
            "data": {},
        },
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


def _update_frames() -> list[dict[str, Any]]:
    """Every `update` frame of one real parent run, decoded."""
    runtime = NodeRuntime(document_loader={"child-flow": CHILD}.__getitem__)
    compiler = WorkflowCompiler()
    plan = compiler.plan(PARENT)
    graph = compiler.build(
        PARENT, RunState, runtime.factory(PARENT), checkpointer=InMemorySaver()
    )
    node_ids_by_name = {safe_name(n): n for n in plan.nodes}
    frames: list[dict[str, Any]] = []
    for raw in _run_frames(
        graph,
        {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
        # `workflow_slug` is what names level 0 of every path — the document
        # the run was launched against.
        {"configurable": {"thread_id": "t1", "workflow_slug": "parent-flow"}},
        plan,
        node_ids_by_name,
        runtime,
        "t1",
        Audience.DEVELOPER,
    ):
        head, _, body = raw.partition("\n")
        if head != "event: update":
            continue
        frames.append(json.loads(body.partition("data: ")[2]))
    return frames


def _project(
    frame: dict[str, Any], document: dict[str, Any], slug: str = ""
) -> str | None:
    """The client's rule, in Python: the level whose document this one is.

    Mirrors `src/core/runtime/frameTarget.ts` so the two halves of one
    behaviour are pinned on both sides of the wire rather than only on the
    side that is easy to test. The slug match is exact; the id walk is the
    fallback for a client that cannot name the document it is showing.
    """
    path = list(frame.get("path") or ())
    slugs = list(frame.get("pathSlugs") or ())
    if slug and slugs:
        for index, owner in enumerate(slugs):
            if owner == slug and index < len(path):
                return path[index]
        # No level is this document. That is an *answer*, not a gap — but only
        # while every level could actually be named; an unknown slug ("")
        # leaves the frame unjudged and the id walk decides instead.
        if all(slugs):
            return None
    ids = {n["id"] for n in document["nodes"]}
    for node_id in path:
        if node_id in ids:
            return node_id
    return None


def test_the_child_of_a_mount_names_itself_on_the_wire() -> None:
    """`agent-sql` must reach the stream as the id the child canvas uses."""
    inside = [f for f in _update_frames() if f["namespace"]]
    assert inside, "the mounted child produced no frames at all"

    paths = [f["path"] for f in inside]
    assert ["wf-music", "agent-sql"] in paths, (
        "no frame named the child's own hyphenated node id; "
        f"paths were {paths}"
    )


def test_a_mounted_frame_lights_the_mount_on_the_parent_canvas() -> None:
    """The behaviour that already worked must keep working, unchanged."""
    inside = [f for f in _update_frames() if f["namespace"]]
    assert {_project(f, PARENT) for f in inside} == {"wf-music"}


def test_the_same_frame_lights_the_real_step_on_the_child_canvas() -> None:
    """The whole ticket: one frame, two documents, two honest answers."""
    inside = [f for f in _update_frames() if f["namespace"]]
    lit = {_project(f, CHILD) for f in inside}
    assert lit == {"in1", "agent-sql"}, lit


def test_a_top_level_frame_is_its_own_path() -> None:
    """No mount, no nesting: the path is the one node that ran."""
    top = [f for f in _update_frames() if not f["namespace"]]
    assert [f["path"] for f in top] == [["in1"], ["wf-music"], ["out1"]]


def test_every_level_names_the_document_it_happened_in() -> None:
    """`path` says which card; `pathSlugs` says whose card it is."""
    inside = [f for f in _update_frames() if f["namespace"]]
    deepest = [f for f in inside if f["path"] == ["wf-music", "agent-sql"]]
    assert deepest, "the child's own step never reported"
    # Level 0 is the document that was run; level 1 is what the mount above
    # it descends into. Same length as `path`, always.
    assert deepest[0]["pathSlugs"] == ["parent-flow", "child-flow"]


def test_a_shared_id_is_disambiguated_by_the_document_it_belongs_to() -> None:
    """The id walk cannot separate two `in1`s; the slug can.

    Both documents have `in1`, so a client showing the CHILD and matching on
    ids alone would light its input node for the PARENT's input step — the
    same class of lie as the one this ticket started from, just quieter.
    """
    top_input = [
        f for f in _update_frames() if not f["namespace"] and f["path"] == ["in1"]
    ]
    assert top_input, "the parent's input step never reported"
    frame = top_input[0]
    assert frame["pathSlugs"] == ["parent-flow"]
    # Told which document it is showing, the child correctly claims nothing.
    assert _project(frame, CHILD, slug="child-flow") is None
    assert _project(frame, PARENT, slug="parent-flow") == "in1"


def test_shared_ids_do_not_make_the_parent_follow_the_child() -> None:
    """`in1` exists in both documents, and outermost-first is why that is safe.

    The child's own input step reports as `in1`, which the parent contains
    too. Walking the path from the *innermost* end would light the parent's
    input node halfway through a mounted run — the exact class of lie this
    ticket is about, introduced by the fix for it.
    """
    child_input = [
        f for f in _update_frames() if f["namespace"] and f["path"][-1] == "in1"
    ]
    assert child_input, "the child's input step never reported"
    for frame in child_input:
        assert _project(frame, PARENT) == "wf-music"
        assert _project(frame, CHILD) == "in1"
