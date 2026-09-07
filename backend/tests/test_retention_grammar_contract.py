"""The card's retention grammar and the ledger's are one grammar, or this is red.

`memory-hardening/10`. The limit was parsed twice — `text.isdigit()` in
`memory_segment.parse_retention`, `Number(raw)` in `MemorySegmentNode.ts` — and
the two disagreed in **both** directions:

- The card accepted `20.0`, `1e3`, `+5` and `0x14`, and its subtitle promised
  *keeps the last 20* / *1000* / *5* / *20*, while the ledger read every one of
  them as unbounded. That is the ticket's title: a bound the ledger does not
  keep.
- Less visibly, the ledger accepted `١٠` — `str.isdigit()` is true for
  Arabic-Indic digits and `int()` reads them — for a string the card refuses.
  And it held `999999999999999999999` exactly where `Number()` gives `1e+21`,
  so the same document produced two different bounds.

The pin is deliberately **not** a comparison of the two source texts. Pinning
constants while leaving the assembly unpinned is how two implementations
diverged anyway (`every-workflow-green/39`). What is pinned is the *behaviour*:
one table of inputs, `retentionGrammar.cases.json`, run through `parse_retention`
here and through `parseRetention`/`validateRetention` in
`src/nodes/memory/MemorySegmentNode.test.ts`. Neither side can move without the
other's suite going red on the same file.

The table lives beside the card because the card is where a person types.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.memory_segment import parse_retention

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "src" / "nodes" / "memory" / "retentionGrammar.cases.json"
CARD = ROOT / "src" / "nodes" / "memory" / "MemorySegmentNode.ts"

_TABLE = json.loads(CASES.read_text())
_CASES = [(c["input"], c["retention"], c["why"]) for c in _TABLE["cases"]]


@pytest.mark.parametrize(("raw", "expected", "why"), _CASES)
def test_the_ledger_reads_every_input_the_way_the_card_promises(
    raw: str, expected: int | None, why: str
) -> None:
    assert parse_retention(raw) == expected, why


def test_the_table_still_covers_the_four_inputs_the_ticket_measured() -> None:
    """The rows that made the card untrue. A table that quietly lost them
    would pass while the defect returned."""
    inputs = {c["input"] for c in _TABLE["cases"]}
    assert {"20.0", "1e3", "+5", "0x14"} <= inputs
    assert {"20", ""} <= inputs


def test_the_card_parses_the_field_in_exactly_one_place() -> None:
    """The DRY half. `validateRetention` and the `retention` getter were two
    copies of one grammar, so the card could disagree with *itself* — accept a
    value in the inspector and display a different bound on the card. Both now
    call `parseRetention`, and no other numeric coercion of the field survives.
    """
    source = CARD.read_text()
    assert "export const parseRetention" in source, (
        "MemorySegmentNode.ts no longer exports parseRetention. The grammar "
        "must stay one exported function, or this contract has nothing to pin."
    )
    assert source.count("parseRetention") == 3, (
        "Expected exactly three mentions: the definition, validateRetention's "
        "call, and the model's `retention` getter. A fourth is a new caller "
        "(fine — adjust this); fewer means one of the two stopped calling it, "
        "which is where a second grammar grows back."
    )
    assert "Number.isInteger" not in source, (
        "MemorySegmentNode.ts coerces with Number()/Number.isInteger again. "
        "That is the parse this ticket removed: Number('0x14') is 20, and the "
        "ledger keeps nothing for it."
    )
