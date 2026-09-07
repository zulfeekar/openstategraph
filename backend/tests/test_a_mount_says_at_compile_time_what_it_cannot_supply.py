"""A mount that can never supply its child's required key says so at compile
time — `organisms-first-class/79`.

Since `32ddc43` a mounted child is invoked with the run's values **narrowed to
its own declaration**: a key crosses a mount only when both documents declare
it. That rule has a consequence which is a fact about two documents, both on
disk, and which was said only when a run reached the mount:

    error: Node "m1" failed and produced no result. Workflow 'child79'
    requires run context that this run supplied none of: caseId.

Measured before anything was written, on a two-package composition — a child
declaring `caseId` required with no default, mounted by a parent declaring only
`tenant`:

| surface | before |
| --- | --- |
| compile | silent |
| `openstategraph validate` | `VALID`, exit **0** |
| `openstategraph run` | dies at the mount, every time, with the sentence above |

Nothing about that composition can change at run time: no value of `--context`
reaches `caseId`, because the parent does not declare it and 76's rule is what
it is. So the honest place to say it is the compile, which is where every other
*this mount can never work* fact is already said — `UNRESOLVED_SUBGRAPH`, the
mount cycle, the unenforced outcome.

**Why a `Finding` and not `plan.warnings`.** `6a812bf` drew that line: a
`Finding` names a capability a compiled graph **lost**, `plan.warnings` names a
**malformed document**. Neither document here is malformed — each is
individually valid, and each runs on its own. What is lost is the mount: it
produces nothing, on every run, for every input. That is `UNRESOLVED_SUBGRAPH`'s
class exactly, one reason over. And `plan.warnings` physically cannot carry it:
that channel is `ValidateWorkflowTool`'s in-memory plan, which has no root to
load a sibling package from and so has never seen the child document at all.

**Why a failure and not a report.** `afc57f6`'s test, applied: *can the
composition answer?* It cannot. The mount raises before `invoke`, the run ends
with no output, and `validate`'s one question — is this ready to run here — is
honestly no.

**What would still be green if the wrong thing were built?** A unit test of the
gap function against a compile that never calls it. So the tests below drive
the real `validate` **as a subprocess** — `conftest.py` sets
`OPENSTATEGRAPH_MEMORY_PATH` at import, so an in-process CLI test can be green
against an unfixed command — and assert on stdout *and* the exit code, plus the
library door through a real `WorkflowCompiler` build.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from openstategraph.compile.diagnostics import REPORT_ONLY, Finding
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

REQUIRED_CASE_ID = [{"key": "caseId", "type": "string", "label": "Case id", "required": True}]
TENANT_ONLY = [{"key": "tenant", "type": "string", "label": "Tenant"}]


def _document(
    name: str,
    *,
    context: Any = None,
    mounts: tuple[str, ...] = (),
) -> dict[str, Any]:
    """`input -> (mount, …) -> output`, with no model in it."""
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": ""}}
    ]
    edges: list[dict[str, Any]] = []
    tail, tail_port = "in1", "text"
    for index, slug in enumerate(mounts, start=1):
        node_id = f"m{index}"
        nodes.append(
            {
                "id": node_id,
                "type": "workflow.subgraph",
                "position": {"x": 100 * index, "y": 0},
                "data": {"workflow": slug},
            }
        )
        edges.append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": node_id, "portId": "input"},
            }
        )
        tail, tail_port = node_id, "result"
    nodes.append(
        {"id": "out1", "type": "output.formatted", "position": {"x": 900, "y": 0}, "data": {}}
    )
    edges.append(
        {
            "source": {"nodeId": tail, "portId": tail_port},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    )
    document: dict[str, Any] = {"version": 1, "name": name, "nodes": nodes, "edges": edges}
    if context is not None:
        document["settings"] = {"context": context}
    return document


def _warnings(parent: dict[str, Any], children: dict[str, dict[str, Any]]) -> list[str]:
    """Everything a real build of this composition noticed."""
    runtime = NodeRuntime(document_loader=children.__getitem__)
    WorkflowCompiler().build(parent, RunState, runtime.factory(parent))
    return runtime.diagnostics.warnings()


def _gap_lines(parent: dict[str, Any], children: dict[str, dict[str, Any]]) -> list[str]:
    return [line for line in _warnings(parent, children) if "can never run" in line]


# --------------------------------------------------------------------------- #
# The library door — a real compile of a real composition.
# --------------------------------------------------------------------------- #


class TestWhatTheCompilerSays:
    def test_a_required_key_the_parent_does_not_declare_is_named_at_compile(self) -> None:
        child = _document("child", context=REQUIRED_CASE_ID)
        parent = _document("parent", context=TENANT_ONLY, mounts=("child",))
        lines = _gap_lines(parent, {"child": child})
        assert len(lines) == 1
        assert "caseId" in lines[0]
        assert '"child"' in lines[0]

    def test_a_parent_declaring_nothing_at_all_is_told_too(self) -> None:
        """The commonest shape: a package is mounted into a document that has
        never heard of run context."""
        child = _document("child", context=REQUIRED_CASE_ID)
        parent = _document("parent", mounts=("child",))
        assert len(_gap_lines(parent, {"child": child})) == 1

    def test_a_grandchilds_gap_is_reported_too(self) -> None:
        """A middle document declaring nothing passes nothing on, so the gap is
        at the lower boundary and the parent absorbs the child's findings."""
        grandchild = _document("grandchild", context=REQUIRED_CASE_ID)
        middle = _document("middle", mounts=("grandchild",))
        parent = _document("parent", context=REQUIRED_CASE_ID, mounts=("middle",))
        lines = _gap_lines(parent, {"middle": middle, "grandchild": grandchild})
        assert len(lines) == 1
        assert "caseId" in lines[0]


