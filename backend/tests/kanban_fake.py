"""An in-memory board — the third implementation of `IKanbanStore`.

`team-board-and-gap-reports/11`. The failure this exists to close: the Postgres
store's half of the contract suite needs a database, CI has none, so it skips
and goes green forever. A fake that runs everywhere means the *rules* on
`AbstractKanbanStore` are proven against more than one concrete on every run,
so a rule that only worked because of something sqlite happens to do is caught
by the default suite rather than by whoever next exports a URL.

**It is an implementation, not a mock.** A mock records calls and asserts about
them, and can never *fail* a contract suite — which is the whole point of
having one. This supplies the seven primitives `AbstractKanbanStore` declares
and inherits every rule unchanged: stage order, the evidence gate, the
conditional claim, the answer-written-once guard, staleness, digest movement.
When a rule is wrong, this store fails the same assertion sqlite does.

## Why it lives in `tests/` and not in the package

`CLAUDE.md` names `src/core/testing/` as the precedent for where a fake lives,
and that directory is inside the shipped tree because vitest resolves from it.
Python's equivalent of "importable by the suite, absent from the wheel" is
`backend/tests/`, which `kanban_by_path.py` already occupies for the same
reason. Shipping this in `openstategraph/` would put a store that loses every
card on restart one `register()` call away from `OPENSTATEGRAPH_KANBAN_URL`,
and the map's whole argument is that a board must never quietly fall back to
something that is not the board.

## The conditional writes are conditional here too

`_advance_stage`, `_reset_card` and `_record_answer` each check their guard and
write in one step, against the dict that *is* the store — never a
read-then-check-then-write over a copy handed to a caller. A fake that got that
wrong would pass the contract suite while proving nothing about the guarantee
the suite is mostly there for, and `cards` is therefore never handed out by
reference: `list_cards` and `_fetch_card` return the frozen `Card` values held
here, which cannot be mutated into the store from outside.

Not thread-safe, and deliberately not: the real race is two processes on one
Postgres, which is `OPENSTATEGRAPH_KANBAN_TEST_URL`'s half of the suite. A lock
here would only prove this module's lock works.
"""

from __future__ import annotations

import dataclasses
import itertools

from openstategraph.abc.kanban_store import AbstractKanbanStore
from openstategraph.kanban_store import Card, CardEvidence, Stage

#: The scheme this store answers to. Never registered in
#: `default_kanban_store_registry()` — a test registers it into a fresh
#: `KanbanStoreRegistry`, which is the registry's own reason for being
#: constructible rather than a module singleton.
FAKE_SCHEME = "memory"

#: The address form. There is only one in-memory board per store object, so the
#: authority part is inert; it exists so the opener has the same
#: `(url: str) -> IKanbanStore` shape as the other two and the registry holds
#: one kind of thing.
FAKE_URL = f"{FAKE_SCHEME}://board"


class FakeKanbanStore(AbstractKanbanStore):
    """Every rule on the base, over a dict."""

    def __init__(self) -> None:
        self._cards: dict[str, Card] = {}
        #: The digest has to move on a write and stand still on a read, and a
        #: card count cannot do that: filing then finishing a card leaves the
        #: count where it was. A monotonic counter bumped by the writes — and
        #: only by the writes that actually changed something — is the smallest
        #: thing that answers the question `KanbanChangeWatcher` asks.
        self._writes = itertools.count()
        self._version = 0

    # -- the primitives `AbstractKanbanStore` decides with -----------------

    def list_cards(self) -> list[Card]:
        return list(self._cards.values())

    def store_digest(self) -> str:
        return f"memory|{len(self._cards)}|{self._version}"

    def _insert_card(self, card: Card) -> bool:
        if card.task_id in self._cards:
            return False
        self._cards[card.task_id] = card
        self._bump()
        return True

    def _fetch_card(self, task_id: str) -> Card | None:
        return self._cards.get(task_id)

    def _advance_stage(
        self,
        task_id: str,
        *,
        required_previous: Stage,
        stage: Stage,
        actor: str,
        heartbeat: str,
        evidence: CardEvidence,
    ) -> bool:
        return self._write_if(
            task_id,
            lambda card: card.stage is required_previous,
            stage=stage,
            actor=actor,
            last_heartbeat_at=heartbeat,
            evidence_test_id=evidence.test_id,
            evidence_red_reason=evidence.red_reason,
            evidence_green=evidence.green,
            evidence_commit=evidence.commit,
            finished_reason=evidence.finished_reason,
        )

    def _reset_card(self, task_id: str) -> bool:
        return self._write_if(
            task_id,
            lambda card: card.stage is not Stage.UNATTENDED,
            stage=Stage.UNATTENDED,
            actor=None,
            last_heartbeat_at=None,
            evidence_test_id="",
            evidence_red_reason="",
            evidence_green=False,
            evidence_commit="",
            finished_reason="",
        )

    def _record_answer(self, task_id: str, *, answer: str, actor: str, at: str) -> bool:
        return self._write_if(
            task_id,
            lambda card: card.stage is Stage.UNATTENDED and card.answer == "",
            answer=answer,
            answered_by=actor,
            answered_at=at,
        )

    # -- the one write ------------------------------------------------------

    def _write_if(self, task_id: str, guard, **changes: object) -> bool:
        """Guard and write in one step, mirroring the single conditional
        `UPDATE ... WHERE` both real stores use. The guard reads the card held
        here, not one a caller passed in, so there is no window between the
        check and the write for a second caller to land in."""
        card = self._cards.get(task_id)
        if card is None or not guard(card):
            return False
        self._cards[task_id] = dataclasses.replace(card, **changes)  # type: ignore[arg-type]
        self._bump()
        return True

    def _bump(self) -> None:
        self._version = next(self._writes) + 1


def open_fake_kanban_store(url: str) -> FakeKanbanStore:
    """The opener a test registers under `FAKE_SCHEME`.

    Takes a URL it does not read, for the reason `open_sqlite_kanban_store`
    takes one: every store in the registry is addressed the same way, and a
    registry holding two shapes of opener is a registry a caller has to branch
    on.
    """
    assert url.startswith(f"{FAKE_SCHEME}://"), url
    return FakeKanbanStore()


__all__ = ["FAKE_SCHEME", "FAKE_URL", "FakeKanbanStore", "open_fake_kanban_store"]
