"""`README.md`'s onramp, held against the software it describes.

`stable-beta-public/05`. The README is the page a public visitor reads before
any other, and until this file it was the only such page with no gate on it at
all: `test_documented_cli_surface.py` holds `docs/cli.md`,
`test_documented_patrol_board_surface.py` holds `docs/the-patrol-board.md`,
`test_the_first_command_a_stranger_copies.py` holds `backend/README.md`'s first
command — and the front page could name a verb argparse has never heard of, or
link a file that moved, and nothing would say so.

Three things are pinned here, and each one is a claim a stranger *acts on*
rather than reads:

1. **Every relative link resolves.** A dead link on the front page teaches a
   reader the whole repository is stale, which is the same lesson
   `test_openwiki_links_resolve.py` exists to prevent one directory over.
   GitHub-relative badge targets (`../../actions/...`) are the one exclusion:
   they resolve on GitHub and name no file here.

2. **The CLI table and argparse agree, in both directions.** The direction that
   costs a reader a failed paste is a documented verb that does not exist; the
   direction a page drifts in on its own is a verb added to the parser whose
   row nobody writes. `docs/cli.md` learned both halves in
   `launch-readiness/196`; the README's shorter table gets the same treatment
   rather than a summary nobody checks.

3. **The `init` table names the files `init` actually writes.** The README
   promises a stranger three skills and four agent config files by name. Those
   are two lists that live in the code (`BUNDLED_SKILLS`, `AGENT_FILES`) and
   have both grown once already, so a prose copy of either has no way to fail.

**What is deliberately not pinned** is the prose. What each verb *means*, why
the pre-release detour exists, whether the install paragraph is well written —
that is an author's wording, and a test demanding particular sentences would be
a test of taste. The rule this file follows is the repository's own: pin the
checkable claim, leave the argument alone.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from openstategraph import cli
from openstategraph.agent_config import AGENT_FILES
from openstategraph.bundled_skills import BUNDLED_SKILLS

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"

#: `[text](target)` — the target half only.
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

#: The CLI table's rows: `| [`verb`](docs/cli.md#anchor) | … |`. `export plugin`
#: is the one two-word entry, which is why the group is not a bare word.
TABLE_ROW = re.compile(r"^\|\s*\[`([a-z][a-z -]*)`\]\(docs/cli\.md#[^)]+\)\s*\|", re.M)

#: `openstategraph <verb>` where a reader would *type* it — at the start of a
#: line in a fenced block, or opening a backticked span in prose. Anchored
#: rather than bare, because `from openstategraph import load_workflow` is the
#: first code the page shows and `import` is not a verb.
COMMAND_IN_PROSE = re.compile(r"(?:^|`|\$ )openstategraph ([a-z][a-z-]*)", re.M)

#: Badge targets that resolve on GitHub and name nothing in the checkout.
GITHUB_RELATIVE = "../../"


def readme() -> str:
    return README.read_text(encoding="utf-8")


def real_verbs() -> set[str]:
    """Every top-level subcommand argparse accepts, from the real parser."""
    for action in cli.build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("the CLI parser has no subcommands at all")


def tabled_verbs() -> set[str]:
    """The first word of every verb the README's CLI table links."""
    return {row.split()[0] for row in TABLE_ROW.findall(readme())}


def test_the_readme_was_actually_found() -> None:
    """The guard every doc gate needs: if the page moves or empties, the rules
    below start passing over nothing."""
    text = readme()
    assert len(text) > 10_000, "README.md is too short to be the front page"
    assert len(LINK.findall(text)) > 20
    assert len(tabled_verbs()) > 10, "the CLI table scan found almost nothing"


class TestEveryLinkGoesSomewhere:
    def test_every_relative_link_resolves(self) -> None:
        missing: list[str] = []
        for number, line in enumerate(readme().splitlines(), start=1):
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                if target.startswith(GITHUB_RELATIVE):
                    continue
                path = target.split("#", 1)[0]
                if path and not (REPO / path).exists():
                    missing.append(f"{number}: {target}")
        assert missing == [], (
            "README.md links to paths that do not exist — a reader following "
            "one learns the page is stale before they learn anything else:\n"
            + "\n".join(missing)
        )

    def test_the_pages_the_onramp_hands_off_to_are_linked(self) -> None:
        """The README's job is to route, not to restate.

        Each of these owns a section the front page deliberately summarises in
        a paragraph; dropping the link would leave the summary as the only
        account, which is how two descriptions of one thing start.
        """
        text = readme()
        for page in (
            "docs/cli.md",
            "docs/the-patrol-board.md",
            "docs/the-openstategraph-skill.md",
            "docs/building-an-atom.md",
            "docs/mcp.md",
            "docs/what-is-this.md",
            "docs/releasing.md",
        ):
            assert page in text, f"the README no longer routes a reader to {page}"


