"""How many compiles a composition costs — the ladder from `the-cost-of-one-more` 02.

`p0` mounts `p1` **twice**, `p1` mounts `p2` twice, down to a leaf that mounts
nothing. Real packages on disk, compiled by the real loader, with
`WorkflowCompiler.build` counted. No model is called and no network is
touched: the leaf's agent is never invoked, only compiled.

The mount graph is a DAG rather than a tree, so resolving a mount per **site**
cost `2^(d+1) - 1` builds — 255 for eight packages on disk, with the wall clock
doubling for every package a user wrote. The axis was not document size. It was
*how many packages a user has written*, which is the thing this product spends
its documentation encouraging.

Resolving a mount per **instance** — `(slug, overrides, persistence)`, memoised
on the parent runtime for the length of one compile — costs one build per
package. The ladder below is the difference, and it is committed rather than
described so the next person re-measures instead of re-arguing.

    python3 scripts/measure_mount_depth.py [max-depth]
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openstategraph import loader  # noqa: E402
from openstategraph.compile import workflow_compiler as compiler  # noqa: E402

CALLS = {"build": 0}
_original = compiler.WorkflowCompiler.build


def _counting(self: Any, *a: Any, **k: Any) -> Any:
    CALLS["build"] += 1
    return _original(self, *a, **k)


compiler.WorkflowCompiler.build = _counting  # type: ignore[method-assign]


def leaf() -> dict[str, Any]:
    return {
        "version": 3,
        "name": "leaf",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "a1", "type": "agent.llm", "position": {"x": 1, "y": 0}, "data": {}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 2, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "a1", "portId": "prompt"}},
            {"source": {"nodeId": "a1", "portId": "result"},
             "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


def parent(child_slug: str) -> dict[str, Any]:
    """One document mounting `child_slug` twice and joining the two answers."""
    return {
        "version": 3,
        "name": "p",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "m1", "type": "workflow.subgraph", "position": {"x": 1, "y": 0},
             "data": {"workflow": child_slug}},
            {"id": "m2", "type": "workflow.subgraph", "position": {"x": 1, "y": 1},
             "data": {"workflow": child_slug}},
            {"id": "j1", "type": "function.format_report",
             "position": {"x": 2, "y": 0}, "data": {}},
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


def ladder(root: Path, depth: int) -> Path:
    (root / f"p{depth}").mkdir(parents=True)
    (root / f"p{depth}" / "workflow.json").write_text(json.dumps(leaf()))
    for level in range(depth - 1, -1, -1):
        (root / f"p{level}").mkdir()
        (root / f"p{level}" / "workflow.json").write_text(json.dumps(parent(f"p{level + 1}")))
    return root / "p0"


def main() -> None:
    deepest = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    print("mount compilation — each package mounts the next TWICE")
    print("  depth  packages  builds   2^(d+1)-1        ms")
    for depth in range(1, deepest + 1):
        root = Path(tempfile.mkdtemp(prefix="osg-mount-depth-"))
        try:
            package = ladder(root, depth)
            CALLS["build"] = 0
            started = time.perf_counter()
            loader.load_workflow(str(package))
            elapsed = (time.perf_counter() - started) * 1000
            print(f"  {depth:5d}  {depth + 1:8d}  {CALLS['build']:6d}  {2 ** (depth + 1) - 1:10d}"
                  f"  {elapsed:8.1f}")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
