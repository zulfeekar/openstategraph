"""The Guardrail card and the Guardrail ladder declare the same two vocabularies.

The sibling of `test_mcp_field_contract.py`, and filed for the same reason it
was: a vocabulary that exists in both languages because both halves use it, with
nothing holding the two together, is a hand-mirror without a pin — which
CLAUDE.md's DRY rule names as the thing it forbids.

The architecture review of 2026-08-16 found this gap by grep: no file in
`backend/` mentions `GUARDRAIL_STRATEGIES`, and no file in `src/` mentions
`BUILTIN_ENTITIES`, so the two five-word lists agreed only by coincidence and
attention. Worse, `GuardrailNode.ts:18-21` asserts a guarantee that did not
exist — *"a release adding `phone` fails a Python test rather than leaving a
card that quietly cannot deliver it"*. A Python test failing does not edit a
TypeScript array. This file is what makes that sentence true.

The two failure directions are not symmetric, and both are bad:

- **Python gains a word the card does not offer.** A protection ships that no
  user can select; the strategy or entity is unreachable from the editor.
- **The card offers a word Python does not implement.** `BaseGuardrail.resolved`
  raises `ValueError` at compile time (`abc/guardrail.py:221-225`) — by design,
  because "a card that claims a protection which does not exist" must not be
  silent. But the loud failure lands on the user at run time rather than on us
  at review time, which is the whole point of moving it here.

Read out of the TypeScript source rather than out of a build artifact: the card
is the thing a developer edits, and a pin against a generated file would go
quiet exactly when somebody edits the source and does not rebuild.
"""

from __future__ import annotations

import re
from pathlib import Path

from openstategraph.abc.guardrail import BUILTIN_ENTITIES, STRATEGIES

ROOT = Path(__file__).resolve().parents[2]
FIELD_SET = ROOT / "src" / "nodes" / "guard" / "GuardrailNode.ts"


def _string_array(name: str) -> list[str]:
    """The string literals of one exported `const NAME = [...]` array."""
    source = FIELD_SET.read_text()
    block = re.search(rf"export const {name} = \[(.*?)\]", source, re.S)
    assert block, f"GuardrailNode.ts no longer declares {name}"
    return re.findall(r"'([^']+)'", block.group(1))


def test_the_card_offers_exactly_the_strategies_the_ladder_implements() -> None:
    assert _string_array("GUARDRAIL_STRATEGIES") == list(STRATEGIES), (
        "GuardrailNode.ts's GUARDRAIL_STRATEGIES and abc/guardrail.py's STRATEGIES "
        "have diverged. Order matters too: it is the order the card's select "
        "offers them in, and `pass` leading is the argument that list makes."
    )


def test_the_card_offers_exactly_the_entities_the_ladder_detects() -> None:
    assert _string_array("GUARDRAIL_BUILTIN_ENTITIES") == list(BUILTIN_ENTITIES), (
        "GuardrailNode.ts's GUARDRAIL_BUILTIN_ENTITIES and abc/guardrail.py's "
        "BUILTIN_ENTITIES have diverged. An entity only Python knows is a "
        "protection nobody can select; an entity only the card knows is a "
        "ValueError out of BaseGuardrail.resolved at compile time."
    )


def test_the_extractor_can_actually_fail() -> None:
    """Guards the regex, not the lists.

    A matcher that silently found nothing would make both assertions above
    vacuous — the defect class the census tests in this suite exist for.
    """
    assert _string_array("GUARDRAIL_STRATEGIES")
    assert _string_array("GUARDRAIL_BUILTIN_ENTITIES")
    assert _string_array("GUARDRAIL_STRATEGIES") != _string_array(
        "GUARDRAIL_BUILTIN_ENTITIES"
    )
