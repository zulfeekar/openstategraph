"""A generated page says which commit it was generated from.

`docs-and-gaps/27`. `openwiki/.last-update.json` said `eee2779`, 2026-08-21 —
nine days and several hundred commits behind the tree, spanning the node-family
extraction, the run store, the dispatch registry and the run dock. That is not
the defect. Staleness here is **structural and expected**: `CLAUDE.md` already
records that "let OpenWiki regenerate" means a human runs it locally, because
the scheduled job has never produced a page.

The defect is the **silence**. `.last-update.json` is a dotfile a reader has no
reason to open, and no `openwiki/**` page carried a date, so a contributor
opening `how-to/extending.md` had nothing telling them they were reading a
snapshot of a tree that had moved. Every wrong sentence on those pages was a
*false statement*. With a stamp on it, the same sentence is a **dated** one,
and a dated claim is honest even when wrong.

## Where the stamp can live, given that a refresh overwrites the page

`CLAUDE.md` states the constraint and demonstrates it: a hand-edit inside the
OPENWIKI markers does not survive the next run, which is why the correction
block there lives *outside* them. `openwiki/**` has no outside — the generator
writes each page whole. So the honest answer is:

> **The stamp does not survive regeneration, and it is not supposed to.**

It is written after the fact by `scripts/stamp_wiki_freshness.py`, from the
values the generator itself recorded in `.last-update.json`. A refresh removes
every stamp — and a refresh is precisely the moment the stamps are all wrong
anyway, since they name the previous commit. This test then goes red, naming
the pages, and one command puts correct stamps back. The alternative designs
were both worse:

- **A stamp the generator writes.** We do not own the generator, so this is a
  feature request against somebody else's tool, and until it lands there is no
  stamp at all.
- **A stamp only in `.last-update.json`, plus a test.** That serves a
  contributor running the suite and nobody reading the page — which is the
  reader `27` is about. Kept as well, not instead: the values below are read
  from that file, so the page and the dotfile cannot disagree.

The values are **derived, never literalised**. Nothing in this file hardcodes a
sha or a date; it reads `.last-update.json` and asks whether the pages agree.
Refreshing the wiki and re-running the stamper therefore makes this file
correct again with no edit — the same construction rule
`test_no_document_repeats_a_retracted_claim.py` gives for reading `ci.yml`.

## What the stamp deliberately does not say

Not "this page is N days stale", and not a count of commits behind. Both are
numbers that are wrong one commit later, which is the failure this repository
has recorded most often. The stamp names the commit and the date and hands the
reader `git log <sha>..HEAD`; the arithmetic is the reader's, and it is right
every time it is done.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WIKI = REPO / "openwiki"
LAST_UPDATE = WIKI / ".last-update.json"

START = "<!-- FRESHNESS:START -->"
END = "<!-- FRESHNESS:END -->"

#: The one page that is not generated: `INSTRUCTIONS.md` is the brief handed
#: *to* OpenWiki, hand-written and never overwritten by a run. It has no
#: generation to stamp, so stamping it would be a claim about nothing. The
#: exclusion is exactly one path and this file asserts that, so widening it is
#: a diff somebody reads — the same mechanism the publishable gate uses for its
#: single content exclusion.
NOT_GENERATED = ("INSTRUCTIONS.md",)


def generated_pages() -> list[Path]:
    return sorted(
        page
        for page in WIKI.rglob("*.md")
        if page.relative_to(WIKI).as_posix() not in NOT_GENERATED
    )


def last_update() -> dict[str, str]:
    return json.loads(LAST_UPDATE.read_text(encoding="utf-8"))


def expected_head() -> str:
    """The short sha, the way a reader would write it in a `git log`."""
    return last_update()["gitHead"][:7]


def expected_date() -> str:
    """The date half of the ISO timestamp the generator recorded."""
    return last_update()["updatedAt"][:10]


def stamp_of(page: Path) -> str:
    """The stamp block, or the empty string if the page carries none."""
    text = page.read_text(encoding="utf-8")
    if START not in text or END not in text:
        return ""
    return text.split(START, 1)[1].split(END, 1)[0]


def test_the_generator_still_records_what_the_stamp_is_made_of() -> None:
    """Without this, a change in OpenWiki's own bookkeeping turns every
    assertion below into a comparison between two absences."""
    assert LAST_UPDATE.is_file()
    recorded = last_update()
    assert len(recorded["gitHead"]) >= 7
    assert recorded["updatedAt"][:4].isdigit()


def test_there_are_pages_to_check() -> None:
    """A glob that silently matches nothing would make this file green and
    empty, which is the one result it must never be able to give."""
    assert len(generated_pages()) >= 10


def test_the_only_unstamped_page_is_the_one_nobody_generates() -> None:
    assert NOT_GENERATED == ("INSTRUCTIONS.md",)
    assert (WIKI / "INSTRUCTIONS.md").is_file()


@pytest.mark.parametrize("page", generated_pages(), ids=lambda p: str(p.relative_to(WIKI)))
class TestEveryGeneratedPageIsDated:
    def test_it_carries_a_stamp(self, page: Path) -> None:
        assert stamp_of(page), (
            f"{page.relative_to(REPO)} carries no generated-from line, so a "
            "reader cannot tell it from a current one.\n"
            "If the wiki has just been regenerated this is expected — the "
            "generator writes each page whole and knows nothing about the "
            "stamp. Run `python3 scripts/stamp_wiki_freshness.py` to put it "
            "back from the values OpenWiki itself recorded in "
            "`openwiki/.last-update.json`."
        )

    def test_it_names_the_commit_it_was_generated_from(self, page: Path) -> None:
        assert expected_head() in stamp_of(page)

    def test_it_names_the_date_it_was_generated_on(self, page: Path) -> None:
        assert expected_date() in stamp_of(page)

    def test_it_tells_the_reader_how_to_refresh_it(self, page: Path) -> None:
        # A date with no remedy beside it is a complaint. The command is the
        # difference between "this is stale" and "this is stale, and here is
        # the one line that fixes it".
        assert "openwiki code --update" in stamp_of(page)

    def test_the_stamp_is_where_a_reader_lands(self, page: Path) -> None:
        """Above the first heading, so it is read before the content it is
        about rather than found afterwards."""
        text = page.read_text(encoding="utf-8")
        headings = [i for i, line in enumerate(text.splitlines()) if line.startswith("# ")]
        assert headings, f"{page.relative_to(REPO)} has no heading at all"
        stamp_line = text[: text.index(START)].count("\n")
        assert stamp_line < headings[0]

    def test_the_stamp_is_below_the_front_matter_it_would_otherwise_break(
        self, page: Path
    ) -> None:
        """A markdown blockquote inside a YAML block is not YAML. Pages that
        have front matter keep it parseable; pages that have none are stamped
        at the very top."""
        text = page.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            assert text.startswith(START)
            return
        closing = text.index("\n---\n", 3) + len("\n---\n")
        assert text.index(START) >= closing

    def test_the_stamp_states_no_arithmetic_that_goes_stale(self, page: Path) -> None:
        """"Nine days behind" is wrong tomorrow and "three hundred commits
        behind" is wrong on the next commit. The stamp names the commit and
        hands the reader the `git log`; nothing counts on its behalf."""
        stamp = stamp_of(page).lower()
        for phrase in ("days stale", "days behind", "commits behind", "days old"):
            assert phrase not in stamp
