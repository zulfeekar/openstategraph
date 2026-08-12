"""The generated node/port catalogue, and the gate that keeps it honest.

Register RC-01. The compiler used to carry a hand-written Python copy of the
TypeScript node catalogue; `port_specs.json` is now generated from
`src/nodes/portSpecs.ts` and this module is what proves the Python side reads it
correctly and refuses a version it does not understand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.compile.node_catalogue import (
    ARTIFACT_PATH,
    GENERATE_COMMAND,
    SCHEMA_VERSION,
    CatalogueError,
    load_catalogue,
)
from openstategraph.compile.workflow_compiler import (
    DEFAULT_PORT_SPECS,
    default_port_resolver,
)

#: The table `workflow_compiler.py` hand-maintained before generation, kept as a
#: fixed floor. The assertion is one-directional — the generated catalogue must
#: be a superset — so nothing here has to be edited when a port is added in
#: TypeScript, and no node type can be silently dropped in the move.
HAND_WRITTEN_TABLE: dict[str, dict[str, tuple[str, str]]] = {
    "input.text": {"text": ("text", "out")},
    "input.markdown": {"skill": ("skill", "out")},
    "agent.llm": {
        "prompt": ("text", "in"),
        "skill": ("skill", "in"),
        "tools": ("tool", "in"),
        "feedback": ("feedback", "in"),
        "result": ("result", "out"),
    },
    "output.formatted": {"result": ("result", "in")},
    "route.grader": {
        "candidate": ("result", "in"),
        "pass": ("result", "out"),
        "revise": ("feedback", "out"),
    },
    "route.classifier": {"question": ("text", "in")},
    "orchestrate.supervisor": {
        "instruction": ("text", "in"),
        "feedback": ("feedback", "in"),
        "workers": ("worker", "out"),
    },
    "orchestrate.worker": {
        "dispatch": ("worker", "in"),
        "skill": ("skill", "in"),
        "tools": ("tool", "in"),
        "result": ("result", "out"),
    },
    "function.format_report": {
        "candidate": ("result", "in"),
        "report": ("result", "out"),
    },
    "human.approval": {
        "candidate": ("result", "in"),
        "approved": ("result", "out"),
        "rejected": ("feedback", "out"),
    },
}


class TestTheArtifactShips:
    def test_it_sits_inside_the_python_package_so_a_wheel_carries_it(self) -> None:
        # A wheel cannot run tsx. If this file were outside `openstategraph/`,
        # an installed consumer would import a catalogue that is not there.
        assert ARTIFACT_PATH.is_file()
        assert ARTIFACT_PATH.parent.name == "compile"

    def test_it_says_how_to_regenerate_itself(self) -> None:
        payload = json.loads(ARTIFACT_PATH.read_text())
        assert payload["generated_by"] == GENERATE_COMMAND
        assert "DO NOT EDIT" in payload["warning"]


class TestNothingWasLostInTheMove:
    def test_the_generated_table_is_a_superset_of_the_hand_written_one(self) -> None:
        for node_type, ports in HAND_WRITTEN_TABLE.items():
            assert node_type in DEFAULT_PORT_SPECS, f"{node_type} vanished"
            for port_id, (port_type, direction) in ports.items():
                spec = DEFAULT_PORT_SPECS[node_type].get(port_id)
                assert spec is not None, f"{node_type}.{port_id} vanished"
                assert (spec.type, spec.direction) == (port_type, direction)

    def test_it_now_covers_node_types_the_hand_written_table_never_had(self) -> None:
        # The drift the register named: these were composable in the editor and
        # invisible to the compiler and to every MCP client.
        catalogue = load_catalogue()
        for node_type in (
            "workflow.subgraph",
            "team.workflow",
            "tool.reddit-search",
            "tool.web-search",
            "tool.chinook-execute-sql",
        ):
            assert node_type in catalogue.node_types

    def test_a_mounted_workflow_declares_its_ports(self) -> None:
        # `workflow.subgraph` was in the architect's known-types set but had no
        # port entry, so `get_node_vocabulary` advertised it with zero ports.
        specs = DEFAULT_PORT_SPECS["workflow.subgraph"]
        assert (specs["input"].type, specs["input"].direction) == ("result", "in")
        assert (specs["result"].type, specs["result"].direction) == ("result", "out")


class TestTheResolverReadsGeneratedSemantics:
    def test_a_router_branch_port_resolves_from_the_generated_prefix(self) -> None:
        spec = default_port_resolver("route.classifier", "branch:anything")
        assert (spec.type, spec.direction) == ("text", "out")

    def test_the_default_branch_configuration_is_not_baked_in_as_ports(self) -> None:
        # A router's five seeded branches are one document's config, not the
        # node type's contract, so they must not appear as static ports.
        # `skill` is static — every prompted node type declares it (ticket 05)
        # — so only the branch outputs are absent here.
        assert set(DEFAULT_PORT_SPECS["route.classifier"]) == {"question", "skill"}

    def test_an_unknown_node_type_still_defaults_to_control_flow(self) -> None:
        assert default_port_resolver("some.future.node", "in").type == "text"


class TestPortMetadataCrossesTheBoundary:
    def test_a_bus_port_declares_unlimited_rather_than_a_non_finite_number(self) -> None:
        # CLAUDE.md: never put Infinity in a serialisable field. `None` is the
        # spelling, and an agent's tool bus is the port that needs it.
        assert DEFAULT_PORT_SPECS["agent.llm"]["tools"].max_connections is None
        assert DEFAULT_PORT_SPECS["agent.llm"]["prompt"].max_connections == 1

    def test_required_inputs_are_carried(self) -> None:
        assert DEFAULT_PORT_SPECS["agent.llm"]["prompt"].required is True
        assert DEFAULT_PORT_SPECS["agent.llm"]["skill"].required is False

    def test_port_level_widening_is_resolved_for_us(self) -> None:
        # An agent's `prompt` accepts a previous agent's `result`. Python must
        # not have to re-implement the editor's connection rules to know that.
        assert DEFAULT_PORT_SPECS["agent.llm"]["prompt"].accepts == ("result", "text")

    def test_every_port_type_the_catalogue_uses_is_classified_by_the_compiler(self) -> None:
        # The one classification Python still owns: control flow versus binding.
        # A port type added in TypeScript and never classified here would make
        # the compiler treat a new binding as an ordinary edge.
        from openstategraph.compile.workflow_compiler import (
            BINDING_PORT_TYPES,
            CONTROL_PORT_TYPES,
            WORKER_PORT_TYPE,
        )

        known = set(CONTROL_PORT_TYPES) | set(BINDING_PORT_TYPES) | {WORKER_PORT_TYPE, "feedback"}
        catalogue = load_catalogue()
        used = {port_type["id"] for port_type in catalogue.port_types}
        assert used <= known, f"unclassified port types: {sorted(used - known)}"


class TestTheDriftGateFails:
    def test_a_corrupted_schema_version_is_refused_by_name(self, tmp_path: Path) -> None:
        payload = json.loads(ARTIFACT_PATH.read_text())
        payload["schema_version"] = SCHEMA_VERSION + 1
        corrupted = tmp_path / "port_specs.json"
        corrupted.write_text(json.dumps(payload))

        with pytest.raises(CatalogueError) as excinfo:
            load_catalogue(corrupted)
        assert GENERATE_COMMAND in str(excinfo.value)

    def test_an_unparseable_artifact_is_refused_rather_than_silently_empty(
        self, tmp_path: Path
    ) -> None:
        corrupted = tmp_path / "port_specs.json"
        corrupted.write_text("{ not json")
        with pytest.raises(CatalogueError):
            load_catalogue(corrupted)

    def test_a_missing_artifact_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CatalogueError):
            load_catalogue(tmp_path / "absent.json")
