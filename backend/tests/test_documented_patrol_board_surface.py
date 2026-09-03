"""The patrol board's page in `docs/the-patrol-board.md`, held against the board.

`kanban-patrol/30`. The board shipped with two reference pages behind it —
`docs/cli.md` and `docs/mcp.md`, one per door — and no page about the board
itself, so every column label, the evidence gate and the copy-instruction
flow were decisions a reader was asked to trust without being told. The page
is the fix; this file is the reason the page cannot quietly stop being true.

## Why a label and not the prose

Same split `test_documented_cli_surface.py` draws, for the same reason: pin
the checkable claim and leave the argument alone. What each column *means* is
prose and is the useful half; **what each control is called** is a string a
reader will hunt for on screen, and a renamed button turns the page into a
set of instructions for a product that no longer exists.

So two directions, and they fail for different readers:

- **Page → source.** A label the page names in backticks and the board does
  not have is a reader looking for a button that is not there.
- **Source → page.** A column in `BOARD_COLUMNS` or an action in
  `ACTION_COPY` the page never names is a reader meeting a control the page
  never introduced — the direction a page drifts in on its own, because a
  label reaches the UI in the same commit as the behaviour and the document
  is a separate act of will.

## What counts as a label claim

A backticked span that reads like a piece of on-screen copy: it begins with a
capital and carries only letters, digits, spaces, an em dash or a hyphen. That
deliberately excludes everything else this page backticks — file paths
(`cardStage.ts`), wire values (`detected`, `needsYou`), config keys
(`project_id`), CLI lines — none of which begin with a capital or are free of
`.`/`_`/`/`.

The handful of capitalised spans that are genuinely not UI copy are named in
`NOT_A_LABEL` with the reason, rather than the rule being widened until it
stops catching anything.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PAGE = ROOT / "docs" / "the-patrol-board.md"

#: Every module the board's own copy may live in. A label spelled anywhere
#: else — the top bar's chip, a design primitive — is not this board's to
#: claim, which is the point of scoping the search rather than grepping `src/`.
BOARD_DIR = ROOT / "src" / "view" / "board"

#: A backticked span that reads as on-screen copy. See the docstring.
LABEL_IN_PROSE = re.compile(r"`([A-Z][A-Za-z0-9 —-]*)`")

#: A single- or double-quoted TypeScript string literal.
STRING_LITERAL = re.compile(r"'([^'\\\n]*)'|\"([^\"\\\n]*)\"")

#: Capitalised backticked spans that are not on-screen copy, each with its
#: reason. Kept short on purpose: the moment this set grows to cover a real
#: label, the gate has been widened rather than the page corrected.
NOT_A_LABEL = {
    "MCP",  # the protocol, named in prose
    "CLI",  # the door, named in prose
    "SKILL",  # part of the bundled skill file's own filename
    "GitHub",  # the company, where the page is not naming the tab
}


def board_string_literals() -> set[str]:
    """Every string literal the board's own modules contain.

    Read as text rather than parsed: this is a search for a spelling, and the
    question a reader asks — *does this exact wording exist on the board* — is
    a question about characters, not about an AST.
    """
    found: set[str] = set()
    for path in sorted(BOARD_DIR.glob("*.ts")) + sorted(BOARD_DIR.glob("*.tsx")):
        source = path.read_text()
        for single, double in STRING_LITERAL.findall(source):
            found.add(single or double)
        # JSX text: `>Release<` is a label with no quotes around it at all,
        # which is exactly how the one control that destroys data is written.
        for text in re.findall(r">\s*([A-Z][A-Za-z0-9 —-]*?)\s*<", source):
            found.add(text)
    return found


def declared_labels(filename: str, table: str) -> list[str]:
    """The `label:` values inside one named table, in source order."""
    source = (BOARD_DIR / filename).read_text()
    body = source.split(table, 1)[1]
    body = body[: body.index("\n};") if "\n};" in body else body.index("\n];")]
    return re.findall(r"label: '([^']+)'", body)


@pytest.fixture(scope="module")
def page() -> str:
    assert PAGE.exists(), f"{PAGE.relative_to(ROOT)} is the board's only page and is missing"
    return PAGE.read_text()


@pytest.fixture(scope="module")
def claimed(page: str) -> list[str]:
    return sorted({m for m in LABEL_IN_PROSE.findall(page)} - NOT_A_LABEL)


class TestEveryLabelThePageNamesIsReal:
    """A control the page names and the board does not have."""

    def test_every_backticked_label_exists_on_the_board(self, claimed: list[str]) -> None:
        literals = board_string_literals()
        invented = sorted(label for label in claimed if label not in literals)
        assert invented == [], (
            f"docs/the-patrol-board.md names {invented} as on-screen copy and no module "
            f"under src/view/board/ spells it — a reader would hunt for a control that "
            "is not there"
        )

    def test_the_scan_actually_reaches_the_page(self, claimed: list[str], page: str) -> None:
        """Guards both assertions from passing because they matched nothing.

        A backtick convention that stops matching is a green test that checks
        the empty set — the failure mode of every doc gate written this way.
        """
        assert len(page) > 4_000, "the page is too short to be the board's reference"
        assert len(claimed) >= 8, f"the label scan found only {claimed}"
        assert len(board_string_literals()) > 50, "the board scan found almost no strings"


class TestEveryControlTheBoardHasIsOnThePage:
    """The direction a page drifts in on its own."""

    @pytest.mark.parametrize("label", declared_labels("patrolBoardModel.ts", "BOARD_COLUMNS"))
    def test_every_column_is_named(self, page: str, label: str) -> None:
        assert f"`{label}`" in page, (
            f"`{label}` is one of the board's four columns and the page never names it"
        )

    @pytest.mark.parametrize("label", declared_labels("cardAction.ts", "ACTION_COPY"))
    def test_every_action_is_named(self, page: str, label: str) -> None:
        assert f"`{label}`" in page, (
            f"`{label}` is a control `actionForCard` offers and the page never names it"
        )

    def test_the_tables_were_actually_found(self) -> None:
        """The split above is a text search; a renamed table would silently
        parametrize over nothing, which is a green test of an empty list."""
        assert len(declared_labels("patrolBoardModel.ts", "BOARD_COLUMNS")) == 4
        assert len(declared_labels("cardAction.ts", "ACTION_COPY")) == 2


class TestThePageIsReachable:
    """A page nobody links is a page nobody finds — the ticket's own symptom."""

    def test_on_the_canvas_links_it(self) -> None:
        canvas = (ROOT / "docs" / "on-the-canvas.md").read_text()
        assert "the-patrol-board.md" in canvas

    def test_the_readme_feature_list_mentions_it(self) -> None:
        assert "the-patrol-board.md" in (ROOT / "README.md").read_text()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
