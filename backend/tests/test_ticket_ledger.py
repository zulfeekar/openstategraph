"""The ledger check reads the ledger, and must read it correctly — ticket 57.

Twenty tickets said `Status: open` for work that had shipped, including a
data-loss blocker. `scripts/ticket_ledger.py` exists so a future session can
tell shipped from open without reading twenty agent reports, and the thing it
must never do is answer confidently and wrongly: a checker that says "the
ledger and git agree" when it does not is worse than no checker, for exactly
the reason the original defect was worse than an empty ledger.

So its two judgements are pinned here — what counts as *open*, and what counts
as a *disagreement*. `.scratch/` is gitignored, so these run against fixtures
written by the test rather than against the real maps: a test that read the
live ledger would go red the moment someone opened a ticket, which is a test
about today's backlog rather than about the checker.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parent.parent.parent


def _script() -> ModuleType:
    """Imported by path — `scripts/` is not an importable package."""
    path = REPO / "scripts" / "ticket_ledger.py"
    spec = importlib.util.spec_from_file_location("ticket_ledger", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before executing: the script's `Ticket` is a dataclass under
    # `from __future__ import annotations`, and `dataclasses` resolves those
    # string annotations through `sys.modules[cls.__module__]`. A module loaded
    # purely by path is not there, and the class body raises on definition.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _script()


def ticket(script: ModuleType, status: str, body: str = "") -> object:
    return script.Ticket(
        map_name="a-map",
        number="07",
        path=Path("07-a-ticket.md"),
        status=status,
        body=body,
    )


class TestWhatCountsAsOpen:
    @pytest.mark.parametrize(
        "status",
        [
            "open",
            "**open**",
            'open — the "package" half (F10) is resolved; F9 and F12 remain',
            "(no Status line)",
        ],
    )
    def test_these_are_open(self, script: ModuleType, status: str) -> None:
        assert ticket(script, status).is_open

    @pytest.mark.parametrize(
        "status",
        [
            "resolved",
            "**resolved** 2026-08-18",
            "closed",
            "done 2026-08-16",
            "resolved (7782285)",
            "**backlog** (owner, 2026-08-18 — parked deliberately)",
        ],
    )
    def test_these_are_not(self, script: ModuleType, status: str) -> None:
        assert not ticket(script, status).is_open

    def test_a_resolved_status_that_says_half_in_prose_is_not_a_partial(
        self, script: ModuleType
    ) -> None:
        """Ticket 01 delegated its remaining half to ticket 21 and said so in
        its status. The word *half* in that sentence made this script report a
        resolved ticket as open — the exact failure it exists to prevent,
        produced by the script. `partial` and `partly` are the words that mean
        it; a status may talk about halves."""
        delegated = ticket(
            script,
            "**resolved** — the template shipped; the half the correction names went to ticket 21",
        )

        assert not delegated.is_open
        assert not delegated.is_partial

    def test_a_partial_is_open_and_says_so_twice(self, script: ModuleType) -> None:
        """Half-shipped is open work. It is also the one open state that
        legitimately carries a resolution section, so it is named rather than
        inferred — see the exemption below."""
        partial = ticket(script, "partially resolved (the refusal; static fan-in remains open)")

        assert partial.is_open
        assert partial.is_partial


class TestWhatCountsAsADisagreement:
    def test_a_resolution_section_under_an_open_header_is_one(self, script: ModuleType) -> None:
        """The check that needs no git at all, and the one that caught two of
        the three drifts found by hand on 2026-08-18."""
        drifted = ticket(script, "open", body="# T\n\n## Resolution (2026-08-16)\n\nShipped.\n")

        assert script.RESOLUTION_HEADING.search(drifted.body)
        assert drifted.is_open and not drifted.is_partial

    def test_the_same_section_under_a_partial_header_is_not(self, script: ModuleType) -> None:
        partial = ticket(
            script,
            "partially resolved (the refusal remains)",
            body="# T\n\n## Resolution\n\nHalf of it.\n",
        )

        assert partial.is_partial  # exempt: the section describes the half that landed

    def test_an_ordinary_heading_is_not_mistaken_for_one(self, script: ModuleType) -> None:
        for heading in ("## Question", "## Done when", "## Watch for", "## Options"):
            assert script.RESOLUTION_HEADING.search(f"{heading}\n\nbody") is None


class TestTheTrailerConvention:
    """`Ticket: <map>/<id>` in a commit message is the durable half of the fix:
    `.scratch/` is gitignored, so the commit is the only place a resolution can
    live where a diff will ever show it."""

    def test_it_reads_a_trailer(self, script: ModuleType) -> None:
        message = "Subject line\n\nBody.\n\nTicket: production-ready/46\n"

        assert script.TRAILER.findall(message) == [("production-ready", "46")]

    def test_a_commit_may_resolve_several(self, script: ModuleType) -> None:
        message = "Subject\n\nTicket: production-ready/46\nTicket: ship-it/07\n"

        assert script.TRAILER.findall(message) == [
            ("production-ready", "46"),
            ("ship-it", "07"),
        ]

    def test_the_map_is_part_of_the_id(self, script: ModuleType) -> None:
        """Every map numbers from 01, so a bare number names several tickets."""
        assert script.TRAILER.findall("Ticket: 46\n") == []

    def test_prose_mentioning_a_ticket_is_not_a_trailer(self, script: ModuleType) -> None:
        assert script.TRAILER.findall("This is like production-ready/46 but different\n") == []


class TestATrailerNamingATicketThatDoesNotExist:
    """`production-ready` 104. Three commits (`9c39c4c`, `6aae666`, `578ccec`)
    carried `Ticket: production-ready/100`, `/101` and `/102` trailers while no
    file existed at those numbers — `.scratch/` is gitignored, so the tickets
    those commits resolved left no trace a diff would show. Every check above
    starts from a ticket *file* and asks what git says about it; none of them
    asks the reverse question, so a session that numbers its next ticket from
    `ls tickets/ | tail -1` can silently collide with a commit's own claim and
    have `ticket_ledger.py` report the new, unrelated, open ticket as already
    resolved by someone else's work — which is exactly how this was found.
    """

    def test_a_trailer_naming_no_file_is_reported(self, script: ModuleType) -> None:
        claimed = {"production-ready/100": ["9c39c4c"]}
        known: set[str] = {"production-ready/99"}

        assert script.missing_ticket_files(claimed, known) == [
            ("production-ready/100", ["9c39c4c"])
        ]

    def test_a_trailer_naming_a_real_ticket_is_not(self, script: ModuleType) -> None:
        claimed = {"production-ready/46": ["7782285"]}
        known = {"production-ready/46"}

        assert script.missing_ticket_files(claimed, known) == []

    def test_several_missing_ids_are_all_reported(self, script: ModuleType) -> None:
        claimed = {
            "production-ready/100": ["9c39c4c"],
            "production-ready/101": ["6aae666"],
            "production-ready/102": ["578ccec"],
        }
        known: set[str] = set()

        assert script.missing_ticket_files(claimed, known) == [
            ("production-ready/100", ["9c39c4c"]),
            ("production-ready/101", ["6aae666"]),
            ("production-ready/102", ["578ccec"]),
        ]

    def test_the_map_filter_narrows_it(self, script: ModuleType) -> None:
        """A `--map production-ready` run must not report a missing `ship-it`
        ticket — that ticket is out of scope, not evidence of drift here."""
        claimed = {"production-ready/100": ["a0eff1a"], "ship-it/03": ["fcfe3c7"]}
        known: set[str] = set()

        assert script.missing_ticket_files(claimed, known, map_filter="production-ready") == [
            ("production-ready/100", ["a0eff1a"])
        ]

    def test_it_runs_end_to_end_against_the_real_repository(self, script: ModuleType) -> None:
        """`main([])` must not crash wiring this in, and — now that 100-102 are
        reconstructed — must report zero of these against the live maps."""
        if not (REPO / ".scratch").is_dir():
            pytest.skip("no .scratch/ in this checkout — the maps are not committed")

        assert script.main([]) == 0


def test_it_runs_against_the_real_maps_without_falling_over(script: ModuleType) -> None:
    """A smoke test, not an assertion about the backlog: exit 0 means it read
    every ticket file in the repository. Whether they *agree* is the report's
    business and changes daily; that this can be run at all is what a future
    session depends on."""
    if not (REPO / ".scratch").is_dir():
        pytest.skip("no .scratch/ in this checkout — the maps are not committed")

    assert script.main([]) == 0


class TestReadingTheHeaderItself:
    """The untested half, and the one that was wrong — `production-ready` 62.

    Every test above hands `Ticket` a status string and asks what it *means*.
    Nothing handed the script a header and asked what it *read*. Two header
    shapes are in use across the maps and the parser knew one, so every ticket
    written in the other style parsed as `(no Status line)` — which contains no
    closed word, so it was open forever whatever it said. Twenty-five clean
    tickets were reported as drift, on the one instrument CLAUDE.md names as
    the authority over prose.
    """

    def _status(self, script: ModuleType, header: str) -> str:
        match = script.STATUS.search(header)
        return match.group(1).strip() if match else "(no Status line)"

    def test_the_labels_line_shape(self, script: ModuleType) -> None:
        header = (
            "# 07 — A ticket\n\n"
            "Labels: wayfinder:bug · Status: open · Size: M · Map: every-workflow-green\n"
        )
        assert self._status(script, header) == "open"

    def test_the_standalone_line_shape(self, script: ModuleType) -> None:
        """`every-workflow-green` 33 and everything after it are written this way."""
        header = (
            "# 33 — It asked for a tool we ship\n\n"
            "Status: resolved 2026-08-19\n"
            "Found: 2026-08-19, by the owner reading a chat transcript\n"
            "Label: wayfinder:bug\n"
        )
        assert self._status(script, header) == "resolved 2026-08-19"

    def test_a_ticket_in_the_standalone_shape_can_actually_close(
        self, script: ModuleType
    ) -> None:
        """The consequence, stated as the thing a person cares about."""
        header = "# 33 — T\n\nStatus: resolved 2026-08-19\nLabel: wayfinder:bug\n"
        assert not ticket(script, self._status(script, header)).is_open

    def test_a_dot_separator_still_ends_the_status(self, script: ModuleType) -> None:
        header = "Labels: wayfinder:task · Status: partially resolved · Size: L\n"
        assert self._status(script, header) == "partially resolved"

    def test_the_word_status_inside_prose_is_not_a_header(self, script: ModuleType) -> None:
        """A body sentence must not be able to reopen or close a ticket."""
        body = (
            "# 07 — A ticket\n\n"
            "Labels: wayfinder:bug · Status: open · Size: S\n\n"
            "## Question\n\nThe run reports Status: resolved in its own output, which is\n"
            "the bug.\n"
        )
        assert self._status(script, body) == "open"

    def test_a_file_with_no_header_at_all_still_says_so(self, script: ModuleType) -> None:
        """Unreadable must stay distinguishable from open — it needs a human."""
        assert self._status(script, "# 07 — A ticket\n\nJust prose.\n") == "(no Status line)"


class TestAPartialIsExemptFromBothChecks:
    """`production-ready` 65.

    A half-shipped ticket is open by design *and* carries trailers by design —
    that is what a partial is. The resolution-section check said so in a
    comment; the trailer check did not, so recording work honestly produced a
    drift line. The rule now lives in one place, `is_partial`, and both checks
    read it.
    """

    def test_a_partial_is_open_and_carries_commits(self, script: ModuleType) -> None:
        partial = ticket(script, "partially resolved 2026-08-20 (part 1 shipped; part 2 open)")

        assert partial.is_open
        assert partial.is_partial

    def test_the_trailer_check_exempts_it(self, script: ModuleType) -> None:
        partial = ticket(script, "partially resolved (part 2 open)")

        assert not script.is_trailer_drift(partial, ["fcfe3c7"])

    def test_a_plainly_open_ticket_with_a_trailer_is_still_drift(
        self, script: ModuleType
    ) -> None:
        """The exemption must not swallow the defect the check exists for."""
        drifted = ticket(script, "open")

        assert script.is_trailer_drift(drifted, ["a0eff1a"])

    def test_a_closed_ticket_is_not_drift(self, script: ModuleType) -> None:
        assert not script.is_trailer_drift(ticket(script, "resolved 2026-08-19"), ["a0eff1a"])

    def test_an_open_ticket_with_no_commits_is_not_drift(self, script: ModuleType) -> None:
        assert not script.is_trailer_drift(ticket(script, "open"), [])
