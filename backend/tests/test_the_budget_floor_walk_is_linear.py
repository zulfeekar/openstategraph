"""One grader, sixty-nine nodes, fifty-five seconds.

`the-cost-of-one-more` 01. `step_budget_floor_for` derived a grader's
step-budget floor from two walks that carried a **per-path** `seen` set, so
the same node was re-expanded once per distinct path prefix reaching it: an
enumeration of every simple path. `STEP_BUDGET_WALK_CAP` capped a path's
*length*, never their *number*, and a depth cap does not bound a path
enumeration — so the docstring's *"the walk is capped rather than solved"*
described a bound that did not exist.

Measured through the real compiler on a document the editor will let anyone
draw (every port cardinality respected — an agent's `prompt` takes one link, a
`function.format_report`'s `in` is a bus, an out-port fans freely), a grader
whose `pass` branch runs into alternating fan-out/join layers three wide:

    nodes= 13   0.03 ms      nodes= 45   126.90 ms
    nodes= 21   0.15 ms      nodes= 53  1149.12 ms
    nodes= 29   1.33 ms      nodes= 61 10472.23 ms
    nodes= 37  13.06 ms      nodes= 69 54931.76 ms

×9.4 per two layers is ×3 per layer — the branching factor, exactly as path
enumeration predicts. `plan()` runs on `validate`, on every run, on the
editor's preview endpoint and once per mount site, with no timeout around it,
so this was a compile-time hang reachable from any document a caller can POST.

**The pin is a counter, not a clock**, following
`src/core/validation/acyclicGraphRule.scaling.test.ts`: the walk asks each
reachable node for its successors **exactly once**, which is exact and cannot
be flaky. A wall-clock assertion at these sizes would have to be loose enough
to pass on a slow machine and would then pass on a ×3-per-layer walk at small
n as well.

The clock lives in `scripts/measure_step_budget_floor.py`, where a 500-node
document is priced against the shape above.
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping

import pytest

from openstategraph.compile import workflow_compiler
from openstategraph.compile.workflow_compiler import (
    WorkflowCompiler,
    step_budget_floor_for,
)


def _wide_tail(layers: int, width: int = 3) -> dict[str, Any]:
    """A grader whose `pass` branch runs into `layers` fan-out/join layers.

    Every port cardinality is respected, so this is a drawing the editor
    accepts: `agent.llm`'s `prompt` takes exactly one link,
    `function.format_report`'s `in` is a bus, and an out-port fans freely.
    """
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "draft1", "type": "agent.llm", "position": {"x": 1, "y": 0}, "data": {}},
        {"id": "grader1", "type": "route.grader", "position": {"x": 2, "y": 0}, "data": {}},
        {"id": "out1", "type": "output.formatted", "position": {"x": 3, "y": 0}, "data": {}},
        {"id": "j0", "type": "function.format_report", "position": {"x": 4, "y": 0}, "data": {}},
    ]
    edges: list[dict[str, Any]] = [
        {"source": {"nodeId": "in1", "portId": "text"},
         "target": {"nodeId": "draft1", "portId": "prompt"}},
        {"source": {"nodeId": "draft1", "portId": "result"},
         "target": {"nodeId": "grader1", "portId": "candidate"}},
        {"source": {"nodeId": "grader1", "portId": "revise"},
         "target": {"nodeId": "draft1", "portId": "feedback"}},
        {"source": {"nodeId": "grader1", "portId": "pass"},
         "target": {"nodeId": "j0", "portId": "in"}},
    ]
    previous = "j0"
    for layer in range(layers):
        join = f"j{layer + 1}"
        nodes.append({"id": join, "type": "function.format_report",
                      "position": {"x": 5 + layer, "y": 0}, "data": {}})
        for lane in range(width):
            worker = f"a{layer}_{lane}"
            nodes.append({"id": worker, "type": "agent.llm",
                          "position": {"x": 5 + layer, "y": lane}, "data": {}})
            edges.append({"source": {"nodeId": previous, "portId": "result"},
                          "target": {"nodeId": worker, "portId": "prompt"}})
            edges.append({"source": {"nodeId": worker, "portId": "result"},
                          "target": {"nodeId": join, "portId": "in"}})
        previous = join
    edges.append({"source": {"nodeId": previous, "portId": "result"},
                  "target": {"nodeId": "out1", "portId": "result"}})
    return {"version": 3, "name": "wide tail", "nodes": nodes, "edges": edges}


class _CountingDestinations(Mapping[str, list[str]]):
    """`_plan_destinations`' answer, counting who is asked and how often."""

    def __init__(self, onward: Mapping[str, list[str]]) -> None:
        self._onward = onward
        self.asked: dict[str, int] = {}

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        self.asked[key] = self.asked.get(key, 0) + 1
        return self._onward.get(key, default)

    def __getitem__(self, key: str) -> list[str]:
        self.asked[key] = self.asked.get(key, 0) + 1
        return self._onward[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._onward)

    def __len__(self) -> int:
        return len(self._onward)


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Runs `step_budget_floor_for` and hands back what the walk asked for."""
    boxes: list[_CountingDestinations] = []
    real = workflow_compiler._plan_destinations

    def counting(plan: Any) -> Any:
        box = _CountingDestinations(real(plan))
        boxes.append(box)
        return box

    monkeypatch.setattr(workflow_compiler, "_plan_destinations", counting)

    def run(layers: int) -> tuple[int, dict[str, int], int]:
        document = _wide_tail(layers)
        plan = WorkflowCompiler().plan(document)
        boxes.clear()
        floor = step_budget_floor_for(plan, "grader1")
        assert len(boxes) == 1, "one destination map per floor, not one per walk"
        return floor, boxes[0].asked, len(document["nodes"])

    return run


class TestTheWalkAsksEachNodeOnce:
    """The complexity pin. A per-path `seen` fails this by orders of magnitude."""

    def test_no_node_is_asked_more_than_once_per_walk(self, counted: Any) -> None:
        """Two walks — the revise lap and the `pass` tail — so twice at most.

        Before the fix, `j0` on a twelve-layer tail is asked 3^12 times.
        """
        _, asked, _ = counted(12)
        worst = max(asked.items(), key=lambda pair: pair[1])
        assert worst[1] <= 2, f"{worst[0]} asked {worst[1]} times"

    def test_the_total_is_linear_in_the_document(self, counted: Any) -> None:
        _, asked, nodes = counted(12)
        assert sum(asked.values()) <= 2 * nodes

    def test_doubling_the_tail_does_not_multiply_the_work(self, counted: Any) -> None:
        """The class assertion: ×3 per layer against ×2 per doubling."""
        _, small, _ = counted(6)
        _, large, _ = counted(12)
        assert sum(large.values()) <= 3 * sum(small.values())


class TestTheFloorItselfIsUnchanged:
    """A faster wrong number is worse than a slow right one."""

    def test_a_wide_tail_still_counts_its_depth(self, counted: Any) -> None:
        """One lap (2) plus the tail: `j0`, then `layers` × (worker, join),
        then `out1`. Six layers is 2 + (1 + 12 + 1) = 16."""
        floor, _, _ = counted(6)
        assert floor == 16
