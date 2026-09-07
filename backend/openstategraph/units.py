"""What a number is measured in — declared by a developer, never chosen by a model.

`osg-agent-experience/75`. A pinned table's `quantity` column holds barrels and
a run answered *"51,106,422 tonnes"*. Nothing in the product objected: the
vocabulary declared no unit for the column, so the model supplied one, and the
grader's rubric asked that a unit be **present**, which it was.

This is the third instance of one shape, and the first two are already built
on the same rung:

| | the two states that render identically |
| --- | --- |
| `launch-readiness/127` | a word with no stated sense, and a word taken in the wrong one |
| `launch-readiness/150` | a number with no stated source, and a number from the wrong one |
| here | a number with no stated unit, and a number in the wrong one |

So the unit is declared where the vocabulary already is — one more key on the
row `openstategraph.vocabulary` already reads — and travels the note rail
`Substitution` and `SourceChoice` travel, which is what puts it in front of the
agent and the grader without either being asked to remember it.

## Tolerant in reading, strict in trusting

A declaration arrives as somebody's YAML or somebody's Python, so `barrels`,
`bbl` and `BBLS` are one unit here. What is **not** tolerant is the refusal: a
candidate is objected to only where it names a unit this module positively
recognises *and* a declaration positively contradicts it. Every other answer —
one naming no unit, one naming a unit nothing was declared about, a run with no
declaration at all — composes exactly what it composed before this module
existed. That narrowness is the safety and is the half that regresses: this
product prints figures constantly, and most of them are not measurements of a
declared column.

## Why the answer to a conversion is a refusal and not a calculation

Barrels to tonnes is not arithmetic. It needs a density, which is a property of
the cargo rather than of the row, and no table that declares only a unit
carries one. A product that converted anyway would be inventing the density —
the same act as inventing the unit, one step further from anything a reader
could check. So the platform says what it does not have, in one fixed sentence,
and a developer who *does* hold a conversion declares it on the same row.
"""

from __future__ import annotations

import re
from typing import Iterable

from openstategraph.abc.tool_notes import DeclaredUnit, ToolNote

#: What a developer may write to mean *nobody knows*. An explicit unknown is a
#: **declaration** and not a gap: it is what makes a named unit refusable
#: below, which is the whole reason the interview asks for one of the two.
UNKNOWN_UNIT_WORDS: frozenset[str] = frozenset(
    {"unknown", "unspecified", "undeclared", "none", "n/a", "na", "not declared"}
)

#: The closed lexicon, and it is closed on purpose. A family is only here
#: because refusing an answer that names one of its words is a judgement this
#: module can defend; single letters (`l`, `t`) and overloaded abbreviations
#: (`mt`, which is a station code, a state and a file extension in this
#: repository's own fixtures) are deliberately absent — a false refusal gets
#: the whole check suppressed, and a suppressed check measures nothing.
UNIT_FAMILIES: dict[str, tuple[str, ...]] = {
    "barrels": ("barrel", "barrels", "bbl", "bbls"),
    "tonnes": ("tonne", "tonnes", "metric ton", "metric tons", "metric tonne"),
    "cubic metres": ("cubic metre", "cubic metres", "cubic meter", "cubic meters", "m3"),
    "litres": ("litre", "litres", "liter", "liters"),
    "kilograms": ("kilogram", "kilograms", "kg", "kgs"),
    "gallons": ("gallon", "gallons"),
    "kilobarrels per day": ("kbd", "kb/d"),
}

#: Said when the answer names a unit for a column the data declares in another.
MISMATCHED_UNIT = (
    "The answer reports {axis} in {found}; this data declares {axis} in {declared}. "
    "Report the declared unit, and do not restate the figure in another."
)

#: Said when the answer names a unit for a column whose unit is declared
#: unknown. Refusing, rather than accepting the model's word for it, is the
#: point: an invented unit and a correct one read identically.
UNDECLARED_UNIT = (
    "The answer reports {axis} in {found} and this data declares no unit for "
    "{axis}. Say that no unit is declared rather than naming one."
)

