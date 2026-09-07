#!/usr/bin/env python3
"""What a grader's step-budget floor costs to derive, at a drawable size.

`the-cost-of-one-more` 01. `step_budget_floor_for` used to walk the plan with
a **per-path** `seen` set, which enumerates every simple path: 55 seconds for
one grader on a 69-node document, growing by the branching factor per layer.
The shape below is that document — a grader whose `pass` branch runs into
alternating fan-out/join layers three wide, every port cardinality respected,
so the editor will let anyone draw it.

`backend/tests/test_the_budget_floor_walk_is_linear.py` is the pin, and it
counts successor lookups because a counter is exact and a clock is not. This
script is the clock, kept because the ticket asks for the price at the map's
own upper bound for a document — 500 nodes — and a test that took a second per
size would be a tax on every run of the suite.

    python3 scripts/measure_step_budget_floor.py

No model is called. Recorded 2026-08-30 on the condensation walk:

    layers=  2 nodes=  13    0.05 ms  floor=8
    layers= 16 nodes=  69    0.19 ms  floor=36
    layers= 32 nodes= 133    0.29 ms  floor=68
    layers= 64 nodes= 261    0.53 ms  floor=132
    layers=124 nodes= 501    1.07 ms  floor=252

Linear, and the branching factor is no longer in the answer's cost.

The old walk answered **34** at sixteen layers where this answers 36, and the
difference is the second half of the defect: `STEP_BUDGET_WALK_CAP` truncated
at depth 32 and returned a floor two supersteps *short* of the tail it was
sizing. A depth cap does not only fail to bound the cost — on the deep
drawings it was supposed to protect, it under-reads the answer.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from openstategraph.compile.workflow_compiler import (  # noqa: E402
    WorkflowCompiler,
    step_budget_floor_for,
)


def wide_tail(layers: int, width: int = 3) -> dict[str, Any]:
    """A grader, a revise loop, and `layers` fan-out/join layers behind `pass`."""
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


def main() -> None:
    print("step_budget_floor_for(grader1) — a drawable width-3 tail, N layers")
    for layers in (2, 4, 6, 8, 10, 12, 14, 16, 32, 64, 124):
        document = wide_tail(layers)
        plan = WorkflowCompiler().plan(document)
        started = time.perf_counter()
        floor = step_budget_floor_for(plan, "grader1")
        elapsed = (time.perf_counter() - started) * 1000
        print(
            f"  layers={layers:3d} nodes={len(document['nodes']):4d} "
            f"edges={len(document['edges']):4d}  {elapsed:8.2f} ms  floor={floor}"
        )
    print("\nsame document, width 8 — the branching factor is not in the cost")
    for layers in (8, 16, 32):
        document = wide_tail(layers, width=8)
        plan = WorkflowCompiler().plan(document)
        started = time.perf_counter()
        floor = step_budget_floor_for(plan, "grader1")
        elapsed = (time.perf_counter() - started) * 1000
        print(
            f"  layers={layers:3d} nodes={len(document['nodes']):4d}  "
            f"{elapsed:8.2f} ms  floor={floor}"
        )


if __name__ == "__main__":
    main()
