"""`README.md` is the front door, and a front door has a length.

`docs-onramp/01`. Measured on 2026-09-05 from a fresh TestPyPI install of
`0.3.0rc14`, with only `README.md` open: the page was **829 lines** in 26
sections, and the stranger's path — install, first run, what to say to a coding
agent — was complete by line 177. The remaining 652 lines were addressed to
somebody who had already decided (`Developing on a checkout`, `Tests`,
`Docker`, `What had to be rebuilt`, `Architecture`, `Extension points`,
`Content-driven cards`, `Accessibility`, `Known limits`, `The compile seam`),
and the documentation index was not named until line **792 of 829**.

Every one of those sections was good and every one had a canonical home
already, which is why the fix was a move rather than a cut: they are in
`CONTRIBUTING.md` (the checkout, Docker, the architecture, the extension
points, the example workflows), `docs/what-is-this.md` (the comparison, the
known limits) and `docs/getting-started.md` (the provider table). Nothing was
deleted from the repository.

## What this file measures, and what it deliberately does not

Two numbers and one order:

1. **Where the stranger's path ends** — derived from the heading that ends it,
   never written as a literal. `STRANGER_PATH_ENDS_AT` is the *heading*, and
   the test asks the file where that heading is. An edit that adds thirty lines
   to § First run moves the answer, which is the whole point; an edit that
   renames the heading fails loudly rather than silently measuring nothing.
2. **The whole page's length**, as a ceiling and a ratchet at once — the same
   mechanism `test_module_size_ceiling.py` argues for at length. The ceiling
   decides that the front page has a budget; the exact number fires when it
   grows. Raising it is one keystroke, and what stops that being a formality is
   that the number sits beside the argument, so raising it lands in review next
   to a paragraph that has to still be true.
3. **The section order.** A reader scrolls; a page whose first heading after the
   pitch is `## Architecture` has no first glance whatever its length is. The
   order is asserted as a prefix — the sections before the stranger's path ends
   are fixed, and what comes after them is the author's business.

**What is deliberately not pinned is the prose.** Whether the install paragraph
is well written, how the pre-release detour is explained, which five rows the
"Where to read next" table carries — that is taste, and a test demanding
particular sentences would be a test of it. The rule is this repository's own:
pin the checkable claim, leave the argument alone.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"

#: The heading that begins the reference half. Everything above it is the
#: stranger's path; the line it sits on is therefore the measurement, and it is
#: resolved from the file rather than written down as a number.
STRANGER_PATH_ENDS_AT = "## The CLI at a glance"

#: The stranger's path must be readable in a sitting. 180 lines on 2026-09-05,
#: against 177 before the restructure — near-identical, and that is the finding
#: rather than a coincidence: the path was never the long part. What changed is
#: that it is now the *whole* first half instead of the first fifth, so a reader
#: who stops at the end of it has stopped at a deliberate place.
STRANGER_PATH_CEILING = 190

#: The whole page. 829 lines on 2026-09-05 before `docs-onramp/01`, 305 after.
#: The budget above the recorded figure is small on purpose — the failure this
#: file exists to prevent is accretion, and accretion arrives twenty lines at a
#: time. Two tables are irreducible and both are pinned elsewhere: the CLI table
#: (20 rows, held against argparse by `test_the_readme_a_stranger_lands_on.py`)
#: and the environment table. They are why the number is not lower.
LINE_CEILING = 330

#: In order, from the top. A prefix, not the full list.
OPENING_SECTIONS = (
    "## Install",
    "## First run",
    "## With your coding agent",
    "## The board",
    "## Building a new module",
    "## Where to read next",
    STRANGER_PATH_ENDS_AT,
)

HEADING = re.compile(r"^## .*$", re.M)


def lines() -> list[str]:
    return README.read_text(encoding="utf-8").splitlines()


def line_of(heading: str) -> int:
    """1-based line number of `heading`, or an assertion naming what was sought."""
    numbered = [n for n, line in enumerate(lines(), start=1) if line.strip() == heading]
    assert numbered, (
        f"README.md no longer carries the heading {heading!r}. If it was renamed, "
        "rename it here too — a heading this file cannot find is a measurement "
        "that silently stops happening."
    )
    assert len(numbered) == 1, f"{heading!r} appears {len(numbered)} times in README.md"
    return numbered[0]


def test_the_readme_was_actually_found() -> None:
    """A sweep over nothing passes."""
    assert README.is_file()
    assert len(lines()) > 100, "README.md is too short to be the front page"


class TestTheStrangersPathIsTheFirstThingOnThePage:
    def test_it_ends_where_the_heading_says_it_does(self) -> None:
        ends_at = line_of(STRANGER_PATH_ENDS_AT)
        assert ends_at <= STRANGER_PATH_CEILING, (
            f"the stranger's path now runs to line {ends_at} of README.md, past the "
            f"recorded {STRANGER_PATH_CEILING}. Either move what you added below "
            f"{STRANGER_PATH_ENDS_AT!r}, or raise the number here and say in the "
            "comment beside it why a first-time reader should read further before "
            "they have a running stack."
        )

    def test_the_opening_sections_are_in_order(self) -> None:
        headings = HEADING.findall(README.read_text(encoding="utf-8"))
        actual = tuple(h.strip() for h in headings[: len(OPENING_SECTIONS)])
        assert actual == OPENING_SECTIONS, (
            "README.md's opening sections are not the stranger's path in order.\n"
            f"  expected: {OPENING_SECTIONS}\n  found:    {actual}"
        )

    def test_the_documentation_index_is_named_inside_it(self) -> None:
        """It was named at line 792 of 829. That is the defect, in one number."""
        text = "\n".join(lines()[: line_of(STRANGER_PATH_ENDS_AT)])
        assert "docs/README.md" in text, (
            "README.md names the documentation index only below the stranger's "
            "path, which is where it sat before `docs-onramp/05`"
        )


class TestTheWholePageHasABudget:
    def test_it_is_under_the_ceiling(self) -> None:
        measured = len(lines())
        assert measured <= LINE_CEILING, (
            f"README.md is {measured} lines, over the recorded {LINE_CEILING}. "
            "The front page is a routing document: the section you are adding "
            "almost certainly belongs to CONTRIBUTING.md, docs/what-is-this.md "
            "or a page docs/README.md already indexes. If it genuinely belongs "
            "here, raise the number and put the argument next to it."
        )

    def test_the_contributor_sections_left_and_landed(self) -> None:
        """Moved, not deleted — so both halves of that are checked.

        Each of these is a section title that used to be a `##` on the front
        page and is now a heading on the page that owns its reader.
        """
        readme = README.read_text(encoding="utf-8")
        for heading, destination in (
            ("What had to be rebuilt", "CONTRIBUTING.md"),
            ("Extension points", "CONTRIBUTING.md"),
            ("Content-driven cards", "CONTRIBUTING.md"),
            ("The compile seam", "CONTRIBUTING.md"),
            ("What the canvas opens on", "CONTRIBUTING.md"),
            ("Accessibility", "CONTRIBUTING.md"),
            ("Why not the four visual tools", "docs/what-is-this.md"),
            ("Known limits", "docs/what-is-this.md"),
        ):
            assert f"## {heading}" not in readme, (
                f"'{heading}' is back on the front page; it belongs to {destination}"
            )
            assert f"# {heading}" in (REPO / destination).read_text(encoding="utf-8"), (
                f"'{heading}' left README.md and never arrived at {destination}"
            )
