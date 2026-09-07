"""Frontmatter that is not at the top is not frontmatter, and nothing said so.

On 2026-09-07 a stray click put the cursor in a Markdown instruction field in
the editor, and the keystrokes that followed left `+++======` in front of the
`---` that opens its YAML header. It sat in the working tree for four hours
inside a 513-line diff of harmless default materialisation, and `git diff` could
not tell the two apart.

**Nothing would have caught it**, and the first attempt at this test was wrong
about why. Measured on the real string:

    good        name='sql-analyst'      description='Answers questions.'
    corrupted   name='sql-analyst.md'   description=''
                body starts: '+++======---\\nname: sql-analyst\\ndescription: …'

The name silently becomes the *filename*, extension and all; the description is
gone; and the whole YAML header is now prompt text handed to a model. No error,
no warning, a worse skill — the failure `skills.py` already names in its own
docstring about a real YAML parser "silently skipping the skill ... rather than
raising, which is worse".

## What this does not assert, and why the obvious version was wrong

The first draft demanded a name and a description from every node carrying an
`instruction`. Five of the seven shipped ones failed it, and every one of those
failures was the test being wrong:

- **`input.skill` carries a body and no header at all.** `skills.py` is explicit
  that "a skill now travels as its body, and the header is a *disk* format",
  written by `render()` at the one place that composes it. Demanding
  frontmatter there would demand the duplication that design removed.
- **`input.markdown` is a Markdown file**, and a Markdown file does not have to
  open with YAML. `workflow-2026`'s is a plain draft marker. Requiring a header
  would be inventing a format the node does not have.

So the rule is narrowed to the one thing that is a defect under every reading:
**a document that contains a frontmatter header must begin with it.** Text that
carries `---` followed by `name:` is announcing a header; if that is not the
first thing in the file, the header is inert and its contents have quietly
become prose. Nothing legitimate is caught by that, which is why it is the rule
rather than the stricter one.

`CLAUDE.md`'s *read tolerantly, trust strictly* is about model output, and
`SkillDocument.parse` stays tolerant for that reason. A file committed to a
package is not model output; it is authored once and read forever, so it can be
checked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ROOTS = (REPO / "workflows", REPO / "backend" / "openstategraph" / "examples")

#: A document announcing YAML frontmatter: the fence, then the first key the
#: format requires. Looked for anywhere, because the defect is that it is *not*
#: at the beginning.
ANNOUNCES_HEADER = "---\nname:"


def instructions() -> list[tuple[str, str, str, str]]:
    """`(root, package, node id, text)` for every authored instruction field."""
    found: list[tuple[str, str, str, str]] = []
    for root in ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/workflow.json")):
            document = json.loads(path.read_text(encoding="utf-8")).get("document", {})
            for node in document.get("nodes", []):
                text = node.get("data", {}).get("instruction")
                if isinstance(text, str) and text.strip():
                    found.append((root.name, path.parent.name, node.get("id", "?"), text))
    return found


CASES = instructions()
IDS = [f"{root}/{package}:{node}" for root, package, node, _ in CASES]


class TestFrontmatterIsAtTheTop:
    def test_there_are_documents_to_check(self) -> None:
        # The census is derived, so an empty one means the query stopped
        # matching rather than that everything passed. A test that silently
        # checks nothing is the failure this repository names most often.
        assert CASES, (
            "No instruction field was found in any package under "
            f"{[str(r) for r in ROOTS]}. Either the field was renamed or the "
            "packages moved; a census that matches nothing is not a pass."
        )

    @pytest.mark.parametrize(("root", "package", "node", "text"), CASES, ids=IDS)
    def test_a_header_is_the_first_thing_or_there_is_no_header(
        self, root: str, package: str, node: str, text: str
    ) -> None:
        if ANNOUNCES_HEADER not in text:
            pytest.skip("no frontmatter announced — a plain Markdown body is fine")

        assert text.startswith("---\n"), (
            f"{root}/{package}:{node} carries a YAML header that does not start "
            f"the document. It begins {text[:24]!r}. Anything before the opening "
            "`---`, even one character, and the header is read as body text: the "
            "name falls back to the filename, the description is lost, and the "
            "whole header is handed to a model as prompt. Delete what precedes it."
        )
