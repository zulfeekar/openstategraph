"""`CONTRIBUTING.md` names a test-count gap. Measure it.

`stable-beta-public/04`. Both documents warn that `cd backend && pytest`
misses the root `pytest.ini`, and both quantify the miss. `README.md` goes
further and argues the quantity is the durable part: *"The gap is the number
worth carrying and the totals are not: it was 49 measured on 2026-08-16 and
49 again on 2026-08-30, with the suite more than doubled in between."*

Measured 2026-09-04 it was **57**. The two identical readings were not
evidence of stability — they were two hand measurements fourteen days apart
on a number nothing was watching, and the argument built on them was the most
confident sentence in the paragraph. Which is this repository's own rule
about a number in prose, committed by the paragraph making the case for
carrying one.

## What the gap actually is

`pytest.ini` declares `testpaths = backend workflows/chinook-assistant`. From
`backend/` that file is never read, so the second path is dropped whole and
nothing else changes — the gap **is** the curated example package's own test
count, not a subset of it and not "the `workflows/` half". `workflows/` as a
whole is deliberately unswept (`test_collection_policy.py` pins that), and
`CONTRIBUTING.md` said "the entire `workflows/` half" until this ticket, which
would have made the gap far larger than either document's number.

So the measurement here is one collection of `workflows/chinook-assistant`,
in a subprocess, compared against the figure the documents print. Collecting
the whole suite twice would measure the same thing for twenty times the
runtime.

## One page states it now, and that is the point of `docs-onramp/01`

Both `README.md` and `CONTRIBUTING.md` carried the sentence when this file was
written, and `test_the_two_pages_agree` existed because they had already
disagreed about the *shape* of the gap. `README.md` § Tests was one of the
sections addressed to a reader who has already decided, and it moved whole to
`CONTRIBUTING.md`, which is where the test gate is argued. So there is one
statement of the fact instead of two, the duplication that produced the
original disagreement is gone, and `PAGES` is a tuple rather than a literal so
a second page restating it is one line away from being measured too — but
nothing restates it today, and `test_the_two_pages_agree` says so rather than
passing vacuously.

## Why the number stays in the prose at all

The alternative — delete it, as `docs/mcp.md`'s tool counts were deleted on
this same ticket — is wrong here, because a warning without a magnitude does
not warn: "you will run fewer tests" is advice nobody acts on. A count is
allowed to stand when something measures it, and this is that something.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TESTS = ROOT / "workflows" / "chinook-assistant"
#: Every page that states the gap. `README.md` stated it too until
#: `docs-onramp/01` moved § Tests to `CONTRIBUTING.md`.
PAGES = (ROOT / "CONTRIBUTING.md",)

#: The sentence shape both pages use. The bold is theirs; the digits are what
#: this file checks.
GAP_CLAIM = re.compile(r"runs \*\*(\d+)\*\* fewer tests")


def _collected_in_the_example_package() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            str(EXAMPLE_TESTS),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"^(\d+) tests collected", result.stdout, re.MULTILINE)
    assert match, (
        "could not read a collection count out of pytest's own output; the gap "
        f"cannot be measured.\nstdout:\n{result.stdout[-2000:]}"
    )
    return int(match.group(1))


def test_the_pages_still_state_a_gap() -> None:
    """The guard: if either page rewords the sentence away, the assertion below
    silently stops checking anything."""
    for page in PAGES:
        assert GAP_CLAIM.search(page.read_text(encoding="utf-8")), (
            f"{page.name} no longer states the collection gap in the shape this "
            "test reads; either restore it or retire this file deliberately."
        )


def test_the_documented_gap_is_the_measured_one() -> None:
    measured = _collected_in_the_example_package()
    wrong = {}
    for page in PAGES:
        stated = int(GAP_CLAIM.search(page.read_text(encoding="utf-8")).group(1))
        if stated != measured:
            wrong[page.name] = stated
    assert not wrong, (
        f"`cd backend && pytest` misses {measured} tests today, and these pages "
        f"say otherwise: {wrong}. Update the sentence — the gap is the curated "
        "example package's own test count."
    )


def test_every_page_that_states_it_states_the_same_gap() -> None:
    """One fact, however many documents. They disagreed on the *shape* of it —
    one said the curated example package, the other said the entire
    `workflows/` tree — which is how one of them came to be wrong about
    something neither had measured.

    `docs-onramp/01` left one page stating it, so this is a one-element check
    today. It is kept rather than retired because the cheapest way to reopen
    the original defect is for a second page to restate the number, and this
    is the assertion that would catch it the moment `PAGES` grows.
    """
    stated = {
        page.name: GAP_CLAIM.search(page.read_text(encoding="utf-8")).group(1) for page in PAGES
    }
    assert len(set(stated.values())) == 1, f"these pages state different gaps: {stated}"
    assert len(stated) == len(PAGES), "a page in PAGES no longer states the gap at all"