# --------------------------------------------------------------------------- #
# The inverses — the noise regression, which is the failure mode of a check
# like this one.
# --------------------------------------------------------------------------- #


class TestWhatStaysSilent:
    def test_a_composition_that_can_supply_everything_says_nothing(self) -> None:
        child = _document("child", context=REQUIRED_CASE_ID)
        parent = _document(
            "parent", context=[*TENANT_ONLY, *REQUIRED_CASE_ID], mounts=("child",)
        )
        assert _gap_lines(parent, {"child": child}) == []

    def test_an_optional_key_is_not_a_gap(self) -> None:
        child = _document(
            "child", context=[{"key": "locale", "type": "string", "label": "L"}]
        )
        parent = _document("parent", mounts=("child",))
        assert _gap_lines(parent, {"child": child}) == []

    def test_a_required_key_with_a_default_is_not_a_gap(self) -> None:
        """`required` yields to a default, exactly as the validator decides it:
        a field the caller must always name even though an answer already
        exists makes that answer unreachable."""
        child = _document(
            "child",
            context=[
                {"key": "locale", "type": "string", "label": "L", "required": True, "default": "en-GB"}
            ],
        )
        parent = _document("parent", mounts=("child",))
        assert _gap_lines(parent, {"child": child}) == []

    def test_a_child_declaring_nothing_is_not_a_gap(self) -> None:
        parent = _document("parent", context=TENANT_ONLY, mounts=("child",))
        assert _gap_lines(parent, {"child": _document("child")}) == []

    def test_a_document_with_no_mounts_is_untouched(self) -> None:
        parent = _document("parent", context=REQUIRED_CASE_ID)
        assert _warnings(parent, {}) == []

    def test_a_package_mounted_three_times_says_it_once(self) -> None:
        """`f4f61bd`'s rule. The gap is a fact about two *documents*, and a
        parent's declaration is document-wide, so three mounts of one package
        have one gap between them for one reason."""
        child = _document("child", context=REQUIRED_CASE_ID)
        parent = _document("parent", mounts=("child", "child", "child"))
        assert len(_gap_lines(parent, {"child": child})) == 1


# --------------------------------------------------------------------------- #
# The classification — recorded here rather than asserted in prose.
# --------------------------------------------------------------------------- #


class TestItIsAFailureAndNotAReport:
    def test_the_finding_can_move_an_exit_code(self) -> None:
        assert Finding.UNSUPPLIABLE_CONTEXT not in REPORT_ONLY

    def test_it_reaches_failure_warnings(self) -> None:
        child = _document("child", context=REQUIRED_CASE_ID)
        parent = _document("parent", mounts=("child",))
        runtime = NodeRuntime(document_loader={"child": child}.__getitem__)
        WorkflowCompiler().build(parent, RunState, runtime.factory(parent))
        assert any("can never run" in line for line in runtime.diagnostics.failure_warnings())


# --------------------------------------------------------------------------- #
# The person's door — the real CLI, as a subprocess.
# --------------------------------------------------------------------------- #

REPO = Path(__file__).resolve().parents[2]


def _package(root: Path, slug: str, document: dict[str, Any]) -> Path:
    folder = root / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": document["name"],
                "savedAt": "2026-08-22T00:00:00Z",
                "document": document,
                "published": False,
            },
            indent=2,
        )
    )
    return folder


def _validate(target: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["OPENSTATEGRAPH_MEMORY_PATH"] = str(target.parent / "memory")
    return subprocess.run(
        [sys.executable, "-m", "openstategraph.cli", "validate", str(target)],
        capture_output=True,
        text=True,
        cwd=REPO / "backend",
        env=environment,
    )


class TestWhatAPersonGets:
    def test_validate_exits_non_zero_and_names_the_key_the_child_and_the_mount(
        self, tmp_path: Path
    ) -> None:
        _package(tmp_path, "child79", _document("child79", context=REQUIRED_CASE_ID))
        parent = _package(
            tmp_path, "parent79", _document("parent79", context=TENANT_ONLY, mounts=("child79",))
        )
        finished = _validate(parent)
        assert finished.returncode == 1, finished.stdout + finished.stderr
        assert "PROBLEMS FOUND" in finished.stdout
        assert "caseId" in finished.stdout
        assert "child79" in finished.stdout
        # Under PROBLEMS, never under Notes — a report cannot move an exit code
        # and this is not one.
        assert "Notes:" not in finished.stdout

    def test_validate_stays_green_when_the_parent_declares_the_key(
        self, tmp_path: Path
    ) -> None:
        _package(tmp_path, "child79", _document("child79", context=REQUIRED_CASE_ID))
        parent = _package(
            tmp_path,
            "parent79",
            _document("parent79", context=[*TENANT_ONLY, *REQUIRED_CASE_ID], mounts=("child79",)),
        )
        finished = _validate(parent)
        assert finished.returncode == 0, finished.stdout + finished.stderr
        assert "VALID" in finished.stdout
