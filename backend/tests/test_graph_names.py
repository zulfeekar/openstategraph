"""Which canvas node, in which document, a compiled graph name refers to.

Two maps on `NodeRuntime` — `node_ids_by_name` and `mount_slugs` — always
travelled together: `api/streaming.py` hands both to `RunPathResolver` in one
call, and both were read through `getattr(runtime, name, None) or {}` because
the contract was loose (reviews-2026-08-14 ticket 07).

They answer one question in two halves, and the second half exists because the
first is not enough: `node_ids_by_name` cannot say *which document* a resolved
id belongs to, and the shipped `concierge` mounts `chinook-assistant` where
both documents have an `in1`, a `router1` and an `out1`.

The behaviour worth having a name for is `absorb`. A child's frames ride the
**parent's** SSE stream, so the parent's fold is the only place that can
resolve them — and the two halves fold by opposite rules, which is exactly the
kind of thing that goes wrong when it lives inline in a 250-line factory
method.
"""

from __future__ import annotations

import pytest

from openstategraph.compile.graph_names import GraphNames


class TestNamingOneDocument:
    def test_a_remembered_name_resolves_to_its_canvas_id(self) -> None:
        names = GraphNames()

        names.remember("agent_sql", "agent-sql")

        assert names.node_ids_by_name == {"agent_sql": "agent-sql"}

    def test_the_first_writer_wins(self) -> None:
        """Two documents share ids — `concierge` and `chinook-assistant` both
        have `in1` and `router1` — and this document's own answer is the
        authoritative one."""
        names = GraphNames()

        names.remember("in1", "mine")
        names.remember("in1", "theirs")

        assert names.node_ids_by_name["in1"] == "mine"

    def test_a_mount_records_the_document_it_descends_into(self) -> None:
        names = GraphNames()

        names.mounted("m1", "child-b")

        assert names.mount_slugs == {"m1": "child-b"}

    def test_the_maps_it_hands_out_cannot_be_written_through(self) -> None:
        """Refused loudly, not ignored quietly.

        `remember` is first-wins, so a caller reaching past it to write
        directly is a caller expecting the opposite rule — which is worth an
        exception rather than a silently dropped assignment.
        """
        names = GraphNames()
        names.remember("in1", "mine")

        with pytest.raises(TypeError):
            names.node_ids_by_name["in1"] = "tampered"  # type: ignore[index]

        assert names.node_ids_by_name["in1"] == "mine"


class TestAbsorbingAChild:
    def test_a_childs_names_become_reachable_from_the_parent(self) -> None:
        child = GraphNames()
        child.remember("agent_sql", "agent-sql")
        parent = GraphNames()

        parent.absorb(child, through="m1", slug="chinook")

        assert parent.node_ids_by_name["agent_sql"] == "agent-sql"

    def test_the_parents_own_name_survives_the_childs(self) -> None:
        child = GraphNames()
        child.remember("in1", "childs-in1")
        parent = GraphNames()
        parent.remember("in1", "parents-in1")

        parent.absorb(child, through="m1", slug="chinook")

        assert parent.node_ids_by_name["in1"] == "parents-in1"

    def test_the_mount_itself_is_recorded(self) -> None:
        parent = GraphNames()

        parent.absorb(GraphNames(), through="m1", slug="child-b")

        assert parent.mount_slugs["m1"] == "child-b"

    def test_a_grandchilds_slug_is_keyed_by_the_whole_mount_path(self) -> None:
        """Node ids are unique within a document and nowhere else.

        Two sibling subtrees that each mount something at a node called
        `inner` are two different mounts of two different packages, and a flat
        map collapsed them first-wins — a frame from one was attributed to the
        other's slug.
        """
        grandchild_of_b = GraphNames()
        grandchild_of_b.mounted("inner", "grand-x")
        grandchild_of_d = GraphNames()
        grandchild_of_d.mounted("inner", "grand-y")
        parent = GraphNames()

        parent.absorb(grandchild_of_b, through="m1", slug="child-b")
        parent.absorb(grandchild_of_d, through="m2", slug="child-d")

        assert parent.mount_slugs["m1/inner"] == "grand-x"
        assert parent.mount_slugs["m2/inner"] == "grand-y"
        # The bare id must not be there at all — that is the collapse itself.
        assert "inner" not in parent.mount_slugs

    def test_absorbing_does_not_alias_the_childs_maps(self) -> None:
        child = GraphNames()
        parent = GraphNames()
        parent.absorb(child, through="m1", slug="child-b")

        child.remember("late", "late-node")

        assert "late" not in parent.node_ids_by_name
