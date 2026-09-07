"""`docs/README.md` is the index. It has to be findable, and it has to be whole.

`docs-onramp/05`. Two failures, and they are opposite ends of one path.

**Findable.** `docs/README.md` is the best navigation artifact in the project —
one row per intent, one canonical page per row, plus an explicit statement of
which page is allowed to repeat another and why. `README.md` linked it **once**,
at line **792 of 829**, inside `## Contributing`, in a bullet list of repository
directories. A reader who wanted the documentation had to scroll past Docker,
the test suites, the architecture rules and *What had to be rebuilt* to be told
a documentation set existed; a reader who came to install something never got
there. Nothing was wrong with either document. The link was in the wrong place.

**Whole.** An index that omits a page is worse than no index, because a reader
who checks it and does not find something concludes it does not exist.
`docs/modules.md` landed on `docs-onramp/04` and was not in the table, which is
the ordinary way this goes: the page and its index row are written by different
edits, and only one of them is obviously required.

## Why the ceiling is a line number and not a section name

`test_the_front_door_stays_short.py` derives its boundary from a heading,
because what it measures is *where the stranger's path ends*, and that is a
structural fact the heading names. What this file measures is different: how
far a reader scrolls before the documentation is mentioned at all. That is a
distance, so it is a number — and a small one, because "linked somewhere on the
page" was true the whole time the defect existed.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
DOCS = REPO / "docs"
INDEX = DOCS / "README.md"

#: How far down `README.md` a reader may get before the documentation set is
#: named. 792 on 2026-09-05, of 829. The front page is 321 lines now and names
#: it inside the stranger's path; 60 is "on the first screen or two", which is
#: the property the ticket was actually about. Raising this is raising how long
#: a stranger reads before they know the docs exist.
INDEX_LINKED_BY_LINE = 60

#: `[text](target)` — the target half only.
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def targets(page: Path) -> set[str]:
    """Every relative link on `page`, anchors and query strings stripped."""
    found = set()
    for target in LINK.findall(page.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "#", "mailto:", "../../")):
            continue
        found.add(target.split("#", 1)[0])
    return found


def test_the_pages_were_actually_found() -> None:
    """A sweep over nothing passes."""
    assert INDEX.is_file() and README.is_file()
    assert len(list(DOCS.glob("*.md"))) > 20, "docs/ is smaller than this test assumes"


def test_the_front_door_names_the_index_on_the_first_screen() -> None:
    for number, line in enumerate(README.read_text(encoding="utf-8").splitlines(), start=1):
        if "docs/README.md" in line:
            assert number <= INDEX_LINKED_BY_LINE, (
                f"README.md first names the documentation index at line {number}, "
                f"past the recorded {INDEX_LINKED_BY_LINE}. It was line 792 of 829 "
                "before `docs-onramp/05`, which is the failure this pins: a reader "
                "who came to install something never reached it."
            )
            return
    raise AssertionError("README.md does not link docs/README.md at all")


def test_every_page_in_docs_is_one_hop_from_the_index() -> None:
    """The census's own rule: reachable from the index, in one hop.

    `docs/decisions/**` is deliberately excluded — it is an argument archive
    reached through the index's single `decisions/` row, and a row per file
    would make the index unreadable in service of a reader who is not lost.
    """
    linked = targets(INDEX)
    orphans = sorted(
        page.name
        for page in DOCS.glob("*.md")
        if page.name != "README.md" and page.name not in linked
    )
    assert orphans == [], (
        "these pages exist in docs/ and the index does not name them, so a "
        f"reader who checks the index concludes they do not exist: {orphans}"
    )


def test_the_index_names_no_page_that_is_gone() -> None:
    """The other direction, which is how an index teaches a reader it is stale."""
    missing = sorted(
        target for target in targets(INDEX) if not (DOCS / target).exists()
    )
    assert missing == [], f"docs/README.md links targets that do not exist: {missing}"
