"""The ninth line of `backend/README.md` is the first thing anybody runs.

Until docs-and-gaps/18 it was::

    pip install "openstategraph[ollama]"

and ``https://pypi.org/pypi/openstategraph/json`` answers **404**. The release
train (``docs/releasing.md``) stops at TestPyPI pending a human approval that
has never been clicked, so that command has never worked for anybody who did
not already have a checkout — and it fails in the reader's favour, because a
404 from pip looks like a typo rather than like a broken README.

`docs/adoption.md` said so correctly, four hundred lines into a different
document. The page a stranger lands on did not.

**What this module refuses to pin is the lazy fix.** A README that says "not
published yet" and stops is worse than the broken line, because the reader who
*does* have a way in is now given none. So the rule is that the first code
block stays copyable, and the shape it takes is decided by the one fact that
actually determines it — whether `backend/pyproject.toml` names a pre-release:

* **pre-release** (today, ``0.3.0rc7``) — the block routes through TestPyPI,
  names both indexes, and pins the version in full. All three are required and
  each fails differently: TestPyPI because PyPI has never heard of us;
  ``--extra-index-url`` because TestPyPI carries no ``pydantic`` 2.x and pip
  blames the dependency rather than the index (launch-readiness/21); the exact
  version because pip excludes pre-releases from an unpinned requirement,
  which is the same trap ``docs/building-an-atom.md`` records for a plugin's
  ``>=`` specifier.
* **final release** — the TestPyPI detour is no longer the honest answer, and
  this module goes red until the block is the plain ``pip install
  "openstategraph[…]"`` it should always have been.

That is the half a doc claim normally cannot have: a way to fail. The pinned
version tracks ``pyproject.toml`` rather than sitting in prose, because the
root README pinned ``0.3.0rc2`` and five release candidates went by without
anything noticing.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "backend" / "pyproject.toml"
BACKEND_README = REPO / "backend" / "README.md"

#: Every page that hands a reader a pinned install of *this* package. History
#: is deliberately absent — CHANGELOG.md and docs/decisions/ record what was
#: installed then, and rewriting those to satisfy a gate is how a record stops
#: being one.
PINNING_DOCS = (
    REPO / "README.md",
    BACKEND_README,
    *sorted((REPO / "docs").glob("*.md")),
)

PINNED = re.compile(r"openstategraph\[[a-z0-9,\-]+\]==([0-9][^\s`\"']*)")

FENCE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)


def version() -> str:
    return tomllib.loads(PYPROJECT.read_text())["project"]["version"]


def is_prerelease(v: str) -> bool:
    return bool(re.search(r"(rc|a|b)\d+$", v))


def first_code_block() -> str:
    found = FENCE.search(BACKEND_README.read_text())
    assert found, "backend/README.md has no code block at all"
    return found.group(1)


class TestTheFirstBlockIsCopyable:
    def test_it_is_an_install_command(self) -> None:
        """Not a `python` snippet, not prose — the thing a reader runs first."""
        assert "pip install" in first_code_block(), (
            "the first fenced block in backend/README.md is what a stranger "
            "copies before reading anything; it has stopped being an install"
        )

    def test_a_prerelease_routes_through_testpypi_with_both_indexes(self) -> None:
        if not is_prerelease(version()):
            return
        block = first_code_block()
        assert "test.pypi.org/simple/" in block, (
            f"{version()} is on TestPyPI and PyPI has never heard of this "
            "package, so the first command must name that index"
        )
        assert "--extra-index-url https://pypi.org/simple/" in block, (
            "TestPyPI carries no pydantic 2.x; without the second index pip "
            "fails on the dependency and never mentions the missing index"
        )

    def test_a_prerelease_is_pinned_in_full(self) -> None:
        """pip excludes pre-releases from an unpinned requirement."""
        if not is_prerelease(version()):
            return
        assert PINNED.search(first_code_block()), (
            "an unpinned requirement resolves to nothing while the only "
            "published versions are pre-releases"
        )

    def test_a_final_release_drops_the_detour(self) -> None:
        """The day the PyPI gate is approved, this goes red on purpose.

        A TestPyPI command left standing after a real release is the same
        defect in the other direction — a working line that is no longer the
        one a reader should copy.
        """
        if is_prerelease(version()):
            return
        block = first_code_block()
        assert "test.pypi.org" not in block, (
            f"{version()} is a final release; the first command should be the "
            "plain PyPI install, not the pre-release detour"
        )
        assert 'pip install "openstategraph[' in block


class TestTheReadmeSaysWhyBeforeItAsks:
    def test_the_unqualified_pypi_line_is_marked(self) -> None:
        """The lazy fix's mirror image: keeping the broken line unmarked.

        `pip install "openstategraph[…]"` may still appear — it is the shape
        the command takes after release, and hiding it would leave the page
        with no headline. It may not appear *unqualified*.
        """
        text = BACKEND_README.read_text()
        offenders = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(text.splitlines(), start=1)
            if re.search(r'^\s*pip install "openstategraph\[', line)
            and "once published" not in line
        ]
        assert offenders == [], (
            "a bare PyPI install of a package that is not on PyPI returns a "
            "404 the reader reads as their own mistake:\n" + "\n".join(offenders)
        )

    def test_it_names_the_gate_that_is_actually_shut(self) -> None:
        text = BACKEND_README.read_text()
        assert "not on PyPI" in text
        assert "releasing.md" in text, (
            "the reader deserves the page that says when this changes"
        )


class TestNoPinnedVersionOutlivesTheRelease:
    def test_every_documented_pin_is_this_version(self) -> None:
        """The root README sat on `0.3.0rc2` through five release candidates."""
        current = version()
        offenders: list[str] = []
        for path in PINNING_DOCS:
            if not path.is_file():
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                for found in PINNED.finditer(line):
                    if found.group(1) != current:
                        offenders.append(
                            f"{path.relative_to(REPO)}:{number} pins "
                            f"{found.group(1)}, shipped is {current}"
                        )
        assert offenders == [], (
            "a version pinned in prose has no way to fail; these have "
            "stopped tracking the wheel:\n" + "\n".join(offenders)
        )