#: Said when the *question* asked for a unit the column is not held in. The
#: sentence a reader gets, and the sentence a model is handed on the model rail
#: so the parser reads the format the prompt teaches.
NEEDS_A_DENSITY = (
    "Answering {axis} in {found} needs a density this table does not carry: it is "
    "declared in {declared} and no conversion is declared. Answer in {declared} "
    "and say the conversion is not available."
)

_WORD = re.compile(r"[a-z0-9/]+(?:\s+[a-z]+)?")


def canonical_unit(unit: str) -> str:
    """The family a written unit belongs to, or the unit itself, lowercased.

    An unrecognised unit is **its own family of one**, never a guess. A
    developer who declares `TEU` gets `TEU` compared against `TEU`, which is
    the only honest thing this module can do with a word it has never met.
    """
    text = " ".join((unit or "").split()).casefold()
    if not text:
        return ""
    for family, spellings in UNIT_FAMILIES.items():
        if text in spellings or text == family:
            return family
    return text


def units_named_in(text: str) -> set[str]:
    """Every unit family this text positively names. Word-bounded.

    A substring match would refuse an answer for containing `kg` inside a
    column name, so each spelling is matched on word boundaries — the same
    reason `vocabulary._find_in_question` is bounded.
    """
    found: set[str] = set()
    haystack = text or ""
    for family, spellings in UNIT_FAMILIES.items():
        for spelling in spellings:
            if re.search(rf"(?<!\w){re.escape(spelling)}(?!\w)", haystack, re.IGNORECASE):
                found.add(family)
                break
    return found


def declared_units(notes: Iterable[ToolNote]) -> tuple[DeclaredUnit, ...]:
    """The declarations on a run's rail, in the order they were recorded."""
    return tuple(note for note in notes if isinstance(note, DeclaredUnit))


def _declines_the_conversion(candidate: str) -> bool:
    """Whether the answer already says the one true thing about the conversion.

    Narrow on purpose: it looks for the platform's **own** sentence, which the
    model is handed on the model rail. `CLAUDE.md`'s rule about a prompt
    teaching a format the parser cannot read cuts the other way here — the
    prompt teaches this sentence, so this is the shape to read.
    """
    return "needs a density this table does not carry" in (candidate or "").casefold()


def unit_discipline(
    candidate: str,
    notes: Iterable[ToolNote],
    *,
    question: str = "",
) -> str:
    """The objection, or `""` when there is none. No model call.

    A fact about the run in the shape `unbound_capability_claim` and
    `unrun_query_claim` already use, so `route.grader`'s deterministic prelude
    can answer it before paying for a judgement — and so it prints like every
    other rule-based rejection, `check` and all.
    """
    declarations = declared_units(notes)
    if not declarations:
        return ""
    named = units_named_in(candidate)
    if not named:
        return ""
    if _declines_the_conversion(candidate):
        return ""
    asked = units_named_in(question)

    for note in declarations:
        declared = canonical_unit(note.unit)
        allowed = {canonical_unit(unit) for unit in note.convertible_to}
        allowed.discard("")
        if declared:
            allowed.add(declared)
        wrong = sorted(named - allowed)
        if not wrong:
            continue
        found = wrong[0]
        axis = note.axis or "these figures"
        if not declared:
            return UNDECLARED_UNIT.format(axis=axis, found=found)
        if found in asked:
            return NEEDS_A_DENSITY.format(axis=axis, found=found, declared=declared)
        return MISMATCHED_UNIT.format(axis=axis, found=found, declared=declared)
    return ""


__all__ = [
    "MISMATCHED_UNIT",
    "NEEDS_A_DENSITY",
    "UNDECLARED_UNIT",
    "UNIT_FAMILIES",
    "UNKNOWN_UNIT_WORDS",
    "canonical_unit",
    "declared_units",
    "unit_discipline",
    "units_named_in",
]
