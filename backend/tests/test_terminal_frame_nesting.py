"""A child's node ids stop overwriting the parent's — ticket 40.

`done.outputs` and `done.decisions` were flat `{node id: value}` maps
accumulated across **every** document a run touched. `concierge` and
`chinook-assistant` ship sharing `in1`, `router1` and `out1`, so the child's
values landed on the parent's keys and the parent's own facts were simply gone.

Captured on a real `?w=concierge` run while fixing tickets 33/34:

    "decisions": {"router1": "b-data", "grader-sql": "pass"}

`b-data` is the **child's** branch. The parent's router chose `b-music`, and
the terminal frame had no way to say both.

## The shape, and why this one

Three were on the table (see the ticket). This is the additive one: the flat
maps keep their exact meaning — **the outermost document's own nodes** — and a
sibling `nested` map carries everything below, keyed by mount path. An older
client sees precisely what it saw before, minus the lies, and a new one can ask
about an instance.

The key is the mount chain plus the node id, `wf-music/agent-sql`, which is the
same vocabulary as the frame's `path`, the address bar and `MountAddress`. That
is ticket 42's whole point: one way to name a node inside a mounted document,
not four.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.api.audience import Audience
from openstategraph.api.streaming import _run_frames

KNOWN = {
    "in1": "in1",
    "router1": "router1",
    "wf_music": "wf-music",
    "wf_other": "wf-other",
    "out1": "out1",
}
WIDE = {**KNOWN, "agent_sql": "agent-sql", "deep": "deep", "wf_inner": "wf-inner"}
MOUNT_NS = ("wf_music:2f0b",)
DEEP_NS = ("wf_music:2f0b", "wf_inner:9ac1")


def _done(chunks: list[Any]) -> dict[str, Any]:
    class _Graph:
        def stream(self, *_a: Any, **_k: Any) -> Any:
            return iter(chunks)

        def get_state(self, _config: Any) -> Any:
            return SimpleNamespace(next=(), tasks=())

        def get_graph(self, **_k: Any) -> Any:
            return SimpleNamespace(draw_mermaid=lambda: "graph TD;")

    runtime = SimpleNamespace(
        diagnostics=CompileDiagnostics(),
        node_ids_by_name=WIDE,
        mount_slugs={},
    )
    for raw in _run_frames(
        _Graph(),
        {},
        {"configurable": {"thread_id": "t1", "workflow_slug": "concierge"}},
        SimpleNamespace(warnings=[]),
        KNOWN,
        runtime,
        "t1",
        Audience.DEVELOPER,
    ):
        head, _, body = raw.partition("\n")
        if head == "event: done":
            return json.loads(body.partition("data: ")[2])
    raise AssertionError("no terminal frame was emitted")


class TestTheParentKeepsItsOwnFacts:
    def test_a_childs_router_no_longer_overwrites_the_parents(self) -> None:
        """The defect, in the shape the wire recorded it."""
        done = _done(
            [
                ((), "updates", {"router1": {"decisions": {"router1": "b-music"}}}),
                (MOUNT_NS, "updates", {"router1": {"decisions": {"router1": "b-data"}}}),
            ]
        )
        assert done["decisions"]["router1"] == "b-music"

    def test_a_childs_output_no_longer_overwrites_the_parents(self) -> None:
        done = _done(
            [
                ((), "updates", {"in1": {"outputs": {"in1": "the parent's question"}}}),
                (MOUNT_NS, "updates", {"in1": {"outputs": {"in1": "the child's question"}}}),
            ]
        )
        assert done["outputs"]["in1"] == "the parent's question"

    def test_the_flat_maps_hold_only_the_outermost_document(self) -> None:
        """What "flat" now *means*, stated once so a reader need not infer it."""
        done = _done(
            [
                ((), "updates", {"in1": {"outputs": {"in1": "parent"}}}),
                (MOUNT_NS, "updates", {"agent_sql": {"outputs": {"agent-sql": "child"}}}),
            ]
        )
        assert set(done["outputs"]) == {"in1"}


class TestTheChildIsStillReported:
    def test_a_mounted_nodes_output_is_keyed_by_its_mount_path(self) -> None:
        done = _done(
            [(MOUNT_NS, "updates", {"agent_sql": {"outputs": {"agent-sql": "the answer"}}})]
        )
        assert done["nested"]["outputs"]["wf-music/agent-sql"] == "the answer"

    def test_a_mounted_decision_is_keyed_the_same_way(self) -> None:
        done = _done([(MOUNT_NS, "updates", {"router1": {"decisions": {"router1": "b-data"}}})])
        assert done["nested"]["decisions"]["wf-music/router1"] == "b-data"

    def test_both_routers_are_readable_at_once(self) -> None:
        """The point of the whole change: two true facts, both kept."""
        done = _done(
            [
                ((), "updates", {"router1": {"decisions": {"router1": "b-music"}}}),
                (MOUNT_NS, "updates", {"router1": {"decisions": {"router1": "b-data"}}}),
            ]
        )
        assert done["decisions"]["router1"] == "b-music"
        assert done["nested"]["decisions"]["wf-music/router1"] == "b-data"

    def test_a_grandchild_carries_its_whole_chain(self) -> None:
        done = _done([(DEEP_NS, "updates", {"deep": {"outputs": {"deep": "from below"}}})])
        assert done["nested"]["outputs"]["wf-music/wf-inner/deep"] == "from below"

    def test_two_mounts_of_one_package_stay_apart(self) -> None:
        """The instance property, on the surface that could not express it."""
        done = _done(
            [
                (("wf_music:aa",), "updates", {"agent_sql": {"outputs": {"agent-sql": "first"}}}),
                (("wf_other:bb",), "updates", {"agent_sql": {"outputs": {"agent-sql": "second"}}}),
            ]
        )
        nested = done["nested"]["outputs"]
        assert nested["wf-music/agent-sql"] == "first"
        assert nested["wf-other/agent-sql"] == "second"


class TestItStaysAdditive:
    def test_a_run_with_no_mounts_reports_an_empty_nested_map(self) -> None:
        """Present and empty, not absent: a client that reads it unconditionally
        must not have to special-case the common case."""
        done = _done([((), "updates", {"in1": {"outputs": {"in1": "only me"}}})])
        assert done["nested"] == {"outputs": {}, "decisions": {}}
        assert done["outputs"] == {"in1": "only me"}

    def test_the_turn_reset_marker_never_becomes_a_key(self) -> None:
        done = _done(
            [(MOUNT_NS, "updates", {"in1": {"outputs": {"__turn_reset__": "", "in1": "q"}}})]
        )
        assert all("__turn_reset__" not in key for key in done["nested"]["outputs"])
