#!/usr/bin/env python3
"""Time the per-request setup path of one package: plan, tool import, skill
read, build. No model, no network, no spend.

`launch-readiness/113` asked whether this path is the cost behind `109`. The
answer is in `docs/decisions/per-request-compile-cost.md`; this is the
instrument that produced it, committed so the next person re-measures instead
of re-arguing.

    python3 scripts/measure_setup_path.py backend/openstategraph/examples/guarded-lookup
    python3 scripts/measure_setup_path.py workflows/chinook-assistant

Read the **warm** passes, not the first one. A live server has already paid
for the lazy imports that make pass 1 two to three times the rest, and the
question this answers is what a *request* costs, not what a process start does.

The model is a stub that raises if anything calls it, so a number that came
out of here cannot have a model call hiding in it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PASSES = 4


class _NeverCalledModel:
    def bind_tools(self, *_a: Any, **_k: Any) -> "_NeverCalledModel":
        return self

    def with_structured_output(self, *_a: Any, **_k: Any) -> "_NeverCalledModel":
        return self

    def with_config(self, *_a: Any, **_k: Any) -> "_NeverCalledModel":
        return self

    def invoke(self, *_a: Any, **_k: Any) -> Any:
        raise SystemExit("a model was called: this measurement is not clean")


def _count(directory: Path, pattern: str) -> int:
    return len(list(directory.glob(pattern))) if directory.is_dir() else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="a workflow package directory")
    parser.add_argument("--passes", type=int, default=PASSES)
    args = parser.parse_args(argv)

    package = args.package.expanduser().resolve()
    root = package.parent
    os.environ["OPENSTATEGRAPH_WORKFLOWS_ROOT"] = str(root)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

    started = time.perf_counter()
    from openstategraph.api.capability_discovery import discover_skills
    from openstategraph.api.services import WorkflowServices
    from openstategraph.compile.node_runtime import RunState
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    imports = time.perf_counter() - started

    raw = json.loads((package / "workflow.json").read_text())
    document = raw.get("document", raw)
    services = WorkflowServices(root)

    print(f"package                  {package}")
    print(f"  nodes                  {len(document.get('nodes') or [])}")
    print(f"  tools/*.py             {_count(package / 'tools', '*.py')}")
    print(
        f"  skills/*.md            {_count(package / 'skills', '*.md')} "
        f"({len(discover_skills(package))} bytes of context)"
    )
    print(
        f"  module import          {imports * 1000:8.1f} ms  (once per process, not per request)"
    )
    print()

    totals: list[float] = []
    for index in range(args.passes):
        t0 = time.perf_counter()
        compiler = WorkflowCompiler()
        compiler.plan(document)
        t1 = time.perf_counter()
        runtime = services.runtime_for(
            package.name, document, _NeverCalledModel(), warnings=[]
        )
        t2 = time.perf_counter()
        compiler.build(document, RunState, runtime.factory(document))
        t3 = time.perf_counter()
        totals.append(t3 - t0)
        label = "pass 1 (cold)" if index == 0 else f"pass {index + 1}"
        print(
            f"  {label:<14} plan {(t1 - t0) * 1000:6.1f}   "
            f"tools+skills {(t2 - t1) * 1000:6.1f}   "
            f"build {(t3 - t2) * 1000:6.1f}   "
            f"TOTAL {(t3 - t0) * 1000:7.1f} ms"
        )

    warm = totals[1:] or totals
    print()
    print(
        f"  warm setup cost        {sum(warm) / len(warm) * 1000:8.1f} ms  (mean of {len(warm)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
