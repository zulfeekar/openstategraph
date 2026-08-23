"""The gate must say which CI jobs it runs and which it does not.

launch-readiness ticket 13: twenty ticket-loop sessions ended on `loop_gate.py`
PASS, then the push failed CI on three jobs the gate never touches
(`gallery-diagrams-check`, `clean-install`, `frontend`'s `npm run verify`). The
gate was answering a narrower question than the one a session reads it as
answering, and it never said so.

The fix has two halves, both pinned here:

1. `loop_gate.py` now runs the *fast* half of what CI runs — `frontend`'s
   static checks (typecheck/lint/format, not the duplicate vitest) and
   `gallery-diagrams-check` — because both are seconds, not minutes, and
   `clean-install`'s wheel-and-serve proof, because a warm `dist/` makes it
   ~40s, cheap next to the ~100s pytest+vitest already pay.
2. Whatever it still does not run (`generated-port-specs`,
   `generated-openapi`, `e2e`, `docs-freshness`) it must print by name, so a
   green gate is legible as "green on this subset" rather than misread as
   "green on CI".

**Why a test and not a comment**, exactly as `test_python_support.py` argues:
a hand-copied job list is a second spelling of `ci.yml`, and the second
spelling is the one nobody updates. This test parses the workflow file itself
and fails the day it grows a job `loop_gate.py`'s coverage table has never
heard of — the "a list is not a gate" lesson `every-workflow-green/20` paid
for, reopened by `production-ready/61`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import loop_gate  # noqa: E402


def _ci_jobs() -> set[str]:
    """Every job `ci.yml` declares, minus the aggregator that runs none of
    its own work."""
    jobs = set(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"])
    jobs.discard("ci-success")
    return jobs


def test_every_ci_job_is_accounted_for():
    """A job in ci.yml that loop_gate.py's coverage table has never heard of
    is exactly the defect this ticket closed: the gate silently answering a
    narrower question than CI asks."""
    known = set(loop_gate.CI_COVERAGE)
    jobs = _ci_jobs()
    missing = jobs - known
    assert not missing, (
        f"ci.yml grew job(s) {sorted(missing)} that loop_gate.py's CI_COVERAGE "
        "table does not mention. Add each one, run=True if the gate now runs "
        "it (or the fast part of it), run=False with a reason if not."
    )
    # The reverse direction matters too: a stale entry for a job that no
    # longer exists is a table lying about coverage in the other direction.
    stale = known - jobs
    assert not stale, f"CI_COVERAGE mentions job(s) {sorted(stale)} that ci.yml no longer has."


def test_the_jobs_that_actually_failed_are_now_run():
    """The three jobs from the 2026-08-23 incident must be marked run=True —
    this is the regression the ticket is closing, not a future aspiration."""
    for job in ("frontend", "clean-install", "gallery-diagrams-check"):
        assert loop_gate.CI_COVERAGE[job].run, f"{job} must be run by the gate (it was the one that broke CI)"


def test_not_run_jobs_are_printed_by_name(capsys):
    """A job the gate does not run must be visible in its output by name —
    not run=False in silence, which is the original defect restated."""
    not_run = [name for name, cov in loop_gate.CI_COVERAGE.items() if not cov.run]
    assert not_run, "expected at least one job the gate legitimately does not run"
    printed = loop_gate.ci_coverage_report()
    for name in not_run:
        assert name in printed, f"{name} (not run by the gate) must appear in the coverage report"
