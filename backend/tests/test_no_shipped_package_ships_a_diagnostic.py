"""A package this repository ships must load without reporting anything.

`every-workflow-green/44`. `chinook-assistant` — the gallery's headline
example, the one the docs send a stranger to — tripped its own grounding
guard on `load_workflow` alone, with no model and no run:

> Output "out1" can be reached from "agent-web", which holds a capability that
> answers from outside this run's own data ... and no check stands between
> them.

Nothing measured that. Every one of these findings is `REPORT_ONLY` by
design — it is a sentence to a developer, not a build failure — and the
consequence of shipping one is not a broken run but a taught lesson: a reader
opening the example they were told to learn from meets a diagnostic about it,
and concludes the diagnostics are noise.

## A ratchet, not a bare ceiling

Five of the nine shipped packages reported on the day this was written, so a
bare "zero everywhere" would have been red on arrival — which is how a pin
acquires a suppression and stops measuring anything (`CLAUDE.md`, the module
ceiling). `KNOWN` is therefore the exact set each package reports **today**,
with the argument for each, and the assertion is equality:

- a package **not** in `KNOWN` must load clean, so a tenth package cannot
  arrive carrying a finding;
- a package **in** `KNOWN` must report exactly what is recorded — a *new*
  finding on an already-reporting package is red, and so is a *fixed* one,
  which is what makes the record shrink rather than rot.

The walk itself is derived: `workflows_root()` names the packages and each
one's own document names its nodes, so nothing here is hand-listed except the
exceptions, which is the only place a hand-written line can be reviewed
against an argument.

## In a clean interpreter, for `43`'s reason

`pytest.ini` puts `workflows/chinook-assistant` on `pythonpath`, and a finding
about a *capability* is only reported when that capability binds. Measuring
in-process would therefore report on a registry no server has —
`test_a_shipped_package_binds_its_own_tool_types.py` is the record of that
exact illusion costing a silent production failure. So the probe runs in a
subprocess whose only path entry is `backend/`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Substrings that identify the findings a package is still allowed to report,
#: per package, with the argument for each. Substrings rather than whole
#: sentences: the copy is `compile/diagnostics.py`'s to reword, and a test that
#: pins prose fails on an improvement.
#:
#: Every row here is `UNDECLARED_FALLBACK`, and every row is the *same shape* —
#: a step holding a web capability reaching an Output with no `guard.check` on
#: the path. `44` fixed `chinook-assistant`'s, and these three are not the same
#: edit. They are `every-workflow-green/50`.
KNOWN: dict[str, list[str]] = {
    # Both agents hold the two web tools and nothing else, so `44`'s remedy —
    # a `guard.check` running a package function that refuses an unattributed
    # figure — is the right one here too. It is not applied here because the
    # function would be a second copy of `chinook-assistant`'s, and a rule
    # written twice is the duplication `CLAUDE.md` forbids: three packages
    # needing one statement is an argument about where that statement lives,
    # and that is `50`'s to settle rather than this ticket's to pre-empt.
    "classifier-router-qa": [
        'Output "out-general" can be reached from "agent-general"',
        'Output "out-world" can be reached from "agent-world"',
    ],
    # `agent-general` holds six platform tools beside the two web ones, so it
    # answers most questions from files it read in this repository. A gate
    # demanding a URL beside every figure would refuse those honestly-grounded
    # answers, and a gate people route around is worse than none
    # (`compile/grounding.py`). The check this branch needs is the one that
    # separates a figure the run retrieved from a figure it did not — which is
    # `numbers_in_prose`, and that cannot see a non-SQL tool's results at all
    # (`every-workflow-green/49`).
    "concierge": ['Output "out1" can be reached from "agent-general"'],
    # The producer is an `orchestrate.worker`, and `port_specs.json` gives that
    # type no `feedback` in-port — so a `guard.check` placed on its result has
    # nowhere to send `revise`, and the document would trade this finding for
    # `UNWIRED_REVISE`. Where the rejection should go on a supervisor fan-out
    # is a design question, not an edit.
    "morning-brief": ['Output "out1" can be reached from "worker-web"'],
}

#: Printed as one JSON object on stdout: every shipped package and the
#: diagnostics `load_workflow` reports for it.
_PROBE = r"""
import json

