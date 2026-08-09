"""`activeNode`: the honest answer to "what is running right now".

Synthetic frames only. The bug this pins (ticket 01): while a mounted
team/subgraph or a long agent step is working, both clients guessed the
active node from the frames they could see and kept the highlight on the
*previous* top-level node — usually the router. The stream now resolves it
once, server-side, and both surfaces read the field.
"""

from __future__ import annotations

from types import SimpleNamespace

from openstategraph.api.streaming import ActiveNodeResolver

KNOWN = {
    "node_router_1": "node:router.1",
    "node_agent_llm_1": "node:agent.llm-1",
    "wf_music": "node:mount.music",
}


def test_a_top_level_canvas_frame_is_itself_active() -> None:
    resolver = ActiveNodeResolver(KNOWN)
    assert resolver.resolve("node:router.1", ()) == "node:router.1"


def test_a_mounted_subgraphs_frames_make_the_mount_active_not_the_router() -> None:
    """The reported bug, in one test."""
    resolver = ActiveNodeResolver(KNOWN)
    resolver.resolve("node:router.1", ())

    # An inner node of the mounted workflow: not a canvas node of this graph.
    assert resolver.resolve("inner_answer", ("wf_music:ckpt-1",)) == "node:mount.music"


def test_an_agents_own_loop_keeps_that_agent_active() -> None:
    """`model`/`tools` frames inside `node_agent_llm_1`'s compiled loop."""
    resolver = ActiveNodeResolver(KNOWN)
    resolver.resolve("node:router.1", ())

    assert resolver.resolve("model", ("node_agent_llm_1:aaa",)) == "node:agent.llm-1"
    assert resolver.resolve("tools", ("node_agent_llm_1:aaa",)) == "node:agent.llm-1"


def test_the_innermost_namespace_segment_that_maps_wins() -> None:
    """A mount nested inside a mount: the deepest known owner is what runs."""
    resolver = ActiveNodeResolver(KNOWN)
    active = resolver.resolve("model", ("wf_music:aaa", "node_agent_llm_1:bbb"))
    assert active == "node:agent.llm-1"


def test_an_unmappable_frame_keeps_the_last_resolved_owner() -> None:
    """Sticky, never a downgrade to a stale sibling."""
    resolver = ActiveNodeResolver(KNOWN)
    resolver.resolve("node:agent.llm-1", ())
    assert resolver.resolve("some_middleware_step", ()) == "node:agent.llm-1"


def test_before_anything_resolves_the_active_node_is_empty() -> None:
    resolver = ActiveNodeResolver(KNOWN)
    assert resolver.resolve("mystery", ()) == ""


def test_without_a_mapping_every_frame_is_taken_at_face_value() -> None:
    """No canvas context (unit tests, ad-hoc callers): degrade gracefully."""
    resolver = ActiveNodeResolver({})
    assert resolver.resolve("node:a", ()) == "node:a"
    assert resolver.resolve("model", ("node_b:x",)) == "node_b"


# --- the field on the wire -------------------------------------------------


def _frames(chunks: list[tuple[tuple[str, ...], str, dict]], known: dict[str, str]):
    """Runs `_stream_run` over a scripted stream and returns parsed SSE events."""
    import json

    from openstategraph.api.streaming import _stream_run

    class _Graph:
        def stream(self, *_args, **_kwargs):
            return iter(chunks)

        def get_state(self, _config):
            return SimpleNamespace(next=(), tasks=())

        def get_graph(self, **_kwargs):
            return SimpleNamespace(draw_mermaid=lambda: "graph TD;")

    runtime = SimpleNamespace(
        unresolved_tools=[], unresolved_functions=[], unresolved_subgraphs=[]
    )
    out = []
    for frame in _stream_run(
        _Graph(), {}, {}, SimpleNamespace(warnings=[]), known, runtime, "t1"
    ):
        name = frame.split("\n")[0][len("event: ") :]
        data = json.loads(frame.split("\n")[1][len("data: ") :])
        out.append((name, data))
    return out


def test_every_update_frame_carries_the_resolved_active_canvas_node() -> None:
    events = _frames(
        [
            ((), "updates", {"node_router_1": {"decisions": {"node:router.1": "music"}}}),
            (("wf_music:ckpt-1",), "updates", {"inner_answer": {"answer": "42"}}),
            (("node_agent_llm_1:aaa",), "updates", {"model": {}}),
        ],
        KNOWN,
    )
    updates = [d for name, d in events if name == "update"]

    assert [u["activeNode"] for u in updates] == [
        "node:router.1",
        "node:mount.music",
        "node:agent.llm-1",
    ]
    # Additive only — nothing the old clients read has changed shape.
    assert updates[1]["node"] == "inner_answer"
    assert updates[1]["internal"] is True
