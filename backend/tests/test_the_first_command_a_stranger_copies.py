"""The ninth line of `backend/README.md` is the first thing anybody runs.

Until docs-and-gaps/18 it was::

    pip install "openstategraph[ollama]"

and ``https://pypi.org/pypi/openstategraph/json`` answered **404** — the
release train (``docs/releasing.md``) stopped at TestPyPI pending a human
approval nobody had clicked, so that command had never worked for anybody who
did not already have a checkout, and it failed in the reader's favour, because
a 404 from pip looks like a typo rather than like a broken README. The name
resolves now (``0.3.0rc18``, published by hand); the unpinned line above still
does not, for the different reason ``TestTheReadmeSaysWhyBeforeItAsks`` holds.

`docs/adoption.md` said so correctly, four hundred lines into a different
document. The page a stranger lands on did not.

**What this module refuses to pin is the lazy fix.** A README that says "not
published yet" and stops is worse than the broken line, because the reader who
*does* have a way in is now given none. So the rule is that the first code
block stays copyable, and the shape it takes is decided by the one fact that
actually determines it — whether `backend/pyproject.toml` names a pre-release:

* **pre-release** (today) — the block pins the version in full, because pip
  excludes pre-releases from an unpinned requirement: the same trap
  ``docs/building-an-atom.md`` records for a plugin's ``>=`` specifier.
* **final release** — the pin is no longer the honest answer, and this module
  goes red until the block is the plain ``pip install "openstategraph[…]"`` it
  should always have been.

**Two of the three requirements above were retired by
``stable-beta-public/37``, and the reason is worth keeping.** Until
``0.3.0rc18`` the block also had to name TestPyPI and carry
``--extra-index-url`` — the first because PyPI had never heard of this package,
the second because TestPyPI carries no ``pydantic`` 2.x and pip blames the
dependency rather than the index (launch-readiness/21). Publishing a release
candidate to PyPI retired both at once, and left the third standing on its own:
"pre-release" is a statement about a version, "not on the default index" was a
statement about an upload, and they had simply never disagreed before.

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

    def test_no_command_here_names_an_index_at_all(self) -> None:
        """`stable-beta-public/37` inverted this, and the inversion is the point.

        This asserted the opposite until `0.3.0rc18`: a pre-release *had* to
        name TestPyPI, because PyPI had never heard of this package and the
        second index was mandatory on top of that. Both facts were true and
        the assertion was right.

        Publishing `0.3.0rc18` to PyPI retired them together. A reader pasting
        `--index-url https://test.pypi.org/simple/` now reaches an index that
        does not carry the build this page is about, and gets it from a page
        whose whole job is the first command that works — which is the same
        defect this module was opened for, pointing the other way.
        """
        block = first_code_block()
        assert "index-url" not in block and "test.pypi.org" not in block, (
            "the first command routes through an index; this distribution is "
            f"on PyPI, which pip reaches with no flags:\n{block}"
        )

    def test_a_prerelease_is_pinned_in_full(self) -> None:
        """pip excludes pre-releases from an unpinned requirement."""
        if not is_prerelease(version()):
            return
        assert PINNED.search(first_code_block()), (
            "an unpinned requirement resolves to nothing while the only "
            "published versions are pre-releases"
        )

    def test_a_final_release_drops_the_pin(self) -> None:
        """The day a final release ships, this goes red on purpose.

        The pin is the pre-release's cost, exactly as the index flags were
        TestPyPI's, and a pin left standing after a final release is the same
        defect the flags became: a working line that is no longer the one a
        reader should copy, and that quietly freezes them on one build.
        """
        if is_prerelease(version()):
            return
        block = first_code_block()
        assert not PINNED.search(block), (
            f"{version()} is a final release; the first command should be the "
            "plain install, not a version somebody has to keep editing"
        )
        assert 'pip install "openstategraph[' in block


class TestTheReadmeSaysWhyBeforeItAsks:
    def test_the_unpinned_line_is_marked(self) -> None:
        """The lazy fix's mirror image: keeping the not-yet-working line unmarked.

        `pip install "openstategraph[…]"` may still appear — it is the shape
        the command takes once a final release exists, and hiding it would
        leave the page with no headline. It may not appear *unqualified*: an
        unpinned requirement still resolves to nothing while every published
        version is a pre-release, and pip reports that as a package it cannot
        find rather than as a candidate it skipped.

        The marker word moved with the fact (`stable-beta-public/37`). It was
        "once published", because the package was on no index a reader could
        reach; it is "final release" now, because the package is on PyPI and
        the only thing still missing is a version without an `rc` in it.

        Guarded the same way `test_a_final_release_drops_the_pin` is: once
        `0.3.0` ships there is no pre-release left to explain, and demanding
        "final release" in an unpinned line that final release itself made
        correct would be requiring a page to explain a problem it no longer
        has.
        """
        if not is_prerelease(version()):
            return
        text = BACKEND_README.read_text()
        offenders = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(text.splitlines(), start=1)
            if re.search(r'^\s*pip install "openstategraph\[[a-z0-9,\-]+\]"', line)
            and "final release" not in line
        ]
        assert offenders == [], (
            "an unpinned install resolves to nothing while every published "
            "version is a pre-release, and pip calls that a missing "
            "package:\n" + "\n".join(offenders)
        )

    def test_it_says_what_the_pin_is_for(self) -> None:
        """Rewritten by `stable-beta-public/37`, which retired what it asked for.

        This required the words "not on PyPI", and that sentence was the honest
        account of the page for as long as it was true. `0.3.0rc18` is on PyPI,
        so requiring the claim would be requiring a false one — the page still
        owes a reader the reason its command is not the plain two words, and
        the reason is now the pre-release.

        Same guard as its sibling above: once there is no pre-release, keeping
        the word "pre-release" in the page to satisfy this assertion would be
        writing a false explanation for a problem the page no longer has.
        """
        text = BACKEND_README.read_text()
        assert "not on PyPI" not in text, (
            "this distribution is on PyPI; the page still says otherwise"
        )
        if not is_prerelease(version()):
            return
        assert "pre-release" in text, (
            "the pin is the pre-release's cost and the page never says so"
        )
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


#: The README's version badge, whose text is a literal inside a shields.io URL
#: — `-` doubled and a space written `%20`, which is shields' own escaping.
BADGE = re.compile(r"img\.shields\.io/badge/version-(?P<text>[^-][^/]*?)-informational\.svg")


def badge_text(version: str) -> str:
    """What the badge must read for `version` — shields' escaping, applied once."""
    return version.replace("-", "--").replace(" ", "%20")


