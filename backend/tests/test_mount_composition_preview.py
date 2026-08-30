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
        """`mount_mid_mount_inner` is the mount **path** — `mount-inner`
        inside `mount-mid`. A mount node id is unique within a document and
        nowhere else, so a second level is drawn under its path rather than
        its bare name (`the-cost-of-one-more` 10); a first level, whose path
        is just its name, is unchanged."""
        assert "subgraph mount_mid_mount_inner" in nested_mermaid

    def test_the_innermost_workflows_own_nodes_are_drawn(
        self, nested_mermaid: str
    ) -> None:
        """`chained-summarizer`, three levels down. Its two agents are what a
        reader of the gallery page is looking for; the ticket's reproduction
        showed neither."""
        # `\\3a` is how `draw_mermaid` escapes the `:` in a prefixed id;
        # Mermaid reads it back as the colon and draws the nesting.
        assert r"mount_mid\3amount_mid_mount_inner\3asummarise1" in nested_mermaid
        assert r"mount_mid\3amount_mid_mount_inner\3ashorten1" in nested_mermaid

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

        assert "subgraph mount_mid_mount_inner" in capsys.readouterr().out


def _leaf() -> dict[str, object]:
    return {
        "version": 3,
        "name": "leaf",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "f1", "type": "function.format_report", "position": {"x": 1, "y": 0}, "data": {}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 2, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "f1", "portId": "in"}},
            {"source": {"nodeId": "f1", "portId": "result"},
             "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


def _mounts_twice(child_slug: str) -> dict[str, object]:
    """One document mounting `child_slug` at `m1` and `m2`.

    Every level of the ladder built from this names its mounts the same two
    things, which is the whole of `the-cost-of-one-more` 10: node ids are
    unique within a document and nowhere else.
    """
    return {
        "version": 3,
        "name": "p",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "m1", "type": "workflow.subgraph", "position": {"x": 1, "y": 0},
             "data": {"workflow": child_slug}},
            {"id": "m2", "type": "workflow.subgraph", "position": {"x": 1, "y": 1},
             "data": {"workflow": child_slug}},
            {"id": "j1", "type": "function.format_report", "position": {"x": 2, "y": 0}, "data": {}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 3, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "m1", "portId": "task"}},
            {"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "m2", "portId": "task"}},
            {"source": {"nodeId": "m1", "portId": "answer"},
             "target": {"nodeId": "j1", "portId": "in"}},
            {"source": {"nodeId": "m2", "portId": "answer"},
             "target": {"nodeId": "j1", "portId": "in"}},
            {"source": {"nodeId": "j1", "portId": "result"},
             "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


@pytest.fixture(scope="module")
def repeated_ids(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`p0` and `p1` each mount at nodes called `m1` and `m2`.

    Two *levels* of one composition reusing a mount node id — the shape
    `scripts/measure_mount_depth.py` builds at depth >= 2, and the shape no
    shipped example reaches (`nested-mounts` names its mounts `mount-mid` and
    `mount-inner`). A user reusing `m1` across two of their own packages is
    not doing anything unusual.
    """
    import json

    root = tmp_path_factory.mktemp("repeated-mount-ids")
    (root / "p2").mkdir()
    (root / "p2" / "workflow.json").write_text(json.dumps(_leaf()))
    (root / "p1").mkdir()
    (root / "p1" / "workflow.json").write_text(json.dumps(_mounts_twice("p2")))
    (root / "p0").mkdir()
    (root / "p0" / "workflow.json").write_text(json.dumps(_mounts_twice("p1")))
    return root / "p0"


class TestTwoMountsOfOneNameAtTwoLevels:
    """`the-cost-of-one-more` 10.

    `expand_mounts` spliced each child under the mount node's own name, so two
    levels both calling a mount `m1` produced two `subgraph m1` blocks and
    `draw_mermaid` refused the drawing outright:

        ValueError: Found duplicate subgraph 'm1' -- this likely means that
        you're reusing a subgraph node with the same name.

    Not a missing picture: `api/diagram.py:workflow_mermaid` is the one seam
    the preview, `RunResponse.mermaid`, the terminal SSE `done` frame and
    MCP's `run_workflow` all draw through, so the exception reached a door.

    `GraphNames.absorb` had already settled this for the *other* fold — mount
    slugs are re-keyed by the whole path, because node ids are unique within a
    document and nowhere else. The drawing fold now scopes the same way.
    """

    @pytest.fixture(scope="class")
    def drawn(self, repeated_ids: Path) -> str:
        from openstategraph import load_workflow

        with load_workflow(repeated_ids) as workflow:
            return workflow.mermaid()

    def test_the_composition_can_be_drawn_at_all(self, drawn: str) -> None:
        assert drawn.startswith("---")

    def test_the_top_level_mounts_keep_their_own_names(self, drawn: str) -> None:
        """A composition one level deep is the common case and reads best
        unqualified, so the path of a first-level mount is just its name."""
        assert "subgraph m1\n" in drawn
        assert "subgraph m2\n" in drawn

    def test_a_second_level_mount_is_drawn_under_its_mount_path(
        self, drawn: str
    ) -> None:
        """`m1_m1` is `m1` inside `m1` — unique because a mount path is, and
        readable because it is the path rather than a hash of it."""
        for block in ("m1_m1", "m1_m2", "m2_m1", "m2_m2"):
            assert f"subgraph {block}\n" in drawn

    def test_the_leaf_documents_own_nodes_are_drawn_under_that_path(
        self, drawn: str
    ) -> None:
        assert r"m1\3am1_m2\3af1" in drawn

    def test_no_block_is_drawn_twice(self, drawn: str) -> None:
        """The library's own rule, which is what raised: mermaid subgraph
        names are global to a diagram."""
        blocks = [
            line.strip().split()[1]
            for line in drawn.splitlines()
            if line.strip().startswith("subgraph ")
        ]
        assert len(blocks) == len(set(blocks))

    def test_xray_off_still_draws_one_box_per_mount(
        self, repeated_ids: Path
    ) -> None:
        """The honest picture when a mount is the suspect, and it must stay
        LangGraph's own — no splice, therefore no prefix, therefore nothing
        for this ticket to have changed."""
        from openstategraph import load_workflow

        with load_workflow(repeated_ids) as workflow:
            flat = workflow.mermaid(xray=False)

        assert "subgraph" not in flat
        assert "in1 --> m1;" in flat and "in1 --> m2;" in flat
