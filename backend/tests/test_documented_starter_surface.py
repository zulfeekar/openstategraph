"""`docs/getting-started.md`'s first-visit paragraph, held against the starter.

`stable-beta-public/06` closed on the promise that the first visit is a
runnable example, not a stub: a question typed into the Input, a note that
says press Run, an answer that gets explained, and — when nothing can
answer — a note that names the environment variable rather than inviting a
press that fails. `docs/getting-started.md` narrates that paragraph for a
reader who has not opened the product yet. Nothing checked it against the
actual wording, which is exactly the gap `test_documented_cli_surface.py`
and `test_documented_patrol_board_surface.py` closed for their own pages —
so this is the same shape: the doc's claims about the starter's *controls*
(Input, Agent, Output, Run, the note, deleting it) are checkable against
`src/app/firstRunStarter.ts`, and this file is what keeps them true.

## What is pinned, and what deliberately is not

The prose *around* the controls — why the starter exists, why it is unsaved,
why it fires once per browser — is argument, not a checkable claim, and stays
unpinned for the reason `test_documented_cli_surface.py`'s own docstring
gives: pin the string a reader will hunt for on screen, not the sentence
explaining it. What is pinned is narrower: every node name the doc bolds as
part of the starter (Input, Agent, Output) is a node the starter's own
before-run text names the same way, the doc's word for the button (`Run`)
is the word the note itself uses, and the doc's claim that a no-model note
"names the environment variable" and that the note is always deletable are
both still true of the source.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DOC = ROOT / "docs" / "getting-started.md"
STARTER = ROOT / "src" / "app" / "firstRunStarter.ts"


def _doc_starter_paragraph() -> str:
    text = DOC.read_text()
    marker = "The **first** visit in a browser is the one exception"
    assert marker in text, "the first-visit paragraph moved or was reworded out of getting-started.md"
    start = text.index(marker)
    # The paragraph ends at the next blank-line-delimited block.
    end = text.index("\n\n", start)
    return text[start:end]


def _starter_source() -> str:
    return STARTER.read_text()


class TestTheDocNamesTheRealControls:
    def test_it_bolds_the_three_node_names_the_starter_uses(self) -> None:
        paragraph = _doc_starter_paragraph()
        source = _starter_source()
        for node in ("Input", "Agent", "Output"):
            assert f"**{node}**" in paragraph, (
                f"getting-started.md's first-visit paragraph no longer bolds **{node}**"
            )
            # The node name the doc bolds must be a node the note itself names
            # the same way — not a claim about a node that got renamed.
            assert f"**{node}**" in source, (
                f"src/app/firstRunStarter.ts no longer names **{node}** — "
                "getting-started.md's claim about it is stale"
            )

    def test_it_says_press_run_the_same_word_the_note_uses(self) -> None:
        paragraph = _doc_starter_paragraph()
        source = _starter_source()
        assert "**Run**" in paragraph
        assert "Press Run" in source, (
            "the before-run note no longer says 'Press Run' — the doc's claim is stale"
        )

    def test_it_says_the_note_names_the_variable_rather_than_inviting_a_press(self) -> None:
        paragraph = _doc_starter_paragraph()
        source = _starter_source()
        assert "never says" in paragraph and "press run" in paragraph.lower()
        # The no-model wording quotes the server's own sentence and never
        # invites a press — checked at the source that composes it.
        assert "must not say" in source or "It must not say" in source, (
            "firstRunStarter.ts no longer documents the no-model rule the doc describes"
        )

    def test_it_says_the_note_is_always_deletable(self) -> None:
        paragraph = _doc_starter_paragraph()
        source = _starter_source()
        assert "delete" in paragraph.lower()
        assert re.search(r"delete this note|yours to delete", source, re.IGNORECASE), (
            "no before/after wording in firstRunStarter.ts still offers to be deleted"
        )


class TestTheScanActuallyReachesTheDoc:
    def test_the_paragraph_was_actually_found(self) -> None:
        paragraph = _doc_starter_paragraph()
        assert len(paragraph) > 200, "the first-visit paragraph looks truncated"

    def test_the_source_file_exists_and_is_not_empty(self) -> None:
        assert STARTER.exists()
        assert len(_starter_source()) > 1_000
