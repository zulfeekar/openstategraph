"""A mount renders as a boundary you can look inside — `workflow-gallery` 28.

`xray=True` expands a **LangGraph subgraph**, and a mount is not one:
`NodeRuntime._subgraph` compiles the child and hands the parent's `StateGraph`
an ordinary Python closure. LangGraph cannot see through a function, so for as
long as the preview was *only* `get_graph(xray=True).draw_mermaid()`, three
documents and three levels rendered as three featureless boxes.

So the composition is walked here rather than asked of LangGraph. These tests
are written against `CompiledWorkflow.mermaid()` and against the CLI — the two
surfaces a reader actually looks at — and not against the helper, because a
test that the helper returns node names would stay green if `mermaid()` never
called it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"


@pytest.fixture(scope="module")
def nested_mermaid() -> str:
    from openstategraph import load_workflow

    with load_workflow(EXAMPLES / "nested-mounts") as workflow:
        return workflow.mermaid()


class TestThreeLevelsAreVisible:
    def test_the_mount_becomes_a_subgraph_block(self, nested_mermaid: str) -> None:
        assert "subgraph mount_mid" in nested_mermaid

    def test_the_grandchild_is_a_block_inside_it(self, nested_mermaid: str) -> None:
        assert "subgraph mount_inner" in nested_mermaid

    def test_the_innermost_workflows_own_nodes_are_drawn(
        self, nested_mermaid: str
    ) -> None:
        """`chained-summarizer`, three levels down. Its two agents are what a
        reader of the gallery page is looking for; the ticket's reproduction
        showed neither."""
        # `\\3a` is how `draw_mermaid` escapes the `:` in a prefixed id;
        # Mermaid reads it back as the colon and draws the nesting.
        assert r"mount_mid\3amount_inner\3asummarise1" in nested_mermaid
        assert r"mount_mid\3amount_inner\3ashorten1" in nested_mermaid

    def test_the_parents_own_nodes_survive(self, nested_mermaid: str) -> None:
        assert "in1" in nested_mermaid and "out1" in nested_mermaid

    def test_the_parent_edges_are_rewired_into_the_child(
        self, nested_mermaid: str
    ) -> None:
        """The boundary is only useful if the arrows cross it: the parent's
        input must reach a node *inside* the mount, and the mount's last node
        must reach the parent's output. An expansion that left `in1 -->
        mount_mid` behind would draw a box with nothing entering it."""
        assert r"in1 --> mount_mid\3ain1;" in nested_mermaid
        assert " --> out1;" in nested_mermaid
        assert "in1 --> mount_mid;" not in nested_mermaid


class TestXrayIsStillTheWordForIt:
    def test_no_expansion_when_xray_is_off(self) -> None:
        """`--no-xray` is the flag for "what LangGraph itself built", and it
        must keep meaning that — otherwise there is no way to see the topology
        the compiler actually handed the runtime."""
        from openstategraph import load_workflow

        with load_workflow(EXAMPLES / "nested-mounts") as workflow:
            flat = workflow.mermaid(xray=False)

        assert "subgraph" not in flat
        assert "in1 --> mount_mid;" in flat


class TestAWorkflowWithNoMounts:
    def test_is_byte_identical_either_way(self) -> None:
        """Expansion is not allowed to perturb the 22 examples that mount
        nothing — including `evaluator-optimizer`, which
        `test_behind_the_scenes.py` renders into a shipped page."""
        from openstategraph import load_workflow

        with load_workflow(EXAMPLES / "evaluator-optimizer") as workflow:
            assert workflow.mermaid() == workflow.mermaid(xray=False)


class TestTheCLIPrintsIt:
    def test_graph_command_shows_the_composition(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`openstategraph graph` is the reproduction in the ticket."""
        from openstategraph import cli

        cli.main(["graph", str(EXAMPLES / "nested-mounts")])

        assert "subgraph mount_inner" in capsys.readouterr().out
