"""The Python versions we advertise must be the Python versions we run.

The gap this closes was found by reading, not by failing: `classifiers` claimed
3.11, 3.12 and 3.13, `requires-python` said `>=3.11`, and CI ran 3.12 and only
3.12. Two thirds of the promise on the PyPI page had never executed a line of
this code. `docs/decisions/sdk-practice.md` §3 recommendation 4 records the
same finding and SUP's principle for fixing it — lint on one version, test on
min and max.

**Why a test and not a comment.** A matrix and a classifier list are two
hand-maintained spellings of one fact, in two files, in two languages, edited
by different instincts — somebody adding 3.14 support edits the classifiers
because that is what PyPI shows, and somebody speeding CI up edits the matrix
because that is what costs money. Whichever they touch, this fails. The fact
lives in `pyproject.toml` (it is the distribution's own metadata, and the only
one a consumer can read); `.github/workflows/ci.yml` is checked *against* it.

**Why parsing the workflow file is worth it**, rather than a duplicated literal
here: a duplicated literal is a third spelling, and the third spelling is the
one nobody remembers to update.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The job whose matrix must match the classifiers. Named, so that adding an
#: unrelated Python job (a docs build, say) does not silently satisfy this.
BACKEND_JOB = "backend"

_CLASSIFIER = re.compile(r"^Programming Language :: Python :: (\d+\.\d+)$")


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _as_tuple(version: str) -> tuple[int, ...]:
    """Sort `3.9` before `3.11`, which a string sort gets backwards."""
    return tuple(int(part) for part in version.split("."))


def advertised_versions() -> list[str]:
    """Every `X.Y` the classifiers claim, oldest first."""
    found = [
        match.group(1)
        for classifier in _pyproject()["project"]["classifiers"]
        if (match := _CLASSIFIER.match(classifier))
    ]
    return sorted(found, key=_as_tuple)


def matrix_versions() -> list[str]:
    """The `python-version` matrix of the backend CI job, oldest first."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"][BACKEND_JOB]
    versions = job["strategy"]["matrix"]["python-version"]
    # YAML would read a bare `3.11` as a float and `3.1` as one too — which is
    # the same value. Quoting in the workflow is what keeps them distinct, and
    # this is where a missing quote gets caught rather than silently dropping a
    # leg of the matrix.
    assert all(isinstance(version, str) for version in versions), (
        "Quote the versions in the CI matrix: unquoted YAML reads 3.10 as the "
        "float 3.1, which is a different version that does not exist here."
    )
    return sorted(versions, key=_as_tuple)


requires_workflow = pytest.mark.skipif(
    not WORKFLOW.exists(),
    reason="No .github/ in this tree — an installed sdist has no CI workflow to check.",
)


class TestTheClaim:
    """`requires-python` and the classifiers are one statement, not two."""

    def test_the_classifiers_name_at_least_two_versions(self) -> None:
        # Min-and-max is only a meaningful policy if there is a range at all.
        assert len(advertised_versions()) >= 2

    def test_requires_python_floor_is_the_oldest_classifier(self) -> None:
        requires = _pyproject()["project"]["requires-python"]
        floor = re.search(r">=\s*(\d+\.\d+)", requires)
        assert floor is not None, f"requires-python {requires!r} states no floor"
        assert floor.group(1) == advertised_versions()[0], (
            "requires-python and the oldest `Programming Language :: Python` "
            "classifier disagree. A resolver obeys the first and a human reads "
            "the second, so they must say the same thing."
        )

    def test_the_advertised_versions_have_no_holes(self) -> None:
        # `>=3.11` cannot exclude 3.12 while claiming 3.13: a resolver will
        # install on 3.12 regardless, so a skipped classifier is a version we
        # ship to and disown.
        versions = [_as_tuple(version) for version in advertised_versions()]
        expected = [(3, minor) for minor in range(versions[0][1], versions[-1][1] + 1)]
        assert versions == expected


@requires_workflow
class TestTheProof:
    """CI must execute the floor and the ceiling of that claim."""

    def test_the_matrix_runs_the_oldest_advertised_version(self) -> None:
        oldest = advertised_versions()[0]
        assert oldest in matrix_versions(), (
            f"pyproject.toml advertises Python {oldest} and CI never runs it. "
            f"Either add it to the `{BACKEND_JOB}` matrix in {WORKFLOW.name} or "
            "drop the classifier — an untested claim is the one thing not on offer."
        )

    def test_the_matrix_runs_the_newest_advertised_version(self) -> None:
        newest = advertised_versions()[-1]
        assert newest in matrix_versions(), (
            f"pyproject.toml advertises Python {newest} and CI never runs it. "
            f"Either add it to the `{BACKEND_JOB}` matrix in {WORKFLOW.name} or "
            "drop the classifier."
        )

    def test_the_matrix_runs_nothing_we_do_not_advertise(self) -> None:
        extra = sorted(set(matrix_versions()) - set(advertised_versions()), key=_as_tuple)
        assert not extra, (
            f"CI runs Python {extra}, which the classifiers do not claim. "
            "Testing a version we tell nobody about spends a runner on a "
            "promise nobody can rely on — add the classifier or drop the leg."
        )

    def test_every_matrix_leg_actually_runs_the_test_suite(self) -> None:
        """A matrix whose legs all skip the tests is decoration.

        Guards the specific way this could rot: the lint/mypy/coverage steps
        are pinned to one version with an `if:`, and it would be easy to pin
        pytest the same way by copy-paste and leave the second leg installing
        dependencies and asserting nothing.
        """
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = workflow["jobs"][BACKEND_JOB]["steps"]
        pytest_steps = [step for step in steps if "pytest" in str(step.get("run", ""))]
        assert pytest_steps, "The backend job runs no tests at all."

        for version in matrix_versions():
            runs_here = [
                step
                for step in pytest_steps
                # No condition means every leg; a condition must admit this one.
                if "if" not in step or version in str(step["if"])
            ]
            assert runs_here, (
                f"No pytest step in the `{BACKEND_JOB}` job runs on Python {version}. "
                "That leg installs dependencies and proves nothing."
            )
