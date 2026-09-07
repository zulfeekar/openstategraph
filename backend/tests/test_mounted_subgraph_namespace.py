"""A mounted child's frames must stay attributable to the mount (ticket 02).

The reported bug was a highlight: during a run of `chinook-assistant` the
router kept the glow for the ~20 seconds the mounted `analyst` worked. The
resolver that was supposed to prevent that (`ActiveNodeResolver`) was correct;
what reached it was not. `NodeRuntime._subgraph` invoked the child with an
explicit config whose `configurable` had been rebuilt without the
`checkpoint*` keys — and `checkpoint_ns` is what LangGraph derives a nested
graph's stream namespace from. With a checkpointer attached (the live path,
and only the live path) the child's frames arrived with the `<mount>:<id>`
head stripped off, so nothing on the wire said `analyst` until the mount
finished.

Real LangGraph, real compiler, no model and no network — the shape under test
is structural, so it costs nothing to run on every commit. The critical detail
is `checkpointer=`: without one the old code looked fine, which is exactly how
this survived a suite full of checkpointer-free subgraph tests.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from openstategraph.api.streaming import ActiveNodeResolver
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

CHILD = {
    "version": 2,
    "name": "child",
    "nodes": [
        {"id": "cin", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "cout", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "cin", "portId": "text"},
            "target": {"nodeId": "cout", "portId": "result"},
        }
    ],
}

PARENT = {
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


def _stream_with_checkpointer() -> list[tuple[tuple[str, ...], str]]:
    """Every `updates` chunk of one parent run, as `(namespace, node name)`."""
    runtime = NodeRuntime(document_loader={"child-flow": CHILD}.__getitem__)
    graph = WorkflowCompiler().build(
        PARENT, RunState, runtime.factory(PARENT), checkpointer=InMemorySaver()
    )
    frames: list[tuple[tuple[str, ...], str]] = []
    for namespace, _mode, payload in graph.stream(
        {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
        {"configurable": {"thread_id": "t1", "workflow_slug": "parent-flow"}},
        stream_mode=["updates"],
        subgraphs=True,
    ):
        for name in payload:
            frames.append((tuple(namespace), name))
    return frames


def test_a_mounted_childs_frames_carry_the_mount_as_their_namespace_head() -> None:
    """The evidence the highlight is built from — restored, and pinned."""
    frames = _stream_with_checkpointer()

    child_frames = [(ns, name) for ns, name in frames if name in {"cin", "cout"}]
    assert child_frames, "the mounted child produced no frames at all"
    for namespace, name in child_frames:
        assert namespace, f"{name!r} arrived with no namespace — the mount is unnameable"
        assert namespace[0].split(":")[0] == safe_name("analyst"), (
            f"{name!r} arrived under {namespace!r}; the mount must be the head"
        )


def test_the_mounts_own_frame_is_still_top_level() -> None:
    """The mount reports its completion on the parent graph, namespace-free."""
    frames = _stream_with_checkpointer()
    assert ((), "analyst") in frames


def test_the_resolver_turns_those_frames_into_the_mount() -> None:
    """End to end: what the clients would actually highlight, in order."""
    known = {safe_name(n): n for n in ("in1", "analyst", "out1")}
    resolver = ActiveNodeResolver(known)

    highlighted: list[str] = []
    for namespace, name in _stream_with_checkpointer():
        active = resolver.resolve(known.get(name, name), namespace)
        if active and (not highlighted or highlighted[-1] != active):
            highlighted.append(active)

    assert highlighted == ["in1", "analyst", "out1"]


def test_the_child_still_runs_under_its_own_workflow_slug() -> None:
    """The isolation the stripped config existed for, kept by the narrow one.

    `TestScopeThreadingAcrossSubgraphs` in `test_memory.py` proves the Store
    consequence; this proves the mechanism directly, so a future edit to the
    mount config cannot pass by breaking only the subtler half.
    """
    seen: dict[str, Any] = {}

    def probe(text: str) -> str:
        from langgraph.config import get_config

        seen.update(get_config().get("configurable") or {})
        return text

    child = {
        **CHILD,
        "nodes": [
            CHILD["nodes"][0],
            {"id": "cf", "type": "function.probe", "position": {"x": 100, "y": 0}, "data": {}},
            CHILD["nodes"][1],
        ],
        "edges": [
            {
                "source": {"nodeId": "cin", "portId": "text"},
                "target": {"nodeId": "cf", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "cf", "portId": "report"},
                "target": {"nodeId": "cout", "portId": "result"},
            },
        ],
    }
    runtime = NodeRuntime(
        document_loader={"child-flow": child}.__getitem__,
        functions={"function.probe": probe},
    )
    graph = WorkflowCompiler().build(
        PARENT, RunState, runtime.factory(PARENT), checkpointer=InMemorySaver()
    )
    graph.invoke(
        {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
        {
            "configurable": {
                "thread_id": "t1",
                "workflow_slug": "parent-flow",
                "user_email": "a@x.com",
            }
        },
    )

    # The one key the mount overrides...
    assert seen.get("workflow_slug") == "child-flow"
    # ...and the ones that must cross untouched: same person, same thread.
    assert seen.get("user_email") == "a@x.com"
    assert seen.get("thread_id") == "t1"
    # The child's address, which is what makes its frames attributable.
    assert str(seen.get("checkpoint_ns", "")).startswith(f"{safe_name('analyst')}:")
