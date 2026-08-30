"""`docs/on-the-canvas.md` — the page a user meets the run timeline on.

`docs-and-gaps` 26. The run dock shipped with lanes, a playhead, a transport
and four keyboard bindings, and the only prose about any of it was in
`docs/decisions/`. A decision record is where a choice is argued; it is never
where a user meets a feature.

**The word is the part that costs money if it is missing.** `CLAUDE.md` coined
*Replay* deliberately — a profiler, not a re-execution, the playhead spends
nothing — because LangGraph publishes *replay* for the fork-and-re-execute
operation that fires the model calls again. A user who reads those docs and
then presses play here has every reason to think it will be billed.
`src/view/run/replayIsNotRerun.test.ts` pins that distinction in `CLAUDE.md`
and in the component. This pins the one place a user actually reads it.

It also pins the **negative**: `memory-and-replay` 59, 60 and 61 are filed and
not built, and a page describing them would be the exact defect this map exists
to fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "on-the-canvas.md"
APP_SHELL = REPO / "src" / "view" / "AppShell.tsx"


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _glossary_row(page: str, word: str) -> str:
    match = re.search(rf"^\| \*\*{re.escape(word)}\*\* \|.*$", page, re.MULTILINE)
    assert match, (
        f"The glossary has no **{word}** row. `CLAUDE.md` names this page as "
        "where a user meets the lexicon, so a lexicon row that stops one file "
        "short of it has not arrived."
    )
    return match.group(0)


class TestTheLexiconReachesTheReader:
    @pytest.mark.parametrize("word", ["replay", "re-run", "eval", "slug"])
    def test_the_word_has_a_row(self, page: str, word: str) -> None:
        row = _glossary_row(page, word)
        # Three cells like every other row: the word, what it means, and the
        # column that is the whole point — what it must never mean.
        assert len([cell for cell in row.split("|") if cell.strip()]) == 3

    def test_replay_says_it_is_a_profiler_and_names_the_collision(
        self, page: str
    ) -> None:
        row = _glossary_row(page, "replay")
        assert "profiler" in row
        assert "LangGraph" in row
        assert "re-execut" in row, (
            "The `Not` column has to say what LangGraph's replay does, in its "
            "own terms. Naming the collision without naming the behaviour "
            "leaves the reader with two words and no way to tell them apart."
        )

    def test_re_run_is_marked_as_not_built(self, page: str) -> None:
        assert "not built here" in _glossary_row(page, "re-run").lower()


class TestTheDockIsOnAUserPage:
    def test_the_page_names_the_surface(self, page: str) -> None:
        for word in ("timeline", "playhead", "transport", "lane"):
            assert word in page.lower(), f"The run dock's `{word}` is undocumented."

    def test_the_toggle_binding_is_the_one_the_editor_dispatches(
        self, page: str
    ) -> None:
        # Read out of the binding table, not retyped: one table drives the
        # dispatcher and the shortcuts drawer, and a third spelling on a doc
        # page is exactly the copy that drifts.
        shell = APP_SHELL.read_text(encoding="utf-8")
        match = re.search(
            r"keys: '([^']+)',\s*\n\s*label: 'Toggle run timeline'", shell
        )
        assert match, "AppShell no longer binds 'Toggle run timeline'."
        assert f"`{match.group(1)}`" in page

    def test_the_shortcuts_drawer_is_named_as_the_published_list(
        self, page: str
    ) -> None:
        # The honest answer to "where are the shortcuts": there is one binding
        # table and the drawer prints it, so the page points rather than
        # copying four rows that would go stale.
        assert "shortcuts drawer" in page


class TestTheHonestyRulesAUserWillOtherwiseMisread:
    def test_a_live_run_is_told_it_gets_no_scrubber(self, page: str) -> None:
        assert "scrubber" in page
        assert "live run" in page.lower()

    def test_the_dash_is_explained_and_zero_is_ruled_out(self, page: str) -> None:
        assert "`—`" in page
        assert "`0 ms`" in page, (
            "A reader who sees a dash where a duration should be will read it "
            "as a bug unless the page says a dash means nobody timed it — and "
            "that it is deliberately not a zero."
        )

    def test_an_open_ended_lane_is_explained(self, page: str) -> None:
        assert "open-ended" in page


class TestNothingUnbuiltIsDescribed:
    """59, 60 and 61 are filed and absent. The page must stay quiet about them."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "payload pane",
            "cadence",
            "token total",
            "re-types",
            "retypes",
        ],
    )
    def test_the_page_does_not_promise_it(self, page: str, phrase: str) -> None:
        assert phrase not in page.lower(), (
            f"`{phrase}` is `memory-and-replay` 59/60/61 — filed, not built. "
            "A page describing it is the defect this map exists to fix."
        )
