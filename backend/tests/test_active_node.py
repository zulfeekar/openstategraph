"""`activeNode`: the honest answer to "what is running right now".

Synthetic frames only. The bug this pins (ticket 01): while a mounted
team/subgraph or a long agent step is working, both clients guessed the
active node from the frames they could see and kept the highlight on the
*previous* top-level node — usually the router. The stream now resolves it
once, server-side, and both surfaces read the field.
"""

from __future__ import annotations

from types import SimpleNamespace

from conftest import ScriptedGraph, drive_fold  # noqa: E402

from openstategraph.compile.diagnostics import CompileDiagnostics
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
        diagnostics=CompileDiagnostics()
    )
    out = []
    for frame in drive_fold(_stream_run(
        ScriptedGraph(_Graph()), {}, {}, SimpleNamespace(warnings=[]), known, runtime, "t1"
    )):
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


# --- replayed from a real run ----------------------------------------------
#
# Ticket 02's own lesson, and the reason the tests above did not catch it: they
# are written from namespaces someone invented, and the invented ones were the
# ones LangGraph produces with NO checkpointer. The live path has one, and the
# shape differed. Everything below is driven by
# `data/recorded_chinook_assistant_run.json` — the namespaces, node names and
# frame ORDER of one real run of `chinook-assistant` against a real model,
# recorded off `graph.stream` and replayed verbatim.


def _recorded() -> dict:
    import json
    from pathlib import Path

    path = Path(__file__).parent / "data" / "recorded_chinook_assistant_run.json"
    return json.loads(path.read_text())


def _replay_recorded() -> list[tuple[str, dict]]:
    """The recorded run, pushed back through the real stream fold."""
    recorded = _recorded()
    chunks: list[tuple[tuple[str, ...], str, object]] = []
    for chunk in recorded["chunks"]:
        namespace = tuple(chunk["ns"])
        if chunk["mode"] == "updates":
            chunks.append((namespace, "updates", {name: {} for name in chunk["nodes"]}))
        else:
            # The fold only reads `.content` and `langgraph_node`; the recording
            # kept the length rather than megabytes of model prose.
            message = SimpleNamespace(content="x" * chunk["chars"])
            chunks.append(
                (namespace, "messages", (message, {"langgraph_node": chunk["node"]}))
            )
    return _frames(chunks, recorded["nodeIdsByName"])


def _highlight_track(events: list[tuple[str, dict]]) -> list[str]:
    """What a client that reads `activeNode` would light up, in order.

    Deduplicated exactly as both clients deduplicate it — which is also the
    assertion that the coalescing works: one entry per *change*, not per frame.
    """
    track: list[str] = []
    for _name, data in events:
        active = str(data.get("activeNode") or "")
        if active and (not track or track[-1] != active):
            track.append(active)
    return track


def test_the_recorded_run_highlights_the_four_canvas_nodes_in_order() -> None:
    """`in1 -> router1 -> analyst -> out1`, and nothing else ever glows.

    `agent_sql`, `grader_sql`, `model` and `tools` are all real frames in this
    recording. None of them is a node of the canvas being watched — three
    belong to the mounted `chinook-nl-to-sql` document and two to an agent's
    own compiled loop — so the box that must glow for every one of them is the
    mount, `analyst`.

    **The recording predates ticket 10 deliberately.** That mount no longer
    exists — the analyst is an inline branch now — and this file is the reason
    the recording is kept anyway: it is the only *real* stream this repository
    holds in which a child document's `in1` collides with a parent's, which is
    the whole subject below. Re-recording it against the collapsed document
    would delete the evidence and leave the collision logic untested.
    """
    assert _highlight_track(_replay_recorded()) == ["in1", "router1", "analyst", "out1"]


