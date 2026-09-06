"""Path-addressed doors onto a sqlite board — for tests only.

`team-board-and-gap-reports/02` moved the card store behind `IKanbanStore` and
took `db_path: Path` out of every production signature: the doors open a board
through `open_kanban_store()` and never name a file. The tests that predate that
split address one by path, because a `tmp_path` fixture *is* how a test names a
throwaway store, and because their whole value in this ticket is that they pass
**unchanged** — that is the "no behaviour change" proof, and an assertion edited
while the code under it moves proves nothing.

So the mechanical constructor swap the ticket allows lives here, once, instead
of at two hundred and fifty call sites. Every function is one line: build the
concrete sqlite store for that path and call the method. Nothing in the package
imports this module, and `test_the_card_store_has_a_seam.py` asserts that no
consumer takes a path.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from openstategraph import kanban_store as _rules
from openstategraph.kanban_sqlite import SqliteKanbanStore
from openstategraph.kanban_store import Card, SetStageResult, Stage


def store(db_path: Path) -> SqliteKanbanStore:
    return SqliteKanbanStore(db_path)


def ensure_schema(db_path: Path) -> None:
    store(db_path).ensure_schema()


def file_card(db_path: Path, **kwargs: object) -> None:
    store(db_path).file_card(**kwargs)  # type: ignore[arg-type]


def file_idea_card(db_path: Path, **kwargs: object) -> str:
    return store(db_path).file_idea_card(**kwargs)  # type: ignore[arg-type]


def read_card(db_path: Path, task_id: str) -> Card:
    return store(db_path).read_card(task_id)


def list_cards(db_path: Path) -> list[Card]:
    return store(db_path).list_cards()


def set_stage(
    db_path: Path,
    task_id: str,
    stage: Stage,
    *,
    actor: str,
    test_id: str = "",
    reason: str = "",
    commit: str = "",
) -> SetStageResult:
    return store(db_path).set_stage(
        task_id, stage, actor=actor, test_id=test_id, reason=reason, commit=commit
    )


def release_card(
    db_path: Path, task_id: str, *, threshold_seconds: int = 3600
) -> SetStageResult:
    return store(db_path).release_card(task_id, threshold_seconds=threshold_seconds)


def answer_card(db_path: Path, task_id: str, *, actor: str, answer: str) -> SetStageResult:
    return store(db_path).answer_card(task_id, actor=actor, answer=answer)


def store_digest(db_path: Path) -> str:
    return store(db_path).store_digest()


def flagged_stale(db_path: Path, *, threshold_seconds: int) -> list[str]:
    return _rules.flagged_stale(store(db_path), threshold_seconds=threshold_seconds)


def unresolved_blockers(db_path: Path, card: Card) -> tuple[str, ...]:
    return _rules.unresolved_blockers(store(db_path), card)


def known_card_ids(db_path: Path) -> frozenset[str]:
    return frozenset(card.task_id for card in list_cards(db_path))


__all__ = [
    "Sequence",
    "answer_card",
    "ensure_schema",
    "file_card",
    "file_idea_card",
    "flagged_stale",
    "known_card_ids",
    "list_cards",
    "read_card",
    "release_card",
    "set_stage",
    "store",
    "store_digest",
    "unresolved_blockers",
]
