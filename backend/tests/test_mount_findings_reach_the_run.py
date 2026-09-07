"""A finding recorded inside a mount reaches the run that mounts it.

`workflow-gallery` 75. `_subgraph` absorbed a child runtime's
`machinery_nodes`, `names` and `mounted_graphs` upward and **not** its
`diagnostics`, so every sentence a mounted package's compile recorded was
dropped on the floor. Measured before anything was changed: a parent mounting
a child whose document names an unimplemented node type answered
`warnings() == []` while the same child compiled on its own said what was
wrong (`export-and-eject/13` hit the same silence from the other side and had
to record its own report on the parent).

The shape chosen is **absorb, prefixed, deduplicated by package path** — see
`CompileDiagnostics.absorb` for why the path is the chain of *slugs* and not
the chain of node ids, which is what makes "a package mounted three times does
not say the same thing three times" true rather than aspirational.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.diagnostics import CompileDiagnostics, Finding
from openstategraph.compile.node_runtime import NodeRuntime, RuntimeServices
from openstategraph.compile.workflow_compiler import CompiledPlan


def _document(*nodes: dict[str, Any]) -> dict[str, Any]:
    ids = [node["id"] for node in nodes]
    return {
        "version": 2,
        "name": "Doc",
        "settings": {},
        "nodes": list(nodes),
        "edges": [
            {
                "source": {"nodeId": first, "portId": "text"},
                "target": {"nodeId": second, "portId": "result"},
            }
            for first, second in zip(ids, ids[1:])
        ],
    }


#: A child whose compile records exactly one finding: `UNKNOWN_NODE_TYPE`.
BROKEN_CHILD = _document(
    {"id": "in1", "type": "input.text", "data": {}},
    {"id": "mystery1", "type": "agent.raect", "data": {}},
    {"id": "out1", "type": "output.formatted", "data": {}},
)


def _mount(runtime: NodeRuntime, node_id: str, slug: str) -> None:
    runtime._subgraph(
        node_id,
        {"id": node_id, "type": "workflow.subgraph", "data": {"workflow": slug}},
        CompiledPlan(),
    )


class TestTheSilence:
    def test_a_finding_inside_a_mount_reaches_the_parent(self) -> None:
        runtime = NodeRuntime(
            services=RuntimeServices(model=None, document_loader=lambda slug: BROKEN_CHILD)
        )
        _mount(runtime, "team1", "mini")

        warnings = runtime.diagnostics.warnings()
        assert len(warnings) == 1
        assert warnings[0].startswith('Inside mounted workflow "mini": ')
        assert "agent.raect" in warnings[0]

    def test_a_mountless_document_says_exactly_what_it_said_before(self) -> None:
        """The inverse. Nothing absorbed means nothing added, byte for byte."""
        diagnostics = CompileDiagnostics()
        diagnostics.record(Finding.UNRESOLVED_TOOL, "reddit")

        assert diagnostics.warnings() == [
            CompileDiagnostics.sentence_for(Finding.UNRESOLVED_TOOL).format("reddit")
        ]
        assert diagnostics.failure_warnings() == diagnostics.warnings()


class TestSayingItOnce:
    def test_a_package_mounted_three_times_does_not_say_it_three_times(self) -> None:
        runtime = NodeRuntime(
            services=RuntimeServices(model=None, document_loader=lambda slug: BROKEN_CHILD)
        )
        for node_id in ("team1", "team2", "team3"):
            _mount(runtime, node_id, "mini")

        assert len(runtime.diagnostics.warnings()) == 1

    def test_two_packages_each_speak(self) -> None:
        other = _document(
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "mystery1", "type": "agent.nonsuch", "data": {}},
        )
        documents = {"mini": BROKEN_CHILD, "maxi": other}
        runtime = NodeRuntime(
            services=RuntimeServices(model=None, document_loader=documents.__getitem__)
        )
        _mount(runtime, "team1", "mini")
        _mount(runtime, "team2", "maxi")

        warnings = runtime.diagnostics.warnings()
        assert len(warnings) == 2
        assert warnings[0].startswith('Inside mounted workflow "mini": ')
        assert warnings[1].startswith('Inside mounted workflow "maxi": ')


class TestDepth:
    def test_a_finding_three_levels_deep_names_where_it_came_from(self) -> None:
        middle = {
            "version": 2,
            "name": "Middle",
            "settings": {},
            "nodes": [{"id": "inner1", "type": "workflow.subgraph", "data": {"workflow": "mini"}}],
            "edges": [],
        }
        documents = {"middle": middle, "mini": BROKEN_CHILD}
        runtime = NodeRuntime(
            services=RuntimeServices(model=None, document_loader=documents.__getitem__)
        )
        _mount(runtime, "team1", "middle")

        warnings = runtime.diagnostics.warnings()
        assert len(warnings) == 1
        assert warnings[0].startswith('Inside mounted workflow "middle/mini": ')


class TestNoReportMovesAnExitCode:
    def test_an_absorbed_report_rides_warnings_and_not_failures(self) -> None:
        child = CompileDiagnostics()
        child.record(Finding.UNWIRED_REVISE, "grader1")
        parent = CompileDiagnostics()
        parent.absorb(child, through="mini")

        assert len(parent.warnings()) == 1
        assert parent.failure_warnings() == []

    def test_an_absorbed_failure_reaches_failures(self) -> None:
        child = CompileDiagnostics()
        child.record(Finding.UNRESOLVED_TOOL, "reddit")
        parent = CompileDiagnostics()
        parent.absorb(child, through="mini")

        assert len(parent.failure_warnings()) == 1
        assert parent.failure_warnings() == parent.warnings()

    def test_a_report_stays_a_report_three_levels_down(self) -> None:
        grandchild = CompileDiagnostics()
        grandchild.record(Finding.STALE_TOOL_DENIAL, "agent1", "you have no tools")
        child = CompileDiagnostics()
        child.absorb(grandchild, through="inner")
        parent = CompileDiagnostics()
        parent.absorb(child, through="outer")

        assert parent.warnings()[0].startswith('Inside mounted workflow "outer/inner": ')
        assert parent.failure_warnings() == []


class TestTheParentStillOwnsItsOwn:
    def test_its_own_findings_come_first_and_are_unprefixed(self) -> None:
        child = CompileDiagnostics()
        child.record(Finding.UNRESOLVED_TOOL, "child-tool")
        parent = CompileDiagnostics()
        parent.record(Finding.UNRESOLVED_TOOL, "parent-tool")
        parent.absorb(child, through="mini")

        first, second = parent.warnings()
        assert "parent-tool" in first and not first.startswith("Inside")
        assert second.startswith('Inside mounted workflow "mini": ')

    def test_absorbing_the_same_child_twice_is_a_no_op(self) -> None:
        child = CompileDiagnostics()
        child.record(Finding.UNRESOLVED_TOOL, "child-tool")
        parent = CompileDiagnostics()
        parent.absorb(child, through="mini")
        parent.absorb(child, through="mini")

        assert len(parent.warnings()) == 1
