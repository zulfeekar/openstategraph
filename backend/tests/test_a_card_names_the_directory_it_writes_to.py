"""A card's own brief may not name a directory the code stopped writing to.

`tool.email-send`'s description ended *"Dry-run (.eml to workflows/_outbox)"*
long after `prebuilt_email.outbox()` had moved to `state_dir() / "outbox"`
(`scale-and-adopt/03`, because a dry-run `.eml` is diagnostic output rather
than content the user authored, and a read-only workflows tree turned "send
the report" into an unactionable tool failure). The sentence is printed on the
palette card, by `openstategraph nodes`, and in the generated
`docs/modules.md`, so a developer who dry-ran a send looked where the only
place that told them anything told them to look, and found nothing.

**The pin holds the agreement, not the wording** (`docs-onramp/13`). A second
copy of a path is the defect, so nothing here asserts a sentence: the test
asks whether any path a description names is a path this process actually
writes to, and derives the write locations from the modules that answer that
question rather than restating them.
"""

from __future__ import annotations

import re
from pathlib import Path

from openstategraph.compile.node_catalogue import load_catalogue
from openstategraph.prebuilt_email import outbox
from openstategraph.state_dir import state_dir
from openstategraph.workflows_root import checkout_root, workflows_root

#: A slash-joined run of path-ish characters — `workflows/_outbox`, and also
#: `pass/revise.`, which is why the assertions below only ever ask about
#: tokens rooted in the workflows tree.
_PATHY = re.compile(r"(?:[\w.]+/)+[\w.]+")


def _node_types() -> tuple[dict, ...]:
    return load_catalogue().nodes


def _description(type_id: str) -> str:
    return next(n["description"] for n in _node_types() if n["type"] == type_id)


def _write_locations() -> set[str]:
    """Every directory this process writes to, as this checkout spells it.

    Derived, so the day one of them moves again this test moves with it.
    """
    root = checkout_root() or Path.cwd()
    here = {workflows_root(), state_dir(), outbox()}
    spellings = {str(p) for p in here}
    for p in here:
        try:
            spellings.add(str(p.relative_to(root)))
        except ValueError:
            pass
    return spellings


class TestTheEmailCardAndTheOutboxAgree:
    def test_every_path_the_card_names_is_where_the_eml_lands(self) -> None:
        description = _description("tool.email-send")
        named = [t for t in _PATHY.findall(description) if "workflows/" in t]
        written = _write_locations()
        for token in named:
            assert any(token in place for place in written), (
                f"tool.email-send's description names {token!r}, which is not part of "
                f"any directory the tool writes to (the dry-run .eml lands in "
                f"{outbox()}). Say 'the outbox' and let the tool's own result print the "
                f"file, or name the state directory in state_dir.py's words."
            )


class TestNoCardNamesAStalePathInTheWorkflowsTree:
    def test_the_census_covers_every_node_type(self) -> None:
        written = _write_locations()
        stale: list[tuple[str, str]] = []
        for node in _node_types():
            for token in _PATHY.findall(node.get("description") or ""):
                if "workflows/" not in token:
                    continue
                if not any(token in place for place in written):
                    stale.append((node["type"], token))
        assert not stale, (
            "these descriptions name a path under the workflows tree that nothing "
            f"writes to: {stale}"
        )
