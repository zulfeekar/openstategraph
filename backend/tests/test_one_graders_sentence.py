"""The grader's sentence is generated into `/chat`, not spelled there again.

`production-ready` 94. `workflow-gallery` 32 put the grader's verdict on the
`interrupt` frame and wrote the sentence a reviewer reads — twice: once in
`src/view/ask/graderVerdictLine.ts` for the editor's approval card, and once as
a hand-kept ternary in `chat.html` for `/chat`'s approval box. Duplication of
*knowledge*, which `CLAUDE.md` allows only behind a drift pin.

The pin `production-ready` 92 left was a substring grep, and its author said it
was not a fix. It was not: measured at the start of this ticket the two
spellings already disagreed on every input with surrounding whitespace — a
verdict of `"   "` printed the bare reason in `/chat` and nothing in the editor
— and the grep was green through all of it.

`chat.html` imports no bundled TypeScript on purpose, so the fix is option 2 of
the ticket: generate the function into the page and gate the drift, the same
relationship `docs/openapi.json` has with Pydantic. This test is the gate. Its
partner is `src/view/ask/graderVerdictLine.parity.test.ts`, which runs the
JavaScript the browser actually executes beside the TypeScript module over one
table of cases — because bytes agreeing is not the claim, the sentence agreeing
is.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "render_grader_verdict_line.py"
SOURCE = REPO / "src" / "view" / "ask" / "graderVerdictLine.ts"
PAGE = REPO / "backend" / "openstategraph" / "api" / "static" / "chat.html"


class TestTheGeneratedSentenceIsCurrent:
    def test_regenerating_changes_nothing(self) -> None:
        """The committed page is what the source of truth renders today."""
        before = PAGE.read_text(encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
        )
        after = PAGE.read_text(encoding="utf-8")
        if after != before:
            PAGE.write_text(before, encoding="utf-8")
        assert result.returncode == 0, result.stderr
        assert after == before, (
            "chat.html is stale — src/view/ask/graderVerdictLine.ts changed and "
            "`python3 scripts/render_grader_verdict_line.py` was not re-run."
        )

    def test_the_page_no_longer_spells_the_sentence_itself(self) -> None:
        """Outside the generated block the page must not restate the rules."""
        page = PAGE.read_text(encoding="utf-8")
        begin = page.index("// GENERATED-BEGIN graderVerdictLine")
        end = page.index("// GENERATED-END graderVerdictLine")
        outside = page[:begin] + page[end:]
        for phrase in ("The grader passed this", "The grader asked for a revision"):
            assert phrase not in outside, f"a second spelling of {phrase!r} is back in chat.html"

    def test_the_page_calls_the_generated_function(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        assert "graderVerdictLine({" in page

    def test_the_source_region_is_marked(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        assert "// GENERATED-SOURCE-BEGIN graderVerdictLine" in source
        assert "// GENERATED-SOURCE-END graderVerdictLine" in source
