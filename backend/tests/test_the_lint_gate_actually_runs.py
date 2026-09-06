"""The lint gate, run where somebody will see it fail.

`.github/workflows/ci.yml` runs `python -m ruff check backend`, and that is the
only place it ran. CI last executed on 2026-08-16 (`d17b930`); by 2026-08-22 the
tree carried **22 violations** across 11 files that nobody had seen, because the
gate lived somewhere that had not run in ~180 commits (`organisms-first-class`
47). A gate whose only trigger is a workflow that is not firing is not a gate.

So it runs here too. `pytest` is the thing this repository actually runs on
every session, which makes it the honest place for a check that is supposed to
be continuous. CI keeps its step — this does not replace it — but a violation
now costs one test run to notice rather than a five-day-old green badge.

Skipped, never failed, when ruff is absent: `ruff` is a `[dev]` dependency and
a consumer installing the lean core must not see a red suite for a tool they
were never asked to install.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _ruff(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _require_ruff() -> None:
    if _ruff("--version").returncode != 0:
        pytest.skip("ruff is not installed; it is a [dev] extra")


class TestBackendPassesItsOwnLintGate:
    def test_ruff_check_backend_is_clean(self) -> None:
        _require_ruff()

        result = _ruff("check", "backend", "--output-format=concise")

        assert result.returncode == 0, (
            "`ruff check backend` — the exact command ci.yml runs — is not "
            f"clean:\n{result.stdout}{result.stderr}"
        )

    def test_the_gate_fails_on_a_fresh_violation(self, tmp_path: Path) -> None:
        """The half that matters: a clean run must mean the gate can still bite.

        A gate asserted only by its own silence is indistinguishable from a gate
        that reports nothing at all — which is the shape of the defect this file
        exists for. So plant one and watch it caught.
        """
        _require_ruff()

        offender = tmp_path / "fresh_violation.py"
        offender.write_text("import json\n")  # F401

        result = _ruff("check", "--select=E9,F", "--output-format=concise", str(offender))

        assert result.returncode != 0
        assert "F401" in result.stdout


class TestTheGateDoesNotDriftWithPyPI:
    """A pin claimed in a comment is a story; this is the part that can fail."""

    def test_ruff_is_pinned_exactly_in_the_dev_extra(self) -> None:
        text = (REPO_ROOT / "backend" / "pyproject.toml").read_text()

        assert '"ruff==' in text, "ruff must be pinned exactly, not floored"
        assert '"ruff>=' not in text

    def test_ci_installs_no_second_unpinned_ruff(self) -> None:
        """The drift was here, not in the extra: `pip install ... dev]" ruff`."""
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

        install_lines = [
            line for line in text.splitlines() if "pip install" in line and "ruff" in line
        ]

        assert install_lines == [], (
            "ci.yml installs ruff outside the pinned extra, so the gate can "
            f"move without a commit: {install_lines}"
        )
