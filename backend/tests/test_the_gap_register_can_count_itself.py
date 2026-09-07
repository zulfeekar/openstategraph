"""The gap register's table is derived from its own entries, or it is a story.

`docs-and-gaps/28`. The register printed a per-theme totals table twenty lines
under a sentence claiming totals were "no longer printed here, and that is
deliberate", and shipped two `grep` commands for auditing it that returned 40
entries against a table summing to 45 and one blocker against three. The
commands existed to be trusted *instead* of reading the file, which is what a
release decision does with them.

The table is now derivable in full: an entry is a bold id at the start of a
line (`**PK-01 — …`, optionally struck through when closed), its theme is the
`## A. …` heading above it and its verdict is the `### …` heading above that.
This walks the file the same way and fails when the table disagrees.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

REGISTER = Path(__file__).resolve().parents[2] / "docs" / "decisions" / "gap-register.md"

ENTRY = re.compile(r"^~*\*\*[A-Z]{2,3}-[0-9]{2}")
THEME = re.compile(r"^## ([A-F])\. ")
VERDICT = re.compile(r"^### (.+)")

#: The table's columns, in the order the page prints them.
COLUMNS = ("Blocks 1.0", "Should precede public launch", "Fine to carry")


def _census() -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    theme = verdict = None
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        heading = THEME.match(line)
        if heading:
            theme, verdict = heading.group(1), None
            continue
        heading = VERDICT.match(line)
        if heading and theme:
            verdict = heading.group(1).strip()
        if theme and verdict and ENTRY.match(line):
            counts[(theme, verdict)] += 1
    return dict(counts)


def _table() -> dict[str, tuple[int, ...]]:
    rows: dict[str, tuple[int, ...]] = {}
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| ([A-F])\. .*?\|(.+)\|\s*$", line)
        if match:
            cells = [cell.strip() for cell in match.group(2).split("|")]
            rows[match.group(1)] = tuple(int(cell) for cell in cells if cell.isdigit())
    return rows


def test_both_halves_were_actually_found() -> None:
    """Without this, a renamed heading compares two empty dicts forever."""
    assert len(_table()) == 6, _table()
    assert sum(_census().values()) > 40


def test_every_theme_row_matches_the_entries_under_it() -> None:
    census = _census()
    for theme, row in sorted(_table().items()):
        total, *by_verdict = row
        counted = [census.get((theme, column), 0) for column in COLUMNS]
        assert by_verdict == counted, (
            f"gap-register.md's row for theme {theme} says {by_verdict} across "
            f"{COLUMNS}, and the entries under those headings count {counted}"
        )
        assert total == sum(counted), (
            f"theme {theme}'s total column says {total}; its own verdict "
            f"columns sum to {sum(counted)}"
        )


def test_the_totals_the_page_prints_in_its_theme_headings_agree_too() -> None:
    """`## B. Packaging & release (10)` is a third copy of the same number."""
    text = REGISTER.read_text(encoding="utf-8")
    census = _census()
    for theme, printed in re.findall(r"^## ([A-F])\. .*\((\d+)\)", text, re.MULTILINE):
        counted = sum(n for (t, _), n in census.items() if t == theme)
        assert int(printed) == counted, (
            f"the heading for theme {theme} prints ({printed}) and carries "
            f"{counted} entries"
        )
