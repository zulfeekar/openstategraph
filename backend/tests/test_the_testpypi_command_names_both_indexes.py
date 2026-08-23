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
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Every markdown file a reader plausibly lands on first.
DOC_FILES = [
    REPO / "README.md",
    *sorted((REPO / "docs").glob("*.md")),
]

# A bare `--index-url https://test.pypi.org/simple/ ... "openstategraph...`
# with no `--extra-index-url` anywhere before the package name is the exact
# shape that fails. Match a pip install invocation naming test.pypi.org.
PIP_INSTALL_TESTPYPI = re.compile(
    r"pip install.{0,120}?test\.pypi\.org/simple/.{0,200}?openstategraph[^\s`\"]*",
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
            for match in PIP_INSTALL_TESTPYPI.finditer(collapsed):
                line = match.group(0)
                if "--extra-index-url" not in line:
                    offenders.append(f"{path.relative_to(REPO)}: {line!r}")

        assert not offenders, (
            "a TestPyPI install command with no --extra-index-url will fail "
            "on pydantic (or another real-PyPI-only dependency) with an "
            "error that blames the dependency instead of the missing "
            "index:\n" + "\n".join(offenders)
        )

    def test_the_readme_onramp_still_has_the_working_two_index_command(self) -> None:
        readme = (REPO / "README.md").read_text()
        collapsed = readme.replace("\n", " ")
        matches = [
            m.group(0)
            for m in PIP_INSTALL_TESTPYPI.finditer(collapsed)
        ]
        assert matches, "README no longer shows a TestPyPI install command at all"
        assert any("--extra-index-url https://pypi.org/simple/" in m for m in matches), (
            "README's TestPyPI command must carry "
            "--extra-index-url https://pypi.org/simple/"
        )
