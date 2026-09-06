"""A package this repository ships must bind every tool type it draws.

`every-workflow-green/43`. A live run of `chinook-assistant` was refused by its
own grader: *"`agent-sql` was wired 3 capabilities and not one of them was
available"*. All three were `tool.chinook-*`, all three are declared by the
package's own `tools/chinook.py`, and `GET /api/workflows/chinook-assistant/
capabilities` listed all three correctly. The binding failed anyway.

**Why nothing in this suite could see it.** `pytest.ini` puts
`workflows/chinook-assistant` on `pythonpath`, and the built-in tool layer
reached the shipped tools by `from tools.chinook import ...` — a bare top-level
`tools` package that exists on `sys.path` **only under pytest**. Every process
that actually serves a run — the API server, the CLI, an installed wheel — got
`ModuleNotFoundError: No module named 'tools'`, swallowed at DEBUG level. The
suite was therefore measuring a registry no shipped process has, which is why
the run failed in silence with a green test suite behind it.

So both checks here run in a **clean interpreter**: a subprocess whose only
path entry is `backend/`, exactly what a server process has. Running them
in-process would restore the very illusion the ticket is about.

Both are derived, never hand-listed. The packages come from `workflows_root()`,
the declared types come from each package's own document, and the built-in
layer's expectation comes from what the shipped package's `tools/` declares —
so a fourth Chinook tool, or a tenth package, is covered by existing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Run in the subprocess. Prints one JSON object on stdout: what the built-in
#: layer publishes for Chinook, what the shipped package declares, and, per
#: shipped package, which of its drawn tool types the registry cannot resolve.
_PROBE = r"""
import json
from pathlib import Path

from openstategraph.api.capability_discovery import discover_tool_registry
from openstategraph.api.registries import build_tool_registry
from openstategraph.api.workflow_store import WorkflowStore
from openstategraph.compile.runtime_services import CHINOOK_SLUG, chinook_tool_registry
from openstategraph.workflows_root import workflows_root

root = workflows_root()
store = WorkflowStore()

report = {"root": str(root), "packages": {}}

try:
    report["builtin_chinook"] = sorted(chinook_tool_registry())
except Exception as exc:  # reported, never raised: the assertion is the caller's
    report["builtin_chinook"] = None
    report["builtin_error"] = f"{type(exc).__name__}: {exc}"

chinook_dir = root / CHINOOK_SLUG
report["chinook_declares"] = (
    sorted(k for k in discover_tool_registry(chinook_dir, CHINOOK_SLUG) if k.startswith("tool."))
    if (chinook_dir / "workflow.json").is_file()
    else []
)

report["default_layer"] = sorted(build_tool_registry(store, None))

for package in sorted(p for p in root.iterdir() if (p / "workflow.json").is_file()):
    document = json.loads((package / "workflow.json").read_text(encoding="utf-8"))
    document = document.get("document", document)
    drawn = sorted(
        {
            str(node.get("type", ""))
            for node in document.get("nodes", [])
            if str(node.get("type", "")).startswith("tool.")
        }
    )
    registry = build_tool_registry(store, package.name)
    report["packages"][package.name] = {
        "drawn": drawn,
        "unresolved": [t for t in drawn if t not in registry],
    }

print(json.dumps(report))
"""


@pytest.fixture(scope="module")
def clean_process_report() -> dict:
    """What binding sees in a process that is not this one.

    The environment is built rather than inherited: `PYTHONPATH` carries
    `backend/` alone, and `OPENSTATEGRAPH_WORKFLOWS_ROOT` is dropped so the
    checkout answers where the packages are — the same resolution `./start dev`
    gets, and not whatever the machine running the suite happens to export.
    """
    env = {k: v for k, v in os.environ.items() if k != "OPENSTATEGRAPH_WORKFLOWS_ROOT"}
    env["PYTHONPATH"] = str(REPO_ROOT / "backend")
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        f"The probe itself failed in a clean process:\n{completed.stderr[-4000:]}"
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


class TestTheBuiltInLayerCarriesTheShippedChinookTools:
    """The default layer is what a run with no `workflow_slug` gets.

    `/api/runs` accepts a document with no slug on purpose — its own 404 copy
    says *"Omit `workflow_slug` to run the document with the default tools"* —
    and `build_tool_registry` publishes the Chinook trio there deliberately, so
    a document that binds them works from any workflow context, mounted or not.
    A layer that publishes nothing outside pytest is not that promise.
    """

    def test_it_publishes_what_the_package_declares(self, clean_process_report: dict) -> None:
        published = clean_process_report["builtin_chinook"]
        assert published is not None, (
            "The built-in Chinook layer raised in a clean process: "
            f"{clean_process_report.get('builtin_error')}. It resolves only under "
            "pytest, so no server process has ever had these tools."
        )
        assert published == clean_process_report["chinook_declares"]

    def test_the_default_layer_resolves_them(self, clean_process_report: dict) -> None:
        missing = [
            node_type
            for node_type in clean_process_report["chinook_declares"]
            if node_type not in clean_process_report["default_layer"]
        ]
        assert not missing, (
            f"A run carrying no workflow_slug cannot bind {missing} — the shipped "
            "package declares them and the default layer does not carry them."
        )


class TestEveryShippedPackageBindsTheToolsItDraws:
    """Derived over `workflows_root()`: every drawn `tool.*` type resolves.

    Scoped by slug, which is what a run naming its workflow gets. A package
    drawing a type nothing can bind reaches its grader having answered from
    nothing — the failure this ticket was filed for, one layer up.
    """

    def test_no_shipped_package_draws_an_unbindable_tool(
        self, clean_process_report: dict
    ) -> None:
        packages = clean_process_report["packages"]
        assert packages, f"No packages found under {clean_process_report['root']}"
        unresolved = {
            slug: report["unresolved"] for slug, report in packages.items() if report["unresolved"]
        }
        assert not unresolved, (
            "Shipped packages draw tool types that binding cannot resolve on this "
            f"checkout: {unresolved}"
        )
