"""A blank line between two table rows must not split the table.

Ticket 18. Found while measuring `15`: the customer's Ops Desk answered a
five-row `Reason | Explanation` table, and the model put a blank line before
the last row. `md()` in `chat.html` calls `closeAll()` on any line that is
not itself a table row, list item, or code fence — so the blank line closed
the `<table>`, and the next row either opened a second table or, once other
prose intervened, printed as a paragraph of raw pipes in front of a customer.

`chat.html` has no JS test harness in this repo (see
`test_chat_answer_containment.py`), so this file extracts `md()`'s own source
with a regex and runs it under `node`, the same way the frontend build
already depends on `node` being present.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

_PAGE = Path(__file__).parent.parent / "openstategraph" / "api" / "static" / "chat.html"


@pytest.fixture(scope="module")
def md_source() -> str:
    text = _PAGE.read_text()
    match = re.search(r"function md\(text\) \{.*?\n\}\n", text, re.DOTALL)
    assert match, "md() not found in chat.html — has it been renamed or moved?"
    return match.group(0)


def _render(md_source: str, text: str) -> str:
    script = f"{md_source}\nconsole.log(JSON.stringify(md({json.dumps(text)})));"
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"node failed: {result.stderr}"
    return json.loads(result.stdout.strip())


class TestABlankLineInsideATableDoesNotEndIt:
    def test_a_normal_table_renders_as_one_table(self, md_source: str) -> None:
        text = "| Reason | Explanation |\n| --- | --- |\n| A | B |\n| C | D |"
        html = _render(md_source, text)
        assert html.count("<table>") == 1
        assert html.count("</table>") == 1
        assert "|" not in re.sub(r"<[^>]*>", "", html)

    def test_a_blank_line_inside_a_table_does_not_split_it(self, md_source: str) -> None:
        text = (
            "| Reason | Explanation |\n"
            "| --- | --- |\n"
            "| Enables modularity | Splits complex logic into reusable graph nodes. |\n"
            "| Supports parallelism | Multiple branches can execute concurrently. |\n"
            "\n"
            "| Enables code generation and reuse | Many frameworks can convert a "
            "state graph into script skeletons, reducing manual coding effort. |"
        )
        html = _render(md_source, text)
        assert html.count("<table>") == 1, html
        assert html.count("</table>") == 1, html
        # No row is stranded as a raw paragraph of pipes.
        assert "<p>|" not in html
        assert "Enables code generation and reuse" in html
        assert "<tr>" in html

    def test_a_blank_line_after_a_table_still_ends_it(self, md_source: str) -> None:
        """The tolerance must not swallow a genuinely new paragraph forever."""
        text = "| A | B |\n| --- | --- |\n| 1 | 2 |\n\nA closing paragraph."
        html = _render(md_source, text)
        assert html.count("<table>") == 1
        assert "<p>A closing paragraph.</p>" in html

    def test_a_lone_pipe_row_with_no_table_still_renders_as_a_table(
        self, md_source: str
    ) -> None:
        html = _render(md_source, "| Just one row | with two cells |")
        assert "<table>" in html
        assert "<tr>" in html