from openstategraph import load_workflow
from openstategraph.workflows_root import workflows_root

root = workflows_root()
report = {"root": str(root), "packages": {}}
for package in sorted(p for p in root.iterdir() if (p / "workflow.json").is_file()):
    try:
        loaded = load_workflow(str(package))
        warnings = [str(w) for w in loaded.warnings]
    except Exception as exc:  # reported, never raised: the assertion is the caller's
        warnings = ["LOAD RAISED %s: %s" % (type(exc).__name__, exc)]
    report["packages"][package.name] = warnings

print("REPORT " + json.dumps(report))
"""


@pytest.fixture(scope="module")
def diagnostics_by_package() -> dict:
    env = {k: v for k, v in os.environ.items() if k != "OPENSTATEGRAPH_WORKFLOWS_ROOT"}
    env["PYTHONPATH"] = str(REPO_ROOT / "backend")
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert completed.returncode == 0, (
        f"The probe itself failed in a clean process:\n{completed.stderr[-4000:]}"
    )
    line = next(row for row in reversed(completed.stdout.splitlines()) if row.startswith("REPORT "))
    return json.loads(line[len("REPORT ") :])


def _unexplained(package: str, warnings: list[str]) -> list[str]:
    """The findings this package reports that `KNOWN` does not account for."""
    allowed = KNOWN.get(package, [])
    return [w for w in warnings if not any(marker in w for marker in allowed)]


class TestEveryShippedPackageLoadsClean:
    def test_the_walk_found_the_packages(self, diagnostics_by_package: dict) -> None:
        packages = diagnostics_by_package["packages"]
        assert packages, f"No packages found under {diagnostics_by_package['root']}"

    def test_no_package_reports_a_finding_that_is_not_recorded(
        self, diagnostics_by_package: dict
    ) -> None:
        offenders = {
            slug: unexplained
            for slug, warnings in diagnostics_by_package["packages"].items()
            if (unexplained := _unexplained(slug, warnings))
        }
        assert not offenders, (
            "Shipped packages report findings on load that nothing in this file "
            f"accounts for: {json.dumps(offenders, indent=2)}\n"
            "A package a stranger is sent to must not arrive carrying a diagnostic "
            "about itself. Fix the document, or record the finding in KNOWN with the "
            "argument for why it stands."
        )

    def test_the_headline_package_is_clean(self, diagnostics_by_package: dict) -> None:
        """`44`'s own subject, named because it is the one the docs point at.

        Covered by the test above as well; stated separately so a regression on
        the gallery's front door reads as itself in a summary line rather than
        as one entry in a dictionary.
        """
        assert diagnostics_by_package["packages"].get("chinook-assistant") == []


class TestTheRecordShrinks:
    """A recorded exception that has been fixed must leave this file.

    Without this half, `KNOWN` is a list that only ever grows, and a fix made
    two tickets from now would be invisible — the gate would keep excusing a
    finding nobody ships any more, and the next reader would take the argument
    beside it for a live constraint.
    """

    def test_every_recorded_package_still_ships(self, diagnostics_by_package: dict) -> None:
        packages = diagnostics_by_package["packages"]
        gone = [slug for slug in KNOWN if slug not in packages]
        assert not gone, f"KNOWN excuses packages this repository no longer ships: {gone}"

    def test_every_recorded_finding_is_still_reported(self, diagnostics_by_package: dict) -> None:
        packages = diagnostics_by_package["packages"]
        stale = {
            slug: [m for m in markers if not any(m in w for w in packages.get(slug, []))]
            for slug, markers in KNOWN.items()
        }
        stale = {slug: markers for slug, markers in stale.items() if markers}
        assert not stale, (
            f"These recorded findings are no longer reported: {json.dumps(stale, indent=2)}\n"
            "They have been fixed. Delete the rows, so the record measures what is "
            "left rather than what once was."
        )