class TestTheCliTableAndArgparseAgree:
    @pytest.mark.parametrize("verb", sorted(tabled_verbs()))
    def test_every_tabled_verb_is_real(self, verb: str) -> None:
        assert verb in real_verbs(), (
            f"the README's CLI table offers `openstategraph {verb}`, which "
            "argparse rejects — a reader's first paste fails"
        )

    def test_every_real_verb_is_tabled(self) -> None:
        missing = sorted(real_verbs() - tabled_verbs())
        assert missing == [], (
            "these verbs exist and the README's 'CLI at a glance' names none "
            f"of them: {missing}. A verb is added to the parser in the commit "
            "that adds the behaviour; the table is a separate act of will, "
            "which is the direction this page drifts in on its own."
        )

    def test_every_fenced_openstategraph_command_is_real(self) -> None:
        """The verbs in the runnable blocks, not only the ones in the table."""
        bad = [
            found
            for found in re.findall(COMMAND_IN_PROSE, readme())
            if found not in real_verbs()
        ]
        assert bad == [], (
            f"the README tells a reader to type commands argparse rejects: {sorted(set(bad))}"
        )


class TestTheInstallLineIsTheOneThatWorks:
    def test_the_uv_line_carries_all_three_prerelease_flags(self) -> None:
        """Each flag fails differently, and two of them fail silently.

        `--extra-index-url` because TestPyPI carries no `pydantic` 2.x and pip
        blames the dependency rather than the missing index;
        `--index-strategy unsafe-best-match` because `uv` will not otherwise
        take a package from one index and its dependencies from another; the
        pinned version because pre-releases are excluded from an unpinned
        requirement. The pin itself is held against `pyproject.toml` by
        `test_the_first_command_a_stranger_copies.py`.
        """
        text = readme()
        assert "uv tool install" in text, (
            "the owner's install line is `uv tool install`; the README no "
            "longer shows it"
        )
        for flag in (
            "--index-url https://test.pypi.org/simple/",
            "--extra-index-url https://pypi.org/simple/",
            "--index-strategy unsafe-best-match",
        ):
            assert flag in text, f"the uv install line has lost {flag}"

    def test_it_says_plainly_that_this_is_a_prerelease(self) -> None:
        text = readme()
        assert "TestPyPI" in text
        assert "pre-release" in text, (
            "a reader pasting an index URL deserves to be told why, in the "
            "words they would search for"
        )


class TestTheInitTableNamesWhatInitWrites:
    def test_every_agent_config_file_is_named(self) -> None:
        text = readme()
        missing = [path for _, path, _ in AGENT_FILES if f"`{path}`" not in text]
        assert missing == [], (
            f"`init` writes these and the README's table names none of them: {missing}"
        )

    def test_the_count_of_agent_files_is_not_a_number_in_prose_alone(self) -> None:
        """Four files, named. The word may stay; the names are the pin."""
        assert len(AGENT_FILES) == 4, (
            "AGENT_FILES has changed size; the README says 'four agent config "
            "files' and the row above lists them — update both together"
        )

    def test_every_bundled_skill_is_reachable_from_the_page(self) -> None:
        """The README need not list all three by name — it says *three* and
        points at the sheet — but the one a stranger is told to invoke must be
        named by the path `init` really writes it to."""
        text = readme()
        assert "openstategraph" in BUNDLED_SKILLS
        assert ".claude/skills/openstategraph/" in text, (
            "the README tells a stranger to say 'use OpenStateGraph' and never "
            "says where the sheet that answers lands"
        )
        assert ".agents/skills/" in text, (
            "both skill roots are written, and an agent that scans only the "
            "second would look like it has no skill at all"
        )
        assert "three skills" in text, (
            f"`init` writes {len(BUNDLED_SKILLS)} skills; the README's table "
            "no longer agrees with BUNDLED_SKILLS"
        )
        assert len(BUNDLED_SKILLS) == 3
