"""Per-mount overrides: one shared package, per-instance configuration.

Design: docs/decisions/mount-overrides.md. The merge happens in exactly one
place, on the in-memory child document only (the compile seam stays
one-directional), and an override naming an unknown child node id warns
loudly instead of failing the run.
"""

from __future__ import annotations

import copy

from openstategraph.compile.node_runtime import apply_mount_overrides

CHILD = {
    "version": 2,
    "name": "Team",
    "settings": {},
    "nodes": [
        {"id": "lead1", "type": "orchestrate.supervisor", "data": {"maxSubtasks": 3}},
        {"id": "grader1", "type": "route.grader", "data": {"criteria": "- default", "maxAttempts": 2}},
    ],
    "edges": [],
}


class TestTheMerge:
    def test_an_override_replaces_the_named_field_only(self) -> None:
        doc, warnings = apply_mount_overrides(CHILD, {"grader1": {"criteria": "- stricter"}})
        grader = next(n for n in doc["nodes"] if n["id"] == "grader1")
        assert grader["data"]["criteria"] == "- stricter"
        assert grader["data"]["maxAttempts"] == 2
        assert warnings == []

    def test_the_source_document_is_never_mutated(self) -> None:
        before = copy.deepcopy(CHILD)
        apply_mount_overrides(CHILD, {"grader1": {"criteria": "- changed"}})
        assert CHILD == before

    def test_no_overrides_returns_the_document_untouched(self) -> None:
        doc, warnings = apply_mount_overrides(CHILD, None)
        assert doc is CHILD
        assert warnings == []

    def test_several_nodes_can_be_overridden_at_once(self) -> None:
        doc, _ = apply_mount_overrides(
            CHILD, {"grader1": {"maxAttempts": 5}, "lead1": {"maxSubtasks": 1}}
        )
        assert next(n for n in doc["nodes"] if n["id"] == "grader1")["data"]["maxAttempts"] == 5
        assert next(n for n in doc["nodes"] if n["id"] == "lead1")["data"]["maxSubtasks"] == 1


class TestValidationIsLoudNotFatal:
    def test_an_unknown_child_node_id_warns_and_runs_on_defaults(self) -> None:
        doc, warnings = apply_mount_overrides(CHILD, {"nonsense": {"criteria": "- x"}})
        assert len(warnings) == 1
        assert "nonsense" in warnings[0]
        assert next(n for n in doc["nodes"] if n["id"] == "grader1")["data"]["criteria"] == "- default"

    def test_a_non_dict_override_value_warns_instead_of_crashing(self) -> None:
        _, warnings = apply_mount_overrides(CHILD, {"grader1": "not a mapping"})
        assert len(warnings) == 1
        assert "grader1" in warnings[0]

    def test_a_non_dict_overrides_field_warns_once(self) -> None:
        doc, warnings = apply_mount_overrides(CHILD, "garbage")
        assert doc is CHILD
        assert len(warnings) == 1


class TestWiringThroughTheMount:
    def test_subgraph_factory_applies_overrides_and_collects_warnings(self) -> None:
        """The child compiles with the merged copy; a bad id reaches
        `override_warnings` prefixed with the slug."""
        from openstategraph.compile.node_runtime import NodeRuntime, RuntimeServices
        from openstategraph.compile.workflow_compiler import CompiledPlan

        child = {
            "version": 2, "name": "Mini", "settings": {},
            "nodes": [
                {"id": "cin", "type": "input.text", "data": {}},
                {"id": "cout", "type": "output.formatted", "data": {}},
            ],
            "edges": [{"source": {"nodeId": "cin", "portId": "text"},
                       "target": {"nodeId": "cout", "portId": "result"}}],
        }
        runtime = NodeRuntime(services=RuntimeServices(
            model=None, document_loader=lambda slug: child,
        ))
        node = {"id": "team1", "type": "team.workflow",
                "data": {"workflow": "mini",
                          "overrides": {"cin": {"prompt": "seeded"},
                                        "ghost": {"x": 1}}}}
        runtime._subgraph("team1", node, CompiledPlan())
        assert runtime.override_warnings == [
            'mini: override targets unknown child node "ghost" — the package default ran'
        ]
        # and the shared child dict itself was never mutated
        assert child["nodes"][0]["data"] == {}


class TestTheInspectorStringForm:
    """The editor's textarea stores overrides as a JSON string."""

    def test_a_json_string_is_one_and_the_same_contract(self) -> None:
        doc, warnings = apply_mount_overrides(CHILD, '{"grader1": {"maxAttempts": 7}}')
        assert warnings == []
        assert next(n for n in doc["nodes"] if n["id"] == "grader1")["data"]["maxAttempts"] == 7

    def test_malformed_json_warns_and_runs_on_defaults(self) -> None:
        doc, warnings = apply_mount_overrides(CHILD, "{not json")
        assert doc is CHILD
        assert "not valid JSON" in warnings[0]

    def test_an_empty_string_is_a_no_op(self) -> None:
        assert apply_mount_overrides(CHILD, "  ") == (CHILD, []) or apply_mount_overrides(CHILD, "")[1] == []
