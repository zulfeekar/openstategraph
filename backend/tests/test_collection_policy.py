"""Collection policy: the user's workspace is not our test suite.

workflow-gallery ticket 46. `workflows/` is the root a *user* writes into,
and the documented way to start a package is to copy one out of
`backend/openstategraph/examples/`. That copy carries the example's own
`tests/test_<slug>_document.py`, so two files with the same module basename
sit under two roots with no `__init__.py` — and pytest refuses both:

    import file mismatch: imported module 'test_morning_brief_document' has
    this __file__ attribute: workflows/morning-brief/tests/...

The same collision took CI down once before (`6ed56df`), and it does not
need a broken package to happen: an *identical, working* copy is enough,
which is why "don't copy a broken one" is not a fix.

So collection names what it collects. `backend` is our suite; the curated
example is named by path, exactly as `pythonpath` already names it; the
`workflows/` root is never swept. Nothing is lost by that — a package's
`tests/` are run by `openstategraph test <package>` and its *document* is
read by the every-package sweep (`backend/tests/test_the_one_example.py`),
neither of which needs pytest to collect a user's files.

This file fails the day `workflows` goes back in as a bare root.
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTEST_INI = REPO_ROOT / "pytest.ini"


def _testpaths() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI)
    return parser["pytest"]["testpaths"].split()


class TestWhatCollectionSweeps:
    def test_our_own_suite_is_collected(self) -> None:
        assert "backend" in _testpaths()

    def test_the_users_workspace_root_is_not(self) -> None:
        assert "workflows" not in _testpaths(), (
            "a bare `workflows` root collects whatever a user copied in, and an "
            "example copied out of examples/ collides with itself on module basename"
        )

    def test_a_workflows_testpath_names_one_package(self) -> None:
        for entry in _testpaths():
            path = Path(entry)
            if path.parts[0] != "workflows":
                continue
            assert len(path.parts) >= 2, f"{entry} is a root, not a package"
            assert (REPO_ROOT / path).is_dir(), f"{entry} does not exist"

    def test_the_curated_example_still_runs(self) -> None:
        assert "workflows/chinook-assistant" in _testpaths()


class TestTheCollisionIsStillThereToAvoid:
    """The hazard is a property of the tree, not of any one package."""

    def test_an_example_and_its_copy_share_a_module_basename(self) -> None:
        examples = REPO_ROOT / "backend" / "openstategraph" / "examples"
        document_tests = sorted(examples.glob("*/tests/test_*_document.py"))
        assert document_tests, "the examples ship document tests"
        # A copy into workflows/ keeps the file name, whatever the user calls
        # the directory — the basename is derived from the example's slug.
        assert len({path.name for path in document_tests}) == len(document_tests)
        for path in document_tests:
            assert not (path.parent / "__init__.py").exists()
