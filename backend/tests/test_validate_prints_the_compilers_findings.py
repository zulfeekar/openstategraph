"""`openstategraph validate` prints what the compiler noticed — and exits on it.

`organisms-first-class` 66. Until this file, `cmd_validate` read
`plan.warnings` and nothing else, so **none of the twelve `Finding` kinds had
ever reached the command whose one question they answer**. A document whose
second Output bypasses the guardrail the rest of it keeps printed `VALID` and
exited 0; `run` on the same document printed the sentence twice.

**These drive the real CLI as a subprocess**, because the target is what a
person at a terminal sees and what their CI gets — stdout, stderr *and* the
exit code. Asserting on `CompileDiagnostics.warnings()` would prove only that
the list this command never read still exists.

**No model is called.** `cmd_validate` compiles with the same drawing-only
stand-in `graph` uses, so every case here runs with no provider credential.

The classification is the substance and both halves are pinned:

- a **failure**-classed finding (`UNGUARDED_EXIT`) reaches PROBLEMS FOUND and
  moves the exit code to 1 — that is what `failure_warnings()` exists for;
- a **report-only** one (`UNWIRED_REVISE`) is printed under its own heading and
  **must not** move the exit code (`8bda508`) — synthesised on a copy of
  `web-research-digest` with its `revise` edge stripped, since `workflow-gallery`
  78 wired `support-triage`'s own edge and no shipped package carries this
  finding on purpose any more;
- and every one of the 32 shipped packages still exits 0, measured before and
  after.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from openstategraph import cli
from openstategraph.compile.diagnostics import REPORT_ONLY, Finding

EXAMPLES = Path(cli.__file__).resolve().parent / "examples"
REPO = Path(cli.__file__).resolve().parents[2]


def _validate(package: Path) -> subprocess.CompletedProcess[str]:
    """The command, as a person types it, from a directory that is not this one."""
    return subprocess.run(
        [sys.executable, "-m", "openstategraph.cli", "validate", str(package)],
        cwd=str(package.parent),
        env={**os.environ, "PYTHONPATH": str(Path(cli.__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def unguarded(tmp_path: Path) -> Path:
    """`guarded-lookup` plus a second Output wired straight off the agent.

    The realistic mistake `UNGUARDED_EXIT` was written for: the document keeps
    a policy on one path and an answer leaves by another. Copied whole so its
    `tools/` travels with it — a package without them trips the *binding*
    check instead, which already exits 1 and would prove nothing.
    """
    package = tmp_path / "unguarded-demo"
    shutil.copytree(EXAMPLES / "guarded-lookup", package)
    shutil.rmtree(package / "tests", ignore_errors=True)
    manifest = package / "workflow.json"
    saved = json.loads(manifest.read_text())
    document = saved["document"]
    document["nodes"].append(
        {"id": "out2", "type": "output.formatted", "data": {}, "position": {"x": 1400, "y": 500}}
    )
    document["edges"].append(
        {"source": {"nodeId": "agent1", "portId": "result"},
         "target": {"nodeId": "out2", "portId": "result"}}
    )
    manifest.write_text(json.dumps(saved))
    return package


@pytest.fixture()
def report_only(tmp_path: Path) -> Path:
    """A grader with its `revise` edge stripped — the report-only finding,
    synthesised the same way `unguarded` synthesises its failure-classed one.

    Until `workflow-gallery` 78 this copied `support-triage`, which shipped
    an unwired grader deliberately (gallery 31). 78 wired that edge into the
    packaged copy to match the fix `48` gave the dev workspace copy, so no
    shipped package carries `UNWIRED_REVISE` any more — `web-research-digest`
    is the donor here precisely because it is a real package whose grader
    *is* wired, so removing the edge is an unambiguous synthetic defect
    rather than a coincidence of some other package's real shape.
    """
    package = tmp_path / "report-demo"
    shutil.copytree(EXAMPLES / "web-research-digest", package)
    shutil.rmtree(package / "tests", ignore_errors=True)
    manifest = package / "workflow.json"
    saved = json.loads(manifest.read_text())
    document = saved["document"]
    document["edges"] = [
        e
        for e in document["edges"]
        if e["source"] != {"nodeId": "grader1", "portId": "revise"}
    ]
    manifest.write_text(json.dumps(saved))
    return package


class TestAFailureClassedFinding:
    def test_it_is_printed_and_it_exits_one(self, unguarded: Path) -> None:
        done = _validate(unguarded)

        assert "PROBLEMS FOUND:" in done.stdout, done.stdout
        assert 'Output "out2" has no guardrail upstream of it' in done.stdout
        assert done.returncode == cli.EXIT_FAILURE

    def test_the_topology_still_follows_it(self, unguarded: Path) -> None:
        """A finding is folded into the one verdict, not printed after it."""
        done = _validate(unguarded)

        assert "Topology:" in done.stdout
        assert done.stdout.index("out2") < done.stdout.index("Topology:")


class TestAReportOnlyFinding:
    def test_it_is_printed(self, report_only: Path) -> None:
        done = _validate(report_only)

        assert 'Grader "grader1" has no revise edge' in done.stdout, done.stdout

    def test_it_does_not_move_the_exit_code(self, report_only: Path) -> None:
        """`8bda508`'s rule, at the surface it was written for."""
        done = _validate(report_only)

        assert done.returncode == cli.EXIT_OK, done.stdout
        assert "PROBLEMS FOUND:" not in done.stdout

    def test_it_is_not_printed_as_a_problem(self, report_only: Path) -> None:
        """A note under a VALID heading, so a reader can tell the two apart."""
        done = _validate(report_only)

        assert done.stdout.startswith("VALID")
        assert "Notes:" in done.stdout


class TestTheInverses:
    def test_a_clean_package_still_says_valid_and_exits_zero(self, tmp_path: Path) -> None:
        package = tmp_path / "chained-summarizer"
        shutil.copytree(EXAMPLES / "chained-summarizer", package)
        shutil.rmtree(package / "tests", ignore_errors=True)

        done = _validate(package)

        assert done.stdout.startswith("VALID")
        assert "Notes:" not in done.stdout
        assert done.returncode == cli.EXIT_OK

    def test_every_shipped_package_still_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        """Measured before the change and pinned after it: printing the
        findings moved no shipped package's exit code, because the only one
        that carries a finding at all carries a report-only one.

        **In-process, unlike every case above**, and the reason is a measured
        one: 32 subprocesses cost 100 seconds and 32 `cli.main` calls cost 4,
        for the same integer. The cases that assert on what is *printed* stay
        subprocesses; this one asserts only the exit code, which `main` returns
        and the shell merely relays.
        """
        packages = sorted(
            [p for p in EXAMPLES.iterdir() if (p / "workflow.json").is_file()]
            + [p for p in (REPO / "workflows").iterdir() if (p / "workflow.json").is_file()]
        )
        assert len(packages) == 32

        moved = {p.name: cli.main(["validate", str(p)]) for p in packages}
        capsys.readouterr()

        assert {name: code for name, code in moved.items() if code != cli.EXIT_OK} == {}


class TestTheClassificationIsReadFromOnePlace:
    def test_every_finding_is_on_exactly_one_side(self) -> None:
        """The command derives its two headings from `REPORT_ONLY`, so a new
        member is classified once, in `diagnostics.py`, and not again here."""
        assert REPORT_ONLY < set(Finding)
        assert len(set(Finding)) == 18
