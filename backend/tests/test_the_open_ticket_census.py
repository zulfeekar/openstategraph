"""What counts as an open ticket, pinned in one place.

Two scripts read the same ticket headers and must agree about what "open"
means: the ledger asks whether the tickets and git agree, the census asks what
is left. When they disagreed, a ticket could be absent from the work list and
still be reported as drift — which reads to a session as a bookkeeping error
rather than as unfinished work.

The word this file exists for is `partially`. It means the shipped work is real
but the reported symptom survives, so the ticket still has a claim on somebody
— and it *contains the substring* `resolved`, so any check that merely looks
for closing words closes a live ticket. That is not hypothetical: it is the
misreading that let twenty tickets, one of them a data-loss blocker, sit at
`Status: open` for work that had already shipped and passed CI, and the reason
a ticket header carries a single status word rather than a phrase.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ticket_census.py"

_spec = importlib.util.spec_from_file_location("ticket_census", _SCRIPT)
census_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(census_mod)


@pytest.mark.parametrize(
    "status",
    [
        "open",
        "partially",
        "partially resolved",
        "partially resolved · needs a second pass",
        "in progress",
        "(none)",
    ],
)
def test_these_statuses_are_open(status: str) -> None:
    assert census_mod.is_open(status), f"{status!r} should count as open"


@pytest.mark.parametrize(
    "status",
    [
        "resolved",
        "closed",
        "done",
        "superseded",
        "withdrawn",
        "rejected",
        "moved to workflow-gallery/12",
        "merged into production-ready/46",
        "backlog",
    ],
)
def test_these_statuses_are_closed(status: str) -> None:
    assert not census_mod.is_open(status), f"{status!r} should not count as open"


def test_partially_wins_over_the_closing_word_it_contains() -> None:
    """The whole point, stated as its own case so a regression names itself."""
    assert "resolved" in "partially resolved"
    assert census_mod.is_open("partially resolved")


def test_a_judgement_ticket_is_never_dispatched_unattended() -> None:
    """A ticket that ends in a decision belongs to the owner, not to a session.

    Ranking them last is a convenience; naming them is the safety. An
    unattended session handed a `question` ticket will answer it, and an
    answered question looks exactly like a resolved one.
    """
    assert census_mod.OWNER_KINDS == {"question", "grilling", "design", "decision"}


def test_the_census_reads_real_tickets() -> None:
    """A smoke test, because the parsing is regex over hand-written markdown.

    Deliberately asserts nothing about the count — that changes hourly and a
    number here would be a test that fails for being right.
    """
    if not census_mod.SCRATCH.is_dir():
        pytest.skip(
            "`.scratch/` is gitignored, so a clean checkout has no tickets to "
            "read. Skipping is right and asserting was not: this failed on CI "
            "from the day it was written, saying the regex had drifted when "
            "the directory simply was not there (async-first/15). A test that "
            "cannot pass where it runs teaches a reader to ignore the summary."
        )
    rows = census_mod.census()
    assert rows, "no open tickets found at all — the header regex has drifted"
    for row in rows:
        assert row["map"] and row["title"], f"unparsed ticket: {row['path']}"
