"""The naive TestPyPI install command fails, misleadingly (launch-readiness/21).

Found by the `launch-readiness/12` stranger run and confirmed live in this
session, in a throwaway `/tmp` venv:

    $ pip install --index-url https://test.pypi.org/simple/ \\
          "openstategraph[server]==0.3.0rc2"
    ERROR: Could not find a version that satisfies the requirement
           pydantic<3,>=2.9 (from openstategraph) (from versions: 1.4a1, 1.5a1)

TestPyPI does not carry `pydantic` 2.x (or most of this project's other
dependencies), so `--extra-index-url https://pypi.org/simple/` is mandatory.
pip's error names `pydantic`, never the missing index, so a reader's obvious
conclusion is "this package depends on a pydantic that does not exist" — a
bug in us — rather than "the index I was told to use cannot serve
dependencies".

`launch-readiness/19` already put a correct two-index command into the
README's onramp. This test pins it: any edit that drops `--extra-index-url`,
or that adds a *new* single-index TestPyPI command somewhere in the docs
tree, goes red instead of silently reopening the same failure for the next
reader.

**The onramp is no longer where that command lives** (`stable-beta-public/37`).
`0.3.0rc18` was published to PyPI, so the README installs with no index flags
and the TestPyPI form belongs to `docs/releasing.md`, where the rehearsal is.
The corpus rule is untouched by that — it was always about every page in the
tree, and the rehearsal's own command has to be as correct as the onramp's
was.

**`uv` joined the pattern in `stable-beta-public/05`**, which made the
README's onramp `uv tool install` rather than `pip install` — the tool form,
because the editor is a developer tool installed once and pointed at any
project. The regex said `pip install` literally and so went red on a README
that had *gained* a correct command, which is the wrong failure: the defect
this file guards is a TestPyPI install with one index, and it is exactly as
misleading under `uv` as under pip. So the installer half is now a small
alternation, and widening it strengthened the first rule as a side effect —
`uv tool install` / `uv pip install` lines in the docs tree were invisible to
it before. `uv` needs a *third* flag (`--index-strategy unsafe-best-match`)
that pip does not; that one is a claim about one page rather than a rule about
the corpus, and `test_the_readme_a_stranger_lands_on.py` is still where it is
held — asserting its **absence** from the README's block since
`stable-beta-public/37`, for the reason above.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Every markdown file a reader plausibly lands on first. `backend/README.md`
# joined the list with docs-and-gaps/18, which put the two-index command into
# its opening block — the one page in the tree whose first line is an install.
DOC_FILES = [
    REPO / "README.md",
    REPO / "backend" / "README.md",
    *sorted((REPO / "docs").glob("*.md")),
]

# A bare `--index-url https://test.pypi.org/simple/ ... "openstategraph...`
# with no `--extra-index-url` anywhere before the package name is the exact
# shape that fails. Match any install invocation naming test.pypi.org —
# `pip install`, `uv pip install` or `uv tool install`, which are the three
# spellings this repository's pages actually hand a reader.
INSTALLER = r"(?:pip install|uv tool install|uv pip install)"
INSTALL_TESTPYPI = re.compile(
    INSTALLER + r".{0,160}?test\.pypi\.org/simple/.{0,240}?openstategraph[^\s`\"]*",
)


class TestEveryTestPyPICommandCarriesTheExtraIndex:
    def test_no_doc_shows_a_single_index_testpypi_install(self) -> None:
        offenders: list[str] = []
        for path in DOC_FILES:
            if not path.is_file():
                continue
            text = path.read_text()
            # Commands are sometimes wrapped across lines, either with a `\`
            # shell continuation or plain markdown paragraph wrapping;
            # collapse all newlines before scanning so a multi-line command
            # is seen as one.
            collapsed = text.replace("\n", " ")
            for match in INSTALL_TESTPYPI.finditer(collapsed):
                line = match.group(0)
                if "--extra-index-url" not in line:
                    offenders.append(f"{path.relative_to(REPO)}: {line!r}")

        assert not offenders, (
            "a TestPyPI install command with no --extra-index-url will fail "
            "on pydantic (or another real-PyPI-only dependency) with an "
            "error that blames the dependency instead of the missing "
            "index:\n" + "\n".join(offenders)
        )

    def test_the_rehearsal_form_still_exists_where_it_belongs(self) -> None:
        """`stable-beta-public/37` moved this claim off the front page.

        It used to be about `README.md`, and had to be: a stranger installing
        this package went to TestPyPI, so the front page owed them the
        two-index command. `0.3.0rc18` is on PyPI, the README's install line
        names no index at all, and requiring a TestPyPI command there would
        require the page to keep a detour nobody should take.

        The command itself has not stopped existing — the release train still
        rehearses from TestPyPI before anything reaches PyPI — so the claim
        moves to the page that owns the rehearsal rather than being deleted.
        The corpus rule above is unchanged and now covers it.
        """
        releasing = (REPO / "docs" / "releasing.md").read_text()
        collapsed = releasing.replace("\n", " ")
        matches = [m.group(0) for m in INSTALL_TESTPYPI.finditer(collapsed)]
        assert matches, (
            "docs/releasing.md no longer shows the TestPyPI rehearsal install "
            "at all, and it is the last page that owns one"
        )
        assert any("--extra-index-url https://pypi.org/simple/" in m for m in matches), (
            "the rehearsal's TestPyPI command must carry "
            "--extra-index-url https://pypi.org/simple/"
        )

    def test_the_front_page_sends_nobody_to_testpypi(self) -> None:
        """The other half of the move, so the detour cannot come back quietly."""
        readme = (REPO / "README.md").read_text()
        assert "test.pypi.org" not in readme, (
            "the README routes a reader through TestPyPI; this distribution "
            "is on PyPI and the rehearsal index carries older builds"
        )