class TestTheVersionBadgeIsNotProse:
    """stable-beta-public/33.

    The badge read `0.3.0 unreleased` while `pyproject.toml` said `0.3.0rc17`
    and TestPyPI listed it — the first line of the front page, wrong, for the
    same reason the root README sat on `0.3.0rc2` through five candidates: a
    version written into prose has no way to fail. `scripts/prepare_release.py`
    rewrites it now, from the version it is bumping; this is the half that
    fails if anybody bumps by hand.
    """

    def test_the_badge_reads_the_version_that_ships(self) -> None:
        found = BADGE.search((REPO / "README.md").read_text())

        assert found is not None, "the README has no version badge to check"
        assert found.group("text") == badge_text(version()), (
            f"the badge says {found.group('text')!r}; "
            f"backend/pyproject.toml ships {version()}"
        )

    def test_the_release_script_is_what_keeps_it_current(self) -> None:
        """Derived, not remembered — `prepare_release.py` rewrites both.

        Called on a sample rather than on the real page, so this stays a test
        of the substitution and not a second copy of the version.
        """
        import sys

        sys.path.insert(0, str(REPO / "scripts"))
        from prepare_release import restate_version

        sample = (
            "[![Version](https://img.shields.io/badge/version-0.1.0-informational.svg)]\n"
            '    "openstategraph[server,ollama]==0.1.0"\n'
        )

        rewritten = restate_version(sample, "9.9.9rc1")

        assert badge_text("9.9.9rc1") in rewritten
        assert "openstategraph[server,ollama]==9.9.9rc1" in rewritten
        assert "0.1.0" not in rewritten
