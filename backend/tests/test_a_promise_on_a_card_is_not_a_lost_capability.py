"""The two findings `workflow-gallery` 50 left on the failure side, decided.

50 classified all `Finding` members into "this graph cannot do what it says"
and "this graph is drawn oddly", and kept `UNENFORCED_OUTCOME` and
`UNGUARDED_EXIT` failures **on its stated safe direction of error rather than
because the argument was won** — while naming the asymmetry it was creating.
`9729338` then made that classification move an exit code for the first time,
so the question stopped being academic.

**They are not the same animal, and running them is what shows it.** Both
documents were built and executed against a deterministic model, and the runs
disagree at the only place that matters — what came out:

- The mount that promises an outcome **answers, completely**. Every node
  produced its output, the child ran, the parent collected it. What is missing
  is a machine check on a sentence a person wrote on a card. That is literally
  `UNWIRED_REVISE` one level up: `_closes_a_loop_impl` — *does any grader in
  the child route revise* — is the same predicate, so one observation was a
  report when the child reported it and a failure when the parent did.
  Worse, it fires on a **deliberate** authoring act: writing an Expected
  outcome as documentation over a child that is a straight pipeline is a
  reasonable thing to do, and it exited 1.
- The second Output bypassing the document's own guardrail **discloses**.
  Same run, same model, two exits: the guarded one leaves as
  `Contact them at [REDACTED_EMAIL] or [REDACTED_URL]`, the unguarded one
  leaves with the address and the internal URL intact. The run did something
  the document was drawn *not* to do, and no other finding in the enum is
  reachable only by an inconsistency the author has to have drawn twice.

So one moves and one does not, and both are recorded with the evidence rather
than with the direction of error.

The exit code is the target, so the CLI is driven as a subprocess: asserting on
`REPORT_ONLY` alone would stay green against a fix wired to the wrong list.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import RespondingModel

from openstategraph import cli, load_workflow
from openstategraph.compile.diagnostics import REPORT_ONLY, Finding

EXAMPLES = Path(cli.__file__).resolve().parent / "examples"
PACKAGE_ROOT = Path(cli.__file__).resolve().parents[1]


def _validate(package: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "openstategraph.cli", "validate", str(package)],
        cwd=str(package.parent),
        env={
            **os.environ,
            "PYTHONPATH": str(PACKAGE_ROOT),
            "OPENSTATEGRAPH_WORKFLOWS_ROOT": str(package.parent),
        },
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def _memory_checkpointer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSTATEGRAPH_CHECKPOINT_PATH", "memory")


@pytest.fixture()
def responding_model() -> RespondingModel:
    """Answers whatever it is asked. The run is the subject, not the answer."""
    return RespondingModel([], default="Bicycles began in 1817 with the draisine.")


@pytest.fixture()
def disclosing_model() -> RespondingModel:
    """Says an email address and an internal URL — two of `guarded-lookup`'s
    own outbound `redact` rows, so what leaves each door is comparable."""
    return RespondingModel(
        [], default="Contact them at dana@example.com or https://internal.crm/records/88."
    )


@pytest.fixture()
def promising_mount(tmp_path: Path) -> Path:
    """A mount whose card states an outcome over a child with no revise branch.

    `chained-summarizer` is a straight pipeline on purpose — the shape a
    person mounts when they want a step done, and writes a note about.
    """
    shutil.copytree(EXAMPLES / "chained-summarizer", tmp_path / "chained-summarizer")
    shutil.rmtree(tmp_path / "chained-summarizer" / "tests", ignore_errors=True)
    package = tmp_path / "promising-parent"
    package.mkdir()
    document = {
        "version": 3,
        "name": "promising-parent",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
            {
                "id": "mount1",
                "type": "workflow.subgraph",
                "title": "Summarise",
                "data": {
                    "workflow": "chained-summarizer",
                    "outcome": "The summary is under 50 words.",
                },
                "position": {"x": 400, "y": 0},
            },
            {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 800, "y": 0}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "mount1", "portId": "input"},
            },
            {
                "source": {"nodeId": "mount1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }
    (package / "workflow.json").write_text(
        json.dumps(
            {"version": 1, "name": "promising-parent", "savedAt": "", "document": document}
        )
    )
    return package


@pytest.fixture()
def unguarded(tmp_path: Path) -> Path:
    """`guarded-lookup` with a second Output wired straight off the agent."""
    package = tmp_path / "unguarded-demo"
    shutil.copytree(EXAMPLES / "guarded-lookup", package)
    shutil.rmtree(package / "tests", ignore_errors=True)
    saved = json.loads((package / "workflow.json").read_text())
    document = saved["document"]
    document["nodes"].append(
        {"id": "out2", "type": "output.formatted", "data": {}, "position": {"x": 1400, "y": 500}}
    )
    document["edges"].append(
        {
            "source": {"nodeId": "agent1", "portId": "result"},
            "target": {"nodeId": "out2", "portId": "result"},
        }
    )
    (package / "workflow.json").write_text(json.dumps(saved))
    return package


class TestAPromiseOnACardIsAReport:
    """`UNENFORCED_OUTCOME` moves to the report side, on run evidence."""

    def test_the_run_answers_and_loses_nothing(
        self,
        promising_mount: Path,
        monkeypatch: pytest.MonkeyPatch,
        responding_model: RespondingModel,
    ) -> None:
        """The classification question, answered by running it."""
        monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(promising_mount.parent))
        workflow = load_workflow(promising_mount, model=responding_model)
        try:
            result = workflow.ask("Summarise the history of the bicycle.")
        finally:
            workflow.close()

        assert result.answer.strip()
        # Every node the document draws produced an output: nothing was
        # skipped, nothing degraded, no capability was lost.
        assert set(result.outputs) == {"in1", "mount1", "out1"}

    def test_so_validate_says_valid_and_exits_zero(self, promising_mount: Path) -> None:
        done = _validate(promising_mount)

        assert done.stdout.startswith("VALID"), done.stdout + done.stderr
        assert "PROBLEMS FOUND:" not in done.stdout
        assert done.returncode == cli.EXIT_OK

    def test_and_the_reader_is_still_told(self, promising_mount: Path) -> None:
        """Demoted from the exit code, never from the report."""
        done = _validate(promising_mount)

        assert "Notes:" in done.stdout
        assert "is documentation and nothing in the run checks it" in done.stdout

    def test_it_is_the_same_predicate_as_the_child_level_finding(self) -> None:
        """The asymmetry 50 named, pinned so it cannot be reintroduced.

        Both findings are *"no grader routes revise"*. One observation cannot
        be a failure at the parent and a report at the child.
        """
        assert Finding.UNENFORCED_OUTCOME in REPORT_ONLY
        assert Finding.UNWIRED_REVISE in REPORT_ONLY


class TestAnUnscreenedExitStaysAFailure:
    """`UNGUARDED_EXIT` stays, and the run says why rather than the taxonomy."""

    def test_the_document_discloses_what_its_own_policy_redacts(
        self,
        unguarded: Path,
        monkeypatch: pytest.MonkeyPatch,
        disclosing_model: RespondingModel,
    ) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(unguarded.parent))
        workflow = load_workflow(unguarded, model=disclosing_model)
        try:
            result = workflow.ask("who owns this?")
        finally:
            workflow.close()

        assert "[REDACTED_EMAIL]" in result.outputs["out1"]
        # The same answer, out the other door, with the policy not applied.
        assert "dana@example.com" in result.outputs["out2"]
        assert "https://internal.crm/records/88" in result.outputs["out2"]

    def test_so_validate_still_calls_it_a_problem_and_exits_one(self, unguarded: Path) -> None:
        done = _validate(unguarded)

        assert "PROBLEMS FOUND:" in done.stdout, done.stdout + done.stderr
        assert 'Output "out2" has no guardrail upstream of it' in done.stdout
        assert done.returncode == cli.EXIT_FAILURE

    def test_and_it_is_not_a_report(self) -> None:
        assert Finding.UNGUARDED_EXIT not in REPORT_ONLY


class TestNoShippedPackageMoved:
    """The inverse the ticket reserved to the owner: an exit code that moved.

    Measured before the change and again after — all 32 exit 0 — so the
    reclassification was this session's to make. In-process rather than 32
    subprocesses: only the integer is asserted, and the naive version costs
    100s (`organisms-first-class` 66's instrument note).
    """

    @staticmethod
    def _packages() -> list[Path]:
        examples = sorted(
            p for p in EXAMPLES.iterdir() if p.is_dir() and (p / "workflow.json").is_file()
        )
        workflows_root = PACKAGE_ROOT.parent / "workflows"
        repo = sorted(
            p for p in workflows_root.iterdir() if p.is_dir() and (p / "workflow.json").is_file()
        )
        return examples + repo

    def test_every_shipped_package_still_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        packages = self._packages()
        assert len(packages) >= 32, [p.name for p in packages]

        nonzero = []
        for package in packages:
            if cli.main(["validate", str(package)]) != cli.EXIT_OK:
                nonzero.append(package.name)
        capsys.readouterr()

        assert nonzero == []
