"""`docs/on-the-canvas.md` §9, held against the bar and the breakdown.

`stable-beta-public/03` put a strip along the bottom of the editor and a dialog
behind it, and §9 of the canvas page is where a reader who has not opened the
product meets them. Nothing checked that page's words against the words on
screen — which is exactly the gap `test_documented_cli_surface.py`,
`test_documented_patrol_board_surface.py` and `test_documented_starter_surface.py`
closed for their own pages, so this is the same shape.

## What is pinned, and what deliberately is not

Pinned: **the strings a reader will hunt for on screen.** The four cell labels
the bar renders (`Total`, `Cached`, `This tab`, `Models`), the three table
headings the dialog renders, and the badge that marks the sitting you are in.
A label the doc spells one way and the source spells another sends a reader
looking for something that is not there.

Not pinned: the prose around them — why a sitting ends with the tab, why the
breakdown waits for the first answer. That is argument, not a checkable claim,
and `test_documented_cli_surface.py`'s docstring gives the reason: pin the
string on screen, not the sentence explaining it.

**The dash rule is the one exception, and it is pinned as a rule rather than
as a sentence.** `—` is not a `0`, and it is the one promise the ticket's own
*done when* makes ("the bar renders nothing false"), so the doc has to say it
and `spendModel.ts` has to still be the thing that decides it.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DOC = ROOT / "docs" / "on-the-canvas.md"
BAR = ROOT / "src" / "view" / "spend" / "SpendBar.tsx"
DIALOG = ROOT / "src" / "view" / "spend" / "SpendDialog.tsx"
MODEL = ROOT / "src" / "view" / "spend" / "spendModel.ts"

HEADING = "## 9. The bottom bar — what the work has cost"

#: The bar's four cells, in the order it renders them.
CELLS = ("Total", "Cached", "This tab", "Models")

#: The dialog's three tables, by the heading each one carries.
TABLES = ("Grand total, by model", "This tab, by model", "Sessions, newest first")


def _section() -> str:
    """§9, with its line breaks collapsed.

    Where the prose wraps is not a promise — an editor reflowing a paragraph
    would otherwise break every assertion below, which is the failure that
    teaches a reader to suppress the test rather than fix the page.
    """
    text = DOC.read_text()
    assert HEADING in text, "on-the-canvas.md \u00a79 moved or was retitled"
    start = text.index(HEADING)
    end = text.index("\n## ", start + len(HEADING))
    return " ".join(text[start:end].split())


class TestTheDocNamesTheCellsTheBarRenders:
    def test_every_cell_label_in_the_source_appears_in_the_section(self) -> None:
        source = BAR.read_text()
        section = _section()
        for label in CELLS:
            assert f'label="{label}"' in source, (
                f"SpendBar no longer renders a cell labelled {label!r}; "
                "on-the-canvas.md §9 names it"
            )
            assert f"**{label}**" in section or f"*{label}*" in section, (
                f"on-the-canvas.md §9 no longer names the {label!r} cell"
            )

    def test_the_section_names_no_cell_the_bar_does_not_have(self) -> None:
        """The other direction, which is the one that goes stale quietly: a
        cell renamed in the source leaves the doc pointing at nothing."""
        source = BAR.read_text()
        emphasised = {
            word.strip("*")
            for word in _section().split()
            if word.startswith("*") and word.strip("*").istitle()
        }
        for word in emphasised & {"Total", "Cached", "Models", "Runs", "Input", "Output"}:
            assert f'label="{word}"' in source or f">{word}<" in DIALOG.read_text(), (
                f"on-the-canvas.md §9 emphasises {word!r}, which neither the bar "
                "nor the breakdown renders"
            )


class TestTheDocNamesTheTablesTheDialogRenders:
    def test_all_three_headings(self) -> None:
        dialog = DIALOG.read_text()
        section = _section()
        for heading in TABLES:
            assert f">{heading}<" in dialog, (
                f"SpendDialog no longer heads a table {heading!r}"
            )
            assert heading.lower() in section.lower(), (
                f"on-the-canvas.md §9 no longer names the {heading!r} table"
            )

    def test_the_current_sitting_is_marked_with_the_words_the_badge_uses(self) -> None:
        assert "this tab\n" in DIALOG.read_text() or ">this tab<" in DIALOG.read_text()
        assert "**this tab**" in _section(), (
            "on-the-canvas.md §9 no longer says how the current sitting is marked"
        )


class TestTheDashRuleIsStated:
    def test_the_section_says_a_dash_is_not_a_zero(self) -> None:
        section = _section()
        assert "—" in section and "`0`" in section, (
            "on-the-canvas.md §9 must say that a dash is not a zero — it is the "
            "one promise stable-beta-public/03's 'done when' makes"
        )

    def test_and_one_place_in_the_source_still_decides_it(self) -> None:
        """The doc's claim is only true while `reportedTokens` is the single
        owner of the tri-state. A second spelling would be the duplication of
        knowledge the DRY rule forbids, and this doc would then be describing
        one of them."""
        model = MODEL.read_text()
        assert "export function reportedTokens" in model
        assert model.count("const NOTHING_REPORTED") == 1
