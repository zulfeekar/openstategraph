"""`osg-agent-experience/63` — every scaffolded package's test had one basename.

`openstategraph new` wrote `tests/test_shape.py` into every package it made.
pytest's default import mode names a test module by its **basename**, so the
moment a project holds two packages, a whole-project `pytest workflows` run
stops before running anything:

    import file mismatch:
    imported module 'test_shape' has this __file__ attribute:
      …/alpha-lens/tests/test_shape.py
    which is not the same as the test file we want to collect:
      …/beta-lens/tests/test_shape.py
    HINT: remove __pycache__ / .pyc files and/or use a unique basename for
    your test file modules

A project generating fifteen packages met fourteen of those at once, none of
them carrying the word *duplicate*, and the offered suggestion (*make sure
your test modules have valid Python names*) is about a file that already has
one.

**Why the basename and not `__init__.py`, measured rather than assumed.**
pytest's hint names two remedies, and the second one — make the test directory
a package, so the module name is qualified by the directories above it — does
not work *here*, for a reason specific to this layout. `tests/__init__.py`
lifts the name to `tests.test_shape`, which is still one name for both
packages; qualifying it further would need `__init__.py` in `<slug>/` too, and
a slug is *required* to carry hyphens (`osg-agent-experience/64`), which no
Python identifier may. `TestInitPyIsNotTheRemedyHere` runs it and shows the
same error, so the argument is checkable rather than asserted.

`importmode=importlib` in the project's own pytest configuration is the third
remedy and it does work — but it is a line in a config file this scaffold does
not own and cannot write into a project it was pointed at, and a package whose
suite only collects under a setting somebody else has to know about is a
package that does not carry its own tests. The unique basename is the one fix
that travels with the package, which is the property `docs/adoption.md` claims
for `tests/` in the first place.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from openstategraph import templates
from openstategraph.scaffold import new_package, package_test_basename


class TestTheBasenameCarriesTheSlug:
    @pytest.mark.parametrize("template", sorted(templates.names()))
    def test_every_template_writes_a_slug_bearing_basename(
        self, tmp_path: Path, template: str
    ) -> None:
        target = new_package(tmp_path, "alpha-lens", template=template)

        written = sorted(p.name for p in (target / "tests").glob("test_*.py"))
        assert written in ([], [package_test_basename("alpha-lens")])

    def test_the_basename_is_an_importable_module_name(self) -> None:
        """A slug carries hyphens by rule; a module name may not. The
        transform is the whole point of the function, so it is asserted rather
        than left to the caller."""
        name = package_test_basename("site-lens-north-yard")

        assert name == "test_site_lens_north_yard_shape.py"
        assert name.removesuffix(".py").isidentifier()

    def test_two_slugs_never_share_a_basename(self) -> None:
        assert package_test_basename("alpha-lens") != package_test_basename("beta-lens")


class TestOnePytestRunCollectsBoth:
    """The ticket's own done-when, run as a subprocess because it is a
    *collection* failure — an in-process assertion about file names would stay
    green against the bug this closes."""

    def _run(self, workflows: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", str(workflows)],
            capture_output=True,
            text=True,
            cwd=workflows.parent,
        )

    def test_two_packages_collect_and_pass_together(self, tmp_path: Path) -> None:
        workflows = tmp_path / "workflows"
        workflows.mkdir()
        new_package(workflows, "alpha-lens")
        new_package(workflows, "beta-lens")

        result = self._run(workflows)

        assert "import file mismatch" not in result.stdout + result.stderr
        assert "2 passed" in result.stdout, result.stdout + result.stderr


class TestInitPyIsNotTheRemedyHere:
    """The alternative the ticket asked to be argued rather than waved away.

    Recorded as a running check because the argument rests on a fact about
    pytest that a reader would otherwise have to take on trust: with
    `tests/__init__.py` the module name becomes `tests.test_shape`, which is
    still one name for two packages, and the qualifying step that would fix it
    needs a `<slug>/__init__.py` that no valid slug can be.
    """

    def test_init_py_alone_still_collides(self, tmp_path: Path) -> None:
        workflows = tmp_path / "workflows"
        workflows.mkdir()
        for slug in ("alpha-lens", "beta-lens"):
            target = new_package(workflows, slug)
            # Undo the fix, restoring the shared basename this ticket removed,
            # and apply the remedy being argued against instead.
            (target / "tests" / package_test_basename(slug)).rename(
                target / "tests" / "test_shape.py"
            )
            (target / "tests" / "__init__.py").write_text("")

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", str(workflows)],
            capture_output=True,
            text=True,
            cwd=workflows.parent,
        )

        assert "import file mismatch" in result.stdout + result.stderr

    def test_a_slug_cannot_be_a_python_package_name(self) -> None:
        """The reason the qualifying step is unavailable, in one assertion."""
        assert not "site-lens-north-yard".isidentifier()


class TestTheLayoutDocumentSaysWhy:
    def _doc(self) -> str:
        return (Path(__file__).resolve().parents[2] / "docs" / "adoption.md").read_text()

    def test_the_doc_no_longer_names_the_shared_basename(self) -> None:
        assert "tests/test_shape.py" not in self._doc()

    def test_the_doc_says_why_the_slug_is_in_the_name(self) -> None:
        doc = self._doc()
        assert "unique basename" in doc
        assert "osg-agent-experience/63" in doc
