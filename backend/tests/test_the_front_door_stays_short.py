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
#:
#: Raised from 190 to 200 the same day, by `docs-onramp/02`: the ratchet fired
#: on the sixteen lines that add the credential step between `init` and Run.
#: That is the one addition this budget exists to admit rather than refuse — a
#: path measured at 180 lines that ends in a 503 is shorter and worse. The next
#: edit that wants ten more lines does not get them for free.
#:
#: Raised from 200 to 230 on 2026-09-06, by `docs-onramp/14`, and it was sitting
#: exactly on 200 when that ticket arrived — the ratchet was already tight. The
#: twenty-seven lines bought are § Two surfaces, one API: that `/` is the
#: editor and `/chat` is the customer-facing app, that both are ordinary
#: clients of `/api`, and that `POST /api/runs/stream` is a stream anyone can
#: read frame by frame. The argument for spending a first-glance budget on it
#: is that a stranger deciding whether this fits their product is asking
#: exactly one question — *can I put my own UI on it?* — and the page's answer
#: was a "Where to read next" row that went via the adoption page. A shorter
#: page that never answers the question a reader came with is not cheaper.
#: 263 → 278 on 2026-09-07 for the second film, and it is the cheapest fifteen
#: lines on this page. § Two surfaces, one API told a reader that `/chat` is
#: the customer-facing app and then described `POST /api/runs/stream` — so the
#: sentence that matters most to somebody deciding whether to put this in front
#: of their own users was a claim with nothing behind it. Eighteen seconds of
#: the thing running is the evidence, and it sits in the section that makes the
#: claim rather than in the pitch, where it would have been a second film
#: nobody could tell apart from the first.
#:
#: 241 → 263 on 2026-09-07 for § The idea, and this budget is again the one
#: that decides it. The section is the mapping a reader needs before any other
#: sentence on the page means anything — canvas is a `StateGraph`, an Agent
#: node is `create_agent`, an edge back into an agent is a cycle — and it was
#: nowhere on the front door. A reader met "compiles to an ordinary LangGraph
#: object" in the pitch and then a `mkdir`. Twenty-two lines to stop every
#: later sentence being read on trust is the cheapest exchange on this page.
#:
#: Raised from 230 to 241 on 2026-09-07 for the product film, and this is the
#: budget it belongs in rather than the page total: the whole claim for putting
#: a video on the front door is that it shortens the stranger's path, so if it
#: could not be paid for here it should not be on the page at all. Forty
#: seconds answers "what is this" faster than any eleven lines of prose can,
#: and the reader who watches it arrives at § Install already knowing what they
#: are installing.
STRANGER_PATH_CEILING = 278

#: The whole page. 829 lines on 2026-09-05 before `docs-onramp/01`, 305 after.
#: The budget above the recorded figure is small on purpose — the failure this
#: file exists to prevent is accretion, and accretion arrives twenty lines at a
#: time. Two tables are irreducible and both are pinned elsewhere: the CLI table
#: (20 rows, held against argparse by `test_the_readme_a_stranger_lands_on.py`)
#: and the environment table. They are why the number is not lower.
#:
#: 330 → 360 on 2026-09-06 (`docs-onramp/14`), the same twenty-seven lines
#: passing through both budgets, because they were added inside the stranger's
#: path rather than below it. Nothing moved off the page to pay for them, and
#: that is stated rather than dressed up: this is a straight raise, and the
#: next section that wants one has to make its own case here.
#:
#: 389 → 404 on 2026-09-07, the same fifteen lines of the second film passing
#: through both budgets. The argument is made at `STRANGER_PATH_CEILING`.
#:
#: 367 → 389 on 2026-09-07, the same twenty-two lines of § The idea passing
#: through both budgets because they sit inside the stranger's path. The
#: argument is made at `STRANGER_PATH_CEILING`; it is not made twice here.
#:
#: 360 → 367 on 2026-09-07: eleven lines for the product film, minus four the
#: pitch gave back. It is the one addition that makes the page *shorter* to
#: read rather than longer — a stranger who watches forty seconds has the
#: answer to "what is this" that the paragraph above it spends four sentences
#: approaching, and can then skip to § Install. It carries no `## ` heading, so
#: the section order below is untouched: the film belongs to the pitch, not
#: between the pitch and the first command. The next raise still has to argue
#: for itself; "the last one was allowed" is not the argument.
LINE_CEILING = 404

#: In order, from the top. A prefix, not the full list.
OPENING_SECTIONS = (
    "## Install",
    # 2026-09-07. It sits between the command that installs and the command
    # that scaffolds, because it is what makes `init`'s output legible: a
    # reader who knows the canvas is a `StateGraph` reads every heading below
    # as a consequence, and a reader who does not takes the whole page on
    # trust. It is deliberately not first — a mapping is only interesting to
    # somebody who has decided to try the thing.
    "## The idea",
    "## First run",
    "## With your coding agent",
    "## The board",
    # `docs-onramp/14`. It sits after the two surfaces exist for the reader
    # (§ First run opens both) and before § Building a new module, which is
    # about extending the vocabulary rather than about consuming the product.
    "## Two surfaces, one API",
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
