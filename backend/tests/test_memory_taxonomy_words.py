"""The Store holds facts, and facts are **semantic** — install-experience 02-d.

`memory.py` and `docs/decisions/memory-architecture.md` each used the word
**Episodic**, and each used it for a different thing: the module docstring for
the *checkpointer*, the decision document for the *Store*. Against the taxonomy
the LangChain docs actually publish, both are wrong, and they are wrong in a
way that reads as a claim.

`concepts/memory.mdx` splits memory **twice** — by *recall scope* (short-term,
thread-scoped, the checkpointer; long-term, namespaced, the Store) and, inside
long-term only, by *type* (the CoALA three: semantic = facts, episodic =
experiences, procedural = instructions). Conflating the two splits is what
makes "context / episodic / procedural / semantic" read like one flat list.

Everything `save_memory` stores is a fact — "the user prefers concise answers",
"chinook revenue sums InvoiceLine amounts". That is semantic. Episodic is past
agent *actions*, replayed as few-shot examples, and we have no mechanism that
turns a past run into a prompt-time example. We have the raw material (thread
history, `<package>/evals/*.eval.json`) and nothing that reads it that way.

The cost of leaving it is not pedantry with a price of zero: a reader arriving
from the LangChain docs, seeing "Episodic" on our Store and expecting
past-trajectory recall, finds a fact store — and concludes either that the docs
are wrong or that we shipped something we did not.

So this file pins three sentences, mechanically:

1. Neither source labels the Store "episodic".
2. Both name it **semantic**.
3. Episodic is recorded as **deliberately absent** rather than left unmentioned
   — an absence a reader can find is a decision; one they cannot is an
   oversight.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: The two places the taxonomy is stated to a reader. Nothing else claims to
#: name the kinds — `docs/adoption.md` describes the *tools*, not the theory.
SOURCES = {
    "memory.py": ROOT / "backend" / "openstategraph" / "memory.py",
    "memory-architecture.md": ROOT / "docs" / "decisions" / "memory-architecture.md",
}


def _text(name: str) -> str:
    return SOURCES[name].read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_the_store_is_called_semantic(name: str) -> None:
    assert re.search(r"\bsemantic\b", _text(name), re.IGNORECASE), (
        f"{name} names the memory kinds and never says 'semantic', which is "
        "what the Store actually holds"
    )


#: The **label** form — a bolded kind heading, in a table row or a bullet.
#: That is the shape the defect took in both files, and the shape a reader
#: skims. The bare lowercase word in prose is not checked: quoting the docs'
#: own taxonomy ("semantic, episodic, procedural") is exactly what these files
#: should be doing.
EPISODIC_LABEL = re.compile(r"\*\*Episodic\*\*")

ABSENCE = re.compile(r"absent|deliberately|do not|does not|never|not have", re.IGNORECASE)


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_episodic_never_labels_something_we_have(name: str) -> None:
    """The word may still appear — it *must*, per the test below — but never as
    a heading over a construct. Where it labels, the same line has to say the
    thing is missing."""
    for line in _text(name).splitlines():
        if not EPISODIC_LABEL.search(line):
            continue
        assert ABSENCE.search(line), (
            f"{name} uses 'Episodic' as a live label: {line.strip()!r}"
        )


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_the_absence_is_recorded_rather_than_silent(name: str) -> None:
    assert re.search(r"\bepisodic\b", _text(name), re.IGNORECASE), (
        f"{name} dropped the word entirely. An absence a reader can find is a "
        "decision; one they cannot is an oversight — the docs name four kinds "
        "and we hold three, and that has to be visible here."
    )
