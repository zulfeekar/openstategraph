#!/usr/bin/env python3
"""Run the stress-test workload packages and report defects.

These packages were found to expose real defects in launch-readiness tickets
174-178. This script runs them against a live model and reports the outcomes.

Spend alert: This runs several workflows against a real model and will use
compute credits. Each run is a few seconds and a few model calls.

Environment:
  - Set OPENSTATEGRAPH_MODEL to override (defaults to ollama:gpt-oss:120b-cloud)
  - Reads .env from cwd, then from each package
  - Pops OLLAMA_HOST and OLLAMA_ENDPOINT to force cloud model

Usage:
    python3 scripts/run_stress_workload.py

    python3 scripts/run_stress_workload.py --package stress-review
    python3 scripts/run_stress_workload.py --packages stress-review stress-deep
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
STRESS_DIR = BACKEND / "tests" / "workflows" / "stress"


def _prepare_environment(packages_root: Path) -> None:
    """The three fixes without which every live run fails silently.

    See CLAUDE.md: live-run env.
    """
    sys.path.insert(0, str(BACKEND))
    from openstategraph.dotenv import load_env_file

    load_env_file(Path.cwd())
    # A daemon on this machine must not be able to answer for the cloud.
    os.environ.pop("OLLAMA_HOST", None)
    os.environ.pop("OLLAMA_ENDPOINT", None)
    # Default model if not set
    if "OPENSTATEGRAPH_MODEL" not in os.environ:
        os.environ["OPENSTATEGRAPH_MODEL"] = "ollama:gpt-oss:120b-cloud"
    os.environ["OPENSTATEGRAPH_WORKFLOWS_ROOT"] = str(packages_root)


async def run_package(
    package_name: str, package_path: Path, model: str, question: str | None = None
) -> dict[str, Any]:
    """Run one stress package and return the result.

    Returns a dict with keys:
      - name: package name
      - success: True if run completed (may still have warnings)
      - warnings: list of warnings from the run
      - answer: the answer (if any)
      - error: error message (if any)
      - duration_s: wall-clock seconds
    """
    import time

    from openstategraph.load import load_workflow
    from openstategraph.runtime import WorkflowRunner

    start = time.monotonic()
    result: dict[str, Any] = {
        "name": package_name,
        "success": False,
        "warnings": [],
        "answer": None,
        "error": None,
        "duration_s": 0.0,
    }

    try:
        workflow = load_workflow(package_path)
        result["warnings"] = [str(w) for w in workflow.warnings]

        if not workflow.is_valid:
            result["error"] = "Workflow validation failed"
            result["success"] = False
            return result

        # Prepare a question if not provided
        if question is None:
            question = (
                "Summarize the key points. If you cannot produce output, "
                "explain what information is needed."
            )

        # Run the workflow
        runner = WorkflowRunner(workflow.compiled, model=model)
        run_result = await runner.ainvoke({"input": question})

        result["answer"] = run_result.get("answer")
        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        result["success"] = False
    finally:
        result["duration_s"] = time.monotonic() - start

    return result


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        help="Run only one package (repeatable)",
        action="append",
        dest="packages",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENSTATEGRAPH_MODEL", "ollama:gpt-oss:120b-cloud"),
        help="Model to use (default: $OPENSTATEGRAPH_MODEL or ollama:gpt-oss:120b-cloud)",
    )
    parser.add_argument(
        "--question",
        help="Question to ask each package",
        default=None,
    )
    args = parser.parse_args(argv)

    # Setup environment
    _prepare_environment(STRESS_DIR.parent.parent)

    # Find packages to run
    if args.packages:
        to_run = [
            (name, STRESS_DIR / name) for name in args.packages if (STRESS_DIR / name).exists()
        ]
    else:
        to_run = sorted(
            (p.name, p) for p in STRESS_DIR.iterdir() if p.is_dir() and (p / "workflow.json").exists()
        )

    if not to_run:
        print("No packages found in", STRESS_DIR)
        return 1

    print(f"\nRunning {len(to_run)} stress packages with model: {args.model}\n")
    print(f"{'Package':<25} {'Status':<12} {'Duration':<12} {'Notes'}")
    print("-" * 80)

    results: list[dict[str, Any]] = []
    for package_name, package_path in to_run:
        try:
            result = await run_package(package_name, package_path, args.model, args.question)
            results.append(result)

            status = "✓ OK" if result["success"] else "✗ FAIL"
            notes = ""
            if result["warnings"]:
                notes = f"{len(result['warnings'])} warning(s)"
            if result["error"]:
                notes = result["error"][:40]

            print(
                f"{package_name:<25} {status:<12} {result['duration_s']:<12.2f}s {notes}"
            )
        except KeyboardInterrupt:
            print(f"\n{package_name:<25} {'INTERRUPTED':<12}")
            return 130
        except Exception as e:
            print(f"{package_name:<25} {'ERROR':<12} {str(e)[:40]}")
            results.append({"name": package_name, "error": str(e)})

    # Summary
    print("\n" + "=" * 80)
    passed = sum(1 for r in results if r.get("success"))
    failed = sum(1 for r in results if not r.get("success"))

    print(f"\nResults: {passed} passed, {failed} failed")

    if failed > 0:
        print("\nFailed packages:")
        for r in results:
            if not r.get("success"):
                error = r.get("error", "Unknown error")
                print(f"  - {r['name']}: {error}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
