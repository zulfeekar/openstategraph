"""The generated contract is a build output, so its toolchain is pinned.

`docs/openapi.json` is generated from the FastAPI app and gated byte-exactly by
`test_openapi_contract.py` and by the `generated-openapi` CI job. That gate is
only meaningful if regenerating produces the same bytes twice — and it did not:
`backend/pyproject.toml` asked for `fastapi>=0.115` with no upper bound, and
FastAPI 0.141 adds `ctx` and `input` to its own `ValidationError` schema.

A fresh runner installs the newest FastAPI, so on the first real CI run both
that job and the drift test would have failed with no code change at all — and
regenerating to fix it would have broken them for anyone on an older version.
A gate that flips with whoever ran pip last is a gate people learn to ignore
(ship-it ticket 50, found while running ticket 49's floor leg in a clean
environment).

So there are two constraints doing two jobs, and this file is what stops them
drifting apart the way the `PYTHON_VERSIONS` matrix and the classifiers are
kept together by `test_python_support.py`:

- **`[server]` carries a range.** An adopter running our HTTP server is
  bounded — which is what catches the *next* breaking minor, exactly as the
  `[mcp]` upper bound already does — but not pinned to one version.
- **`[dev]` carries an exact pin.** Contributors and CI generate the artifact
  at one version, so the committed bytes are reproducible.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "backend" / "pyproject.toml"
CI = REPO / ".github" / "workflows" / "ci.yml"


def requirement(extra: str, distribution: str) -> str:
    """The one requirement naming `distribution` in `extra`."""
    data = tomllib.loads(PYPROJECT.read_text())
    entries = data["project"]["optional-dependencies"][extra]
    found = [line for line in entries if re.match(rf"^{distribution}\b", line)]
    assert len(found) == 1, f"expected one {distribution} in [{extra}], got {found}"
    return found[0]


def installed_extras(job: str) -> list[str]:
    """Every `backend[...]` extra list that `job` installs, parsed as YAML.

    Parsed rather than sliced between literal job headers: slicing depends on
    the *order* jobs appear in and on the exact indentation of the next one, so
    renaming or moving a job raised `ValueError: substring not found` from
    inside the helper instead of failing the assertion it was there to make.
    A gate whose failure mode is a stack trace about string indices is a gate
    that gets deleted rather than read.
    """
    jobs = yaml.safe_load(CI.read_text())["jobs"]

    assert job in jobs, f"{CI.name} has no `{job}` job — it defines {sorted(jobs)}"

    return [
        extras
        for step in jobs[job]["steps"]
        for extras in re.findall(r'pip install -e "backend\[([^\]]+)\]"', step.get("run", ""))
    ]


class TestTheTwoConstraints:
    def test_the_contributor_environment_pins_fastapi_exactly(self) -> None:
        pin = requirement("dev", "fastapi")

        assert "==" in pin, (
            f"[dev] must pin FastAPI exactly, got {pin!r} — a range regenerates "
            "docs/openapi.json differently depending on what pip resolved"
        )

    def test_adopters_get_a_range_not_the_pin(self) -> None:
        """The cost of reproducibility falls on us, not on an adopter."""
        server = requirement("server", "fastapi")

        assert ">=" in server and "==" not in server, server

    def test_the_pin_is_inside_the_range_it_is_pinning(self) -> None:
        """Two constraints that disagree are an uninstallable package, and pip
        would say so at install time rather than here — but only for whoever
        installs both extras."""
        pinned = requirement("dev", "fastapi").split("==")[1].strip()
        upper = re.search(r"<\s*([0-9.]+)", requirement("server", "fastapi"))
        lower = re.search(r">=\s*([0-9.]+)", requirement("server", "fastapi"))

        assert upper and lower, "the [server] range needs both bounds"

        def parts(version: str) -> tuple[int, ...]:
            return tuple(int(n) for n in version.split("."))

        assert parts(lower.group(1)) <= parts(pinned) < parts(upper.group(1))

    def test_the_upper_bound_exists_at_all(self) -> None:
        """FastAPI is 0.x, where minors carry breaking changes — 0.141 changed
        what `include_router` leaves in `app.routes`. Every other dependency
        in this file is bounded; this one's absence was the anomaly."""
        assert "<" in requirement("server", "fastapi")


class TestTheJobInstallsWhatItNeeds:
    def test_generated_openapi_installs_the_dev_extra(self) -> None:
        """The pin lives in `[dev]`, so a job that installs `[all]` alone gets
        whatever is newest and regenerates a different document — which is the
        exact failure this ticket is about, reintroduced by omission."""
        installs = installed_extras("generated-openapi")

        assert installs, "the generated-openapi job installs nothing"
        for extras in installs:
            assert "dev" in extras.split(","), (
                f"generated-openapi installs backend[{extras}] — it needs [dev] "
                "for the FastAPI pin that makes the artifact reproducible"
            )

    def test_the_backend_job_also_gets_the_pin(self) -> None:
        """It runs `test_openapi_contract.py`, which compares the same bytes."""
        installs = installed_extras("backend")

        assert installs, "the backend job installs nothing"
        for extras in installs:
            assert "dev" in extras.split(","), extras


class TestTheEnvironmentActuallyMatches:
    def test_the_installed_fastapi_is_the_pinned_one(self) -> None:
        """The claim above is about a file; this is about this interpreter.

        Skipped rather than failed when they differ: a contributor may
        legitimately be mid-upgrade, and the byte gate in
        `test_openapi_contract.py` is what actually holds the line. This exists
        to make the *reason* obvious when that one fails.
        """
        import pytest

        import fastapi

        pinned = requirement("dev", "fastapi").split("==")[1].strip()
        if fastapi.__version__ != pinned:
            pytest.skip(
                f"fastapi {fastapi.__version__} installed, {pinned} pinned in "
                "[dev] — reinstall with `pip install -e 'backend[all,dev]'` "
                "before regenerating docs/openapi.json"
            )
        assert fastapi.__version__ == pinned
