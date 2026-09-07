"""What we promise about somebody else's database — install-experience 02-e/f.

Three things about memory are true of this product, none of them visible to a
reader, and all three read as missing features if you find them out by
experiment instead of by being told:

1. **We create, and we announce it.** A checkpointer and a Store are opened on
   your behalf, under `state_dir()`, and each says so in one startup line.
2. **We reuse — but only what you hand us.** `load_workflow(checkpointer=,
   store=)` for a Python caller; three environment variables for anyone else.
   Ownership is recorded at construction, so what you lend stays yours.
3. **We never go looking for yours.** No sniffing a `*.sqlite` for a
   `checkpoints` table, no adopting a `DATABASE_URL`.

The third is the one that needs writing down, because it is a *deliberate
absence* and absences are indistinguishable from oversights unless somebody
says which they are. It is also the one with the sharpest reasoning behind it
— reaching into another application's private storage on a hunch is the same
species as the Ollama-daemon rule CLAUDE.md already settled.

This file is a prose gate, in the shape `test_documented_install.py` already
established: the documentation is load-bearing here, prose drifts, and what
drifts away is a promise. It pins that the promise is stated where an adopter
reads (`adoption.md`) and that its reasoning is stated where reasoning lives
(`memory-architecture.md`), rather than pinning any particular wording.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADOPTION = ROOT / "docs" / "adoption.md"
DECISION = ROOT / "docs" / "decisions" / "memory-architecture.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestTheAdopterIsTold:
    """`adoption.md` is where somebody decides whether to lend us their
    database. The promise has to be on that page, not one link away."""

    def test_the_promise_not_to_detect_is_stated(self) -> None:
        assert re.search(
            r"never\s+(go\s+looking\s+for|look\s+for|detect|adopt)", _text(ADOPTION), re.IGNORECASE
        ), "adoption.md never says we do not go hunting for the reader's own checkpointer"

    def test_both_reuse_doors_are_named(self) -> None:
        """A Python caller passes objects; anyone else sets variables. Naming
        only the first would tell a Docker deployment it has no way in."""
        text = _text(ADOPTION)
        assert "OPENSTATEGRAPH_CHECKPOINT_PATH" in text
        assert "OPENSTATEGRAPH_MEMORY_PATH" in text
        assert "OPENSTATEGRAPH_POSTGRES_URL" in text


class TestTheReasoningIsRecorded:
    """Three reasons, each load-bearing and each already argued elsewhere in
    this document — which is why they belong here rather than in the adopter
    page, where they would be three paragraphs nobody asked for."""

    def test_there_is_nothing_to_detect(self) -> None:
        assert re.search(r"no discovery API|nothing to detect", _text(DECISION), re.IGNORECASE)

    def test_guessing_wrong_risks_corruption(self) -> None:
        text = _text(DECISION)
        assert re.search(r"two OS processes do not share|two processes", text, re.IGNORECASE)
        assert re.search(r"auto-open|guess", text, re.IGNORECASE)

    def test_thread_ids_would_collide(self) -> None:
        assert re.search(r"thread ids.{0,80}collide|collide", _text(DECISION), re.IGNORECASE)

    def test_background_formation_is_recorded_as_a_choice(self) -> None:
        """The docs name it; we do not do it; that has to read as a decision.
        Same for collection-versus-profile shape."""
        text = _text(DECISION)
        assert re.search(r"background", text, re.IGNORECASE)
        assert re.search(r"profile", text, re.IGNORECASE)
