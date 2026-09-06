"""`docs/stability.md` says "Tier 1, **exactly**". This makes that word true.

Production-ready ticket 20, reopened. The page answers one question — *if I
import it, can it be taken away from me?* — and answers it with a literal
import block headed "Tier 1, exactly". A reader is entitled to read that as a
list, because that is what it is shaped like.

It had drifted by **37 names** when this file was written. The whole
`openstategraph.providers` module was Tier 1 by every other measure — exported,
snapshotted, and named in `extensions`' entry-point group list — and appeared
in neither the tier table nor the block. So did the guardrail ladder
(`IGuardrail`/`BaseGuardrail`/`Guardrail`/`GuardrailRule`/`Redaction`/`Screening`),
the node-family ladder, two entry-point groups, and the six provider errors.

The direction that matters is the one an adopter feels: a Tier 1 name absent
from this page is a name they will not build on because they cannot tell it is
covered, and — worse — one *we* may break without noticing that the promise
applied. The reverse direction (a name listed here that no longer exists) is
also caught, because a promise about a deleted symbol is the more embarrassing
half.

**Why `public_api.txt` is the source of truth and not `dir()`.** That file is
the committed signature snapshot `test_public_api.py` already diffs on every
run, so it is the definition of "what we promised" that the repository already
maintains. Deriving from it means this test cannot disagree with that one, and
means adding a Tier 1 symbol requires exactly two edits — the snapshot and this
page — rather than three.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STABILITY = ROOT / "docs" / "stability.md"
SNAPSHOT = Path(__file__).resolve().parent / "public_api.txt"

#: The module the snapshot lists a name under maps onto the `from … import`
#: statement the page shows. Names re-exported from the top level appear twice
#: in the snapshot (once as `openstategraph.X`, once as its home module); the
#: page lists each one once, which is correct for a reader and would be wrong
#: for a set comparison — so both sides are flattened to bare leaf names.
LEAF = re.compile(r"^([a-zA-Z0-9_.]+)\s*=")


def promised_names() -> set[str]:
    """Every Tier 1 leaf name, from the snapshot CI already diffs."""
    names: set[str] = set()
    for line in SNAPSHOT.read_text().splitlines():
        match = LEAF.match(line.strip())
        if match:
            names.add(match.group(1).rsplit(".", 1)[-1])
    return names


def listed_names() -> set[str]:
    """Every identifier inside the page's "Tier 1, exactly" code block."""
    body = STABILITY.read_text().split("### Tier 1, exactly", 1)[1]
    # `split("```")[1]` opens with the fence's language tag on its own line.
    block = body.split("```", 2)[1].split("\n", 1)[1]
    # Drop the `from openstategraph.abc import (` scaffolding — module paths and
    # keywords are not promises, the imported names are.
    without_imports = re.sub(r"from\s+[\w.]+\s+import", " ", block)
    return {
        token
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", without_imports)
        if token not in {"import", "from"}
    }


class TestTierOneIsExactly:
    def test_the_page_lists_the_whole_snapshot(self) -> None:
        missing = sorted(promised_names() - listed_names())
        assert missing == [], (
            "these names are covered by the deprecation policy and a reader of "
            "docs/stability.md cannot tell, because its 'Tier 1, exactly' block "
            f"does not list them: {missing}"
        )

    def test_the_page_lists_nothing_that_does_not_exist(self) -> None:
        invented = sorted(listed_names() - promised_names())
        assert invented == [], (
            "docs/stability.md promises stability for names that are not in the "
            f"committed public API snapshot: {invented}"
        )

    def test_the_block_was_actually_found(self) -> None:
        """The guard every doc gate written this way needs.

        If the heading is renamed or the fence moves, the two assertions above
        start comparing empty sets against each other and pass forever. This is
        the one that notices.
        """
        assert len(listed_names()) > 50
        assert len(promised_names()) > 50


class TestTheTierTableCoversEveryTierOneModule:
    """A module can be Tier 1 in the snapshot and unmentioned in the table.

    That is how `openstategraph.providers` came to be promised and undocumented
    at the same time: the snapshot knew, the entry-point group list knew, and
    the one table a reader consults did not.
    """

    @pytest.mark.parametrize(
        "module",
        sorted(
            {
                line.split(" = ")[0].rsplit(".", 1)[0]
                for line in SNAPSHOT.read_text().splitlines()
                if " = " in line
            }
        ),
    )
    def test_it_is_named_in_the_tier_table(self, module: str) -> None:
        table = STABILITY.read_text().split("## The tiers", 1)[1].split("###", 1)[0]
        # `openstategraph` itself is named as `openstategraph.__all__`.
        needle = "openstategraph.__all__" if module == "openstategraph" else module
        assert needle in table, f"{module} is Tier 1 and the tier table never names it"
