"""The type gate, run where somebody will see it fail — the second half of 47.

`.github/workflows/ci.yml` runs `cd backend && python -m mypy`, and that was
the only place it ran. CI last executed on 2026-08-16 (`d17b930`); by
2026-08-22 the tree carried **three** type errors nobody had seen, one of them
a genuine Liskov break that cost the knowledge explorer a `TypeError`
(`organisms-first-class` 48). Exactly the shape of 47's lint finding, on the
same CI step, for the same reason: a gate whose only trigger is a workflow that
is not firing is not a gate.

**The cost, measured on this checkout rather than guessed** (mypy 1.19.1, 123
source files, an Apple-silicon laptop):

- **cold, no `.mypy_cache`: ~46s**, and the cache it writes is ~310M
- **warm: ~3.2s**, against a suite that takes ~147s

So the honest price is one 46-second run per fresh checkout and ~2% of a suite
thereafter. That is worth paying and the lint gate's precedent is why: the
alternative on offer is not "a cheaper gate", it is the five-day-old green
badge that let three errors accumulate. A slow gate in the inner loop is its
own way of not being run, and 3.2s is not that.

Skipped, never failed, when mypy is absent — same rule as the lint gate: mypy
is a `[dev]` extra and a consumer installing the lean core must not see a red
suite for a tool they were never asked to install.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def _mypy(*args: str, cwd: Path = BACKEND) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mypy", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _require_mypy() -> None:
    if _mypy("--version").returncode != 0:
        pytest.skip("mypy is not installed; it is a [dev] extra")


class TestBackendPassesItsOwnTypeGate:
    def test_mypy_is_clean(self) -> None:
        """The exact command ci.yml runs, from the directory it runs it in.

        The cwd is load-bearing: `[tool.mypy]` lives in `backend/pyproject.toml`
        and names `files = ["openstategraph"]`, so from the repo root this
        checks nothing and still exits 0 — the same passing-looking, measuring-
        nothing failure `ruff check backend` has from `backend/`.
        """
        _require_mypy()

        result = _mypy()

        assert result.returncode == 0, (
            "`cd backend && python -m mypy` — the exact command ci.yml runs — "
            f"is not clean:\n{result.stdout}{result.stderr}"
        )

    def test_the_gate_fails_on_a_fresh_violation(self, tmp_path: Path) -> None:
        """A gate asserted only by its own silence cannot be told from no gate.

        `disallow_untyped_defs` is the flag `pyproject.toml` calls load-bearing
        — it is what makes every other check reach into function bodies — so it
        is the one planted here.
        """
        _require_mypy()

        offender = tmp_path / "fresh_violation.py"
        offender.write_text("def undeclared(x):\n    return x\n")

        result = _mypy("--disallow-untyped-defs", str(offender), cwd=tmp_path)

        assert result.returncode != 0
        assert "no-untyped-def" in result.stdout


class TestTheGateDoesNotDriftWithPyPI:
    """A pin claimed in a comment is a story; this is the part that can fail.

    Same reasoning as ruff's, and it rots the same way: a release with a new
    check turns a clean tree red with no commit to blame, and raising the pin
    is then a deliberate commit somebody reads. The cost is that nobody gets a
    new check for free either.
    """

    def test_mypy_is_pinned_exactly_in_the_dev_extra(self) -> None:
        text = (BACKEND / "pyproject.toml").read_text()

        assert '"mypy==' in text, "mypy must be pinned exactly, not floored"
        assert '"mypy>=' not in text

    def test_ci_installs_no_second_unpinned_mypy(self) -> None:
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

        install_lines = [
            line for line in text.splitlines() if "pip install" in line and "mypy" in line
        ]

        assert install_lines == [], (
            "ci.yml installs mypy outside the pinned extra, so the gate can "
            f"move without a commit: {install_lines}"
        )