def test_the_mount_starts_glowing_when_its_work_starts_not_when_it_ends() -> None:
    """The reported bug, measured on the recording that showed it.

    `updates` frames arrive on completion, so the mount's own update frame is
    the LAST thing the run says about it. If the highlight waited for that, the
    router would hold the glow for every frame in between — 130-odd of them in
    this recording, about twenty seconds of wall clock.
    """
    events = _replay_recorded()
    first_active = next(
        i for i, (_n, d) in enumerate(events) if d.get("activeNode") == "analyst"
    )
    completed = next(
        i
        for i, (name, d) in enumerate(events)
        if name == "update" and d.get("node") == "analyst"
    )

    assert first_active < completed
    # Not "one frame early" — the whole of the mount's work happens in between.
    assert completed - first_active > 100
    # Including the mount's longest single stretch of work: a 100+ frame model
    # turn from inside the child's agent, every frame of which now names the
    # mount. Before the fix these were the frames that said `router1`.
    inner_tokens = [
        d
        for name, d in events[first_active:completed]
        if name == "token" and d["node"] in {"model", "tools", "grader_sql"}
    ]
    assert len(inner_tokens) > 100
    assert {d["activeNode"] for d in inner_tokens} == {"analyst"}


def test_a_node_lights_up_on_its_first_token_not_on_its_completion() -> None:
    """Tokens are the only frames that arrive while a node is still working.

    In the recording, `in1` and `router1` each stream text before their own
    `update` frame lands. Those token frames are what make the glow mean "is
    working" rather than "has finished".
    """
    events = _replay_recorded()

    for node in ("in1", "router1"):
        first = next(i for i, (_n, d) in enumerate(events) if d.get("activeNode") == node)
        completed = next(
            i
            for i, (name, d) in enumerate(events)
            if name == "update" and d.get("node") == node
        )
        assert events[first][0] == "token", f"{node} lit up on an {events[first][0]} frame"
        assert first < completed


def test_nothing_is_attributed_to_the_router_once_the_mount_is_working() -> None:
    """The literal symptom: "the router glows while the analyst works"."""
    events = _replay_recorded()
    started = next(i for i, (_n, d) in enumerate(events) if d.get("activeNode") == "analyst")

    assert not [
        d for _n, d in events[started:] if d.get("activeNode") == "router1"
    ]


def test_a_chatty_model_turn_is_one_highlight_change_not_a_hundred() -> None:
    """Coalescing, checked against the run that produced the flicker risk.

    Every token frame carries `activeNode` (its meaning must not vary by
    frame), so the coalescing lives in the clients — `_highlight_track` is that
    rule. The recording contains a single model turn of 100+ consecutive token
    frames; it must contribute exactly one entry.
    """
    events = _replay_recorded()
    token_frames = [d for name, d in events if name == "token"]

    assert len(token_frames) > 100
    assert len(_highlight_track(events)) == 4


def test_a_child_step_that_shares_a_parents_name_is_still_internal() -> None:
    """In the recording, `chinook-assistant` mounts `chinook-nl-to-sql`; both
    have `in1`/`out1`.

    The recording contains the child's own input and output steps, and their
    graph-node names are identical to the parent's. Only the namespace tells
    them apart — so `internal` is decided by that, not by the name. Otherwise
    a second `in1` row lands in the activity feed halfway through the run, as
    though the canvas's input node had run twice.
    """
    events = _replay_recorded()
    updates = [d for name, d in events if name == "update"]

    inside_the_mount = [d for d in updates if d["namespace"]]
    assert {d["node"] for d in inside_the_mount} >= {"in1", "out1"}
    assert all(d["internal"] for d in inside_the_mount)
    assert all(d["activeNode"] == "analyst" for d in inside_the_mount)

    # The canvas's OWN input and output steps are still flat-feed rows.
    top_level = [d for d in updates if not d["namespace"]]
    assert [d["node"] for d in top_level] == ["in1", "router1", "analyst", "out1"]
    assert not any(d["internal"] for d in top_level)


def test_every_token_frame_still_carries_what_it_always_carried() -> None:
    """Additive: `activeNode` was added beside `node`, never instead of it."""
    events = _replay_recorded()
    tokens = [d for name, d in events if name == "token"]

    assert all({"node", "namespace", "content", "activeNode"} <= set(d) for d in tokens)
    # `node` is still the reporting graph step, which is exactly what makes it
    # useless as a highlight: these are inner names of the mounted document.
    assert {"grader_sql", "model", "tools"} & {d["node"] for d in tokens}
