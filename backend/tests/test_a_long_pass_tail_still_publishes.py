"""The slack a stopping grader leaves behind is the drawing's, not a constant.

`organisms-first-class` 59, split out of 56.

`56` (`bb8cec4`) stopped a runaway revision loop from raising
`GraphRecursionError` by having the grader read LangGraph's managed
`remaining_steps` and, with barely any left, take its own wired `pass` edge —
so the output node still runs and the caller reads the answer the workflow
produced. The number it compared against was **a constant, 3**, measured on
`evaluator-optimizer`, whose `pass` branch crosses exactly one node.

**What a constant cannot know is how far `pass` still has to travel.** A
grader wired to a formatter, then a guardrail, then an output has three
supersteps of tail, and the run raised again — the exact exception `56`
exists to remove. Measured here before it was fixed: the same package, the
same scripted grader, the same `recursion_limit=10`, with two nodes spliced
into the `pass` branch, raised `GraphRecursionError` out of `ask()`.

**And the revise side is exposed too, for a different reason.** A grader can
only look at the budget once per lap. If the lap is longer than the slack it
just approved, the budget runs out *between* two looks and the run dies part
way round, having never been offered the chance to stop. So the floor is not
"what the tail costs" but "what one more lap costs, and then the tail" —
which, on `evaluator-optimizer`, is 2 + 1 and reproduces the constant `56`
measured. That is the argument for computing it: the derivation agrees with
the measurement on the shape the measurement was taken on.

No live model run was possible — this environment has no provider credential
— so every observation is a scripted model through a real `WorkflowCompiler`
graph, as `56`'s were.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel
from openstategraph.loader import load_workflow

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"

BUDGET_SENTENCE = "step budget"
ATTEMPTS_SENTENCE = "ran out of attempts"


class _NeverRelents(RespondingModel):
    """The only model shape that can actually exhaust a step budget."""

    def __init__(self) -> None:
        super().__init__(rules=[])
        object.__setattr__(self, "graded", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        context = "\n".join(str(m.content) for m in messages)
        if "You are a grader" not in context:
            return self._reply("a draft of the answer")
        object.__setattr__(self, "graded", self.graded + 1)
        return self._reply("FAIL\nstill not good enough")


def _long_tail(tmp_path: Path) -> Path:
    """`evaluator-optimizer` with two deterministic nodes spliced into the
    `pass` branch, so the tail is three supersteps instead of one.

    Both are model-free on purpose: the defect is arithmetic about
    supersteps, and a node that calls the scripted model would add a second
    reason for the numbers to move.
    """
    destination = tmp_path / "long-tail"
    shutil.copytree(EXAMPLES / "evaluator-optimizer", destination)
    payload = json.loads((destination / "workflow.json").read_text())
    document = payload["document"]
    for node in document["nodes"]:
        if node["id"] == "grader1":
            node["data"]["maxAttempts"] = 500
    document["nodes"].append(
        {"id": "fmt1", "type": "function.format_report",
         "position": {"x": 900, "y": 0}, "data": {}}
    )
    document["nodes"].append(
        {"id": "guard1", "type": "guard.policy",
         "position": {"x": 1100, "y": 0}, "data": {}}
    )
    document["edges"] = [
        edge for edge in document["edges"]
        if not (edge["source"]["nodeId"] == "grader1"
                and edge["source"]["portId"] == "pass")
    ] + [
        {"source": {"nodeId": "grader1", "portId": "pass"},
         "target": {"nodeId": "fmt1", "portId": "candidate"}},
        {"source": {"nodeId": "fmt1", "portId": "report"},
         "target": {"nodeId": "guard1", "portId": "content"}},
        {"source": {"nodeId": "guard1", "portId": "allowed"},
         "target": {"nodeId": "out1", "portId": "result"}},
    ]
    (destination / "workflow.json").write_text(json.dumps(payload))
    return destination


def _long_lap(tmp_path: Path) -> Path:
    """The other exposure: a long `revise` path, one-node tail.

    The grader looks at the budget once per lap. Two nodes spliced between
    `revise` and the drafter make a lap cost four supersteps, so a floor
    sized for a two-superstep lap approves a lap the budget cannot pay for
    and the run dies before the grader is asked again.
    """
    destination = tmp_path / "long-lap"
    shutil.copytree(EXAMPLES / "evaluator-optimizer", destination)
    payload = json.loads((destination / "workflow.json").read_text())
    document = payload["document"]
    for node in document["nodes"]:
        if node["id"] == "grader1":
            node["data"]["maxAttempts"] = 500
    document["nodes"].append(
        {"id": "relay1", "type": "function.format_report",
         "position": {"x": 300, "y": 300}, "data": {}}
    )
    document["nodes"].append(
        {"id": "relay2", "type": "memory.segment",
         "position": {"x": 500, "y": 300}, "data": {}}
    )
    document["edges"] = [
        edge for edge in document["edges"]
        if not (edge["source"]["nodeId"] == "grader1"
                and edge["source"]["portId"] == "revise")
    ] + [
        {"source": {"nodeId": "grader1", "portId": "revise"},
         "target": {"nodeId": "relay1", "portId": "candidate"}},
        {"source": {"nodeId": "relay1", "portId": "report"},
         "target": {"nodeId": "relay2", "portId": "crossing"}},
        {"source": {"nodeId": "relay2", "portId": "onward"},
         "target": {"nodeId": "draft1", "portId": "feedback"}},
    ]
    (destination / "workflow.json").write_text(json.dumps(payload))
    return destination


def _one_node_tail(tmp_path: Path) -> Path:
    """`evaluator-optimizer` exactly as `56` measured it."""
    destination = tmp_path / "short-tail"
    shutil.copytree(EXAMPLES / "evaluator-optimizer", destination)
    payload = json.loads((destination / "workflow.json").read_text())
    for node in payload["document"]["nodes"]:
        if node["id"] == "grader1":
            node["data"]["maxAttempts"] = 500
    (destination / "workflow.json").write_text(json.dumps(payload))
    return destination


def _budget_lines(result: Any) -> list[str]:
    return [w for w in (result.warnings or []) if BUDGET_SENTENCE in w]


class TestALongPassTailPublishesInsteadOfRaising:
    """The defect, at the layer a caller stands on."""

    @pytest.fixture(scope="class")
    def run(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        package = _long_tail(tmp_path_factory.mktemp("longtail"))
        model = _NeverRelents()
        workflow = load_workflow(package, model=model)
        return workflow.ask("Describe the export fix.", recursion_limit=10), model

    def test_no_recursion_error_escapes(self, run: Any) -> None:
        """Before this, `ask()` raised and the caller got nothing at all."""
        assert str(run[0]).strip()

    def test_the_whole_tail_actually_ran(self, run: Any) -> None:
        """A stop that skipped the tail would publish, and publish the wrong
        thing. Both spliced nodes must have produced an output."""
        outputs = run[0].outputs
        assert "fmt1" in outputs and "guard1" in outputs, outputs

    def test_the_run_says_the_step_budget_stopped_it(self, run: Any) -> None:
        lines = _budget_lines(run[0])
        assert len(lines) == 1, run[0].warnings
        assert "grader1" in lines[0]

    def test_it_is_a_report_and_not_a_failure(self, run: Any) -> None:
        assert run[0].failures == []

    def test_it_is_not_dressed_as_an_attempt_cap(self, run: Any) -> None:
        assert [w for w in (run[0].warnings or []) if ATTEMPTS_SENTENCE in w] == []


class TestALongReviseLapPublishesToo:
    """The exposure the ticket asked to be checked rather than assumed."""

    @pytest.fixture(scope="class")
    def run(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        package = _long_lap(tmp_path_factory.mktemp("longlap"))
        model = _NeverRelents()
        workflow = load_workflow(package, model=model)
        return workflow.ask("Describe the export fix.", recursion_limit=10), model

    def test_no_recursion_error_escapes(self, run: Any) -> None:
        assert str(run[0]).strip()

    def test_the_run_says_the_step_budget_stopped_it(self, run: Any) -> None:
        assert len(_budget_lines(run[0])) == 1, run[0].warnings

    def test_it_laps_at_least_once(self, run: Any) -> None:
        """A floor so generous it stops before revising anything would pass
        every test above and destroy the feature."""
        assert run[1].graded >= 2


class TestTheOneNodeTailIsUnchanged:
    """`56`'s measurement is the calibration, and the derived floor must
    reproduce it: one more lap (2) plus the tail (1) is the constant 3."""

    @pytest.fixture(scope="class")
    def run(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        package = _one_node_tail(tmp_path_factory.mktemp("shorttail"))
        model = _NeverRelents()
        workflow = load_workflow(package, model=model)
        return workflow.ask("Describe the export fix.", recursion_limit=10), model

    def test_it_still_publishes(self, run: Any) -> None:
        assert "a draft of the answer" in str(run[0])

    def test_it_grades_exactly_as_many_times_as_before(self, run: Any) -> None:
        """`56` measured three gradings at `recursion_limit=10`. A floor that
        moved for this drawing would stop the loop earlier, which is the
        regression this change risks."""
        assert run[1].graded == 3

    def test_the_sentence_still_names_the_remaining_supersteps(self, run: Any) -> None:
        line = _budget_lines(run[0])[0]
        assert "3 supersteps left" in line, line


class TestTheFloorIsDerivedFromTheDrawing:
    """The unit beneath all of the above, so a regression names itself."""

    def _plan(self, package: Path) -> Any:
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        payload = json.loads((package / "workflow.json").read_text())
        return WorkflowCompiler().plan(payload["document"])

    def test_a_one_node_tail_is_the_measured_constant(
        self, tmp_path: Path
    ) -> None:
        from openstategraph.compile.workflow_compiler import step_budget_floor_for
        from openstategraph.compile.state import STEP_BUDGET_FLOOR

        plan = self._plan(_one_node_tail(tmp_path))
        assert step_budget_floor_for(plan, "grader1") == STEP_BUDGET_FLOOR == 3

    def test_a_three_node_tail_costs_two_more(self, tmp_path: Path) -> None:
        from openstategraph.compile.workflow_compiler import step_budget_floor_for

        plan = self._plan(_long_tail(tmp_path))
        assert step_budget_floor_for(plan, "grader1") == 5

    def test_a_four_superstep_lap_costs_two_more(self, tmp_path: Path) -> None:
        from openstategraph.compile.workflow_compiler import step_budget_floor_for

        plan = self._plan(_long_lap(tmp_path))
        assert step_budget_floor_for(plan, "grader1") == 5

    def test_a_node_that_is_not_a_grader_gets_the_constant(
        self, tmp_path: Path
    ) -> None:
        """Nothing drawn, nothing to derive — the floor `56` measured is the
        fallback, never an unbounded number."""
        from openstategraph.compile.workflow_compiler import step_budget_floor_for
        from openstategraph.compile.state import STEP_BUDGET_FLOOR

        plan = self._plan(_one_node_tail(tmp_path))
        assert step_budget_floor_for(plan, "draft1") == STEP_BUDGET_FLOOR

    def test_a_mount_in_the_tail_costs_one_superstep(self, tmp_path: Path) -> None:
        """The other exposure the ticket asked to be checked rather than
        assumed. A mount is a **closure** in the parent graph, and the child
        is a separate `invoke` with its own step counter — measured: shipped
        `nested-mounts` runs its three parent nodes at `recursion_limit=4`
        while the child mounts a third document. So it costs the parent one
        superstep like any other node, and the walk needs no special case."""
        from openstategraph.compile.workflow_compiler import step_budget_floor_for

        package = _one_node_tail(tmp_path)
        payload = json.loads((package / "workflow.json").read_text())
        document = payload["document"]
        document["nodes"].append(
            {"id": "mount1", "type": "workflow.subgraph",
             "position": {"x": 900, "y": 0},
             "data": {"workflow": "nested-mounts-mid"}}
        )
        document["edges"] = [
            edge for edge in document["edges"]
            if not (edge["source"]["nodeId"] == "grader1"
                    and edge["source"]["portId"] == "pass")
        ] + [
            {"source": {"nodeId": "grader1", "portId": "pass"},
             "target": {"nodeId": "mount1", "portId": "input"}},
            {"source": {"nodeId": "mount1", "portId": "result"},
             "target": {"nodeId": "out1", "portId": "result"}},
        ]
        (package / "workflow.json").write_text(json.dumps(payload))
        assert step_budget_floor_for(self._plan(package), "grader1") == 4

    def test_a_cycle_in_the_tail_stays_bounded(self, tmp_path: Path) -> None:
        """A `pass` branch that loops back makes "longest path" unbounded.

        The bound used to be `STEP_BUDGET_WALK_CAP`, a fixed depth, and it did
        not bound the *cost* of finding the answer at all
        (`the-cost-of-one-more` 01). The walk condenses the graph now, so the
        bound is the drawing's own size: a lap and a tail can each visit every
        node once and no more.
        """
        from openstategraph.compile.workflow_compiler import step_budget_floor_for

        package = _one_node_tail(tmp_path)
        payload = json.loads((package / "workflow.json").read_text())
        document = payload["document"]
        document["edges"].append(
            {"source": {"nodeId": "grader1", "portId": "pass"},
             "target": {"nodeId": "draft1", "portId": "feedback"}}
        )
        (package / "workflow.json").write_text(json.dumps(payload))
        plan = self._plan(package)
        floor = step_budget_floor_for(plan, "grader1")
        assert 3 <= floor <= 2 * len(plan.nodes)
