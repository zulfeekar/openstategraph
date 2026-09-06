"""The card store's ladder — `team-board-and-gap-reports/02`.

`kanban_store.py` was one module holding two things that had never been
separated because there was only ever one of them: **the card's rules** — the
stage machine, the atomic claim, the evidence gate, `triage`, `column_for`,
`flagged_stale` — and **sqlite**. Fourteen functions each opened their own
`sqlite3.connect(db_path)`, and `db_path: Path` was in every signature, so even
the *type* of the first argument said sqlite. A second backing store could not
be added without editing each one, which is the engine-editing extension
`CLAUDE.md`'s **O** forbids.

## The ladder that was built, and the one that was not

`IKanbanStore` → `AbstractKanbanStore` → `SqliteKanbanStore`.

The ticket asked for the middle rung to be **decided rather than assumed**:

    Inheritance must earn itself. Where a hierarchy exists only to share two
    fields, use composition and say so.

It earns it, and the argument is one sentence: **every refusal in this family is
pure and every write is not.** `set_stage`'s evidence gate, its stage ordering,
`file_idea_card`'s brief check and `answer_card`'s two refusals are decisions
about a `Card` that no storage engine can have an opinion about — while the
write each one guards is a single conditional `UPDATE` that only the engine can
perform. A ladder with no middle rung would hand a second store the gate as well
as the write, and a second store that reimplemented `set_stage`'s conditional
`UPDATE ... WHERE stage = ?` would reintroduce `kanban-patrol/13`'s lost card on
the one board where concurrency stops being hypothetical.

So the base owns every decision and declares five primitives — `_insert_card`,
`_fetch_card`, `_advance_stage`, `_reset_card`, `_record_answer` — and a
concrete store implements those and `list_cards`/`store_digest` and nothing
else. The rules that are not about one card at all (`triage`, `column_for`,
`card_row`, `flagged_stale`, `unresolved_blockers`, `resolve_blocked_by`) stay
module-level functions in `kanban_store.py`, off the interface, so a second
store cannot disagree with them either.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from openstategraph import kanban_store
from openstategraph.abc.kanban_store import AbstractKanbanStore, IKanbanStore
from openstategraph.kanban_sqlite import SqliteKanbanStore
from openstategraph.kanban_store import (
    KANBAN_URL_ENV,
    Card,
    KanbanStoreRegistry,
    Stage,
    open_kanban_store,
)

PACKAGE = Path(kanban_store.__file__).resolve().parent


class TestTheInterface:
    def test_the_sqlite_store_is_one(self, tmp_path: Path) -> None:
        store = SqliteKanbanStore(tmp_path / "kanban.sqlite")
        assert isinstance(store, IKanbanStore)
        assert isinstance(store, AbstractKanbanStore)

    def test_it_is_narrow(self) -> None:
        """`CLAUDE.md`'s **I**: reads and writes a card, says whether anything
        changed, lists — and nothing else. The count is the class census's own
        ceiling, asserted here too because this interface is the one a second
        store has to implement in full."""
        members = {name for name in vars(IKanbanStore) if not name.startswith("_")}
        assert members == {
            "file_card",
            "file_idea_card",
            "read_card",
            "list_cards",
            "set_stage",
            "release_card",
            "answer_card",
            "store_digest",
        }

    def test_the_rules_are_not_on_it(self) -> None:
        """A second store must not be able to disagree with the order the board
        is worked in, or with which column a card is in."""
        members = set(vars(IKanbanStore))
        for rule in ("triage", "column_for", "card_row", "flagged_stale"):
            assert rule not in members
            assert callable(getattr(kanban_store, rule))


class TestOnlyOneModuleKnowsSqlite:
    def test_the_card_path_names_one_module(self) -> None:
        """`grep -rn "sqlite3" openstategraph/` names the sqlite store and the
        run/memory/SQL modules, and no board consumer."""
        offenders = sorted(
            str(path.relative_to(PACKAGE))
            for path in PACKAGE.rglob("*.py")
            if re.search(r"^\s*import sqlite3", path.read_text(), re.M)
        )
        assert offenders == [
            "evaluation/denotation.py",
            "kanban_sqlite.py",
            "memory.py",
            "prebuilt_sql.py",
            "readonly_sqlite.py",
            "run_sinks.py",
        ]

    def test_no_consumer_takes_a_db_path(self) -> None:
        """The doors address a store, never a file. `Path` in a card signature
        is what made a second store unaddable."""
        consumers = [
            PACKAGE / "cli.py",
            PACKAGE / "mcp_server.py",
            PACKAGE / "patrol.py",
            PACKAGE / "api" / "routes" / "kanban.py",
            PACKAGE / "api" / "kanban_events.py",
        ]
        for path in consumers:
            text = path.read_text()
            assert "kanban_store_path(" not in text, (
                f"{path.name} still addresses the board by file path; "
                "open_kanban_store() is the one door"
            )


class _FakeStore(AbstractKanbanStore):
    """A second implementation, which is the whole point of the seam. It is
    defined in this test rather than in the package because
    `test_a_dispatch_table_does_not_hold_its_targets.py` stays at zero: a
    registry never holds an implementation written beside it."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._cards: dict[str, Card] = {}

    def list_cards(self) -> list[Card]:
        return list(self._cards.values())

    def store_digest(self) -> str:
        return f"fake|{len(self._cards)}"

    def _insert_card(self, card: Card) -> bool:
        if card.task_id in self._cards:
            return False
        self._cards[card.task_id] = card
        return True

    def _fetch_card(self, task_id: str) -> Card | None:
        return self._cards.get(task_id)

    def _advance_stage(self, task_id, *, required_previous, stage, actor, heartbeat, evidence):
        card = self._cards.get(task_id)
        if card is None or card.stage is not required_previous:
            return False
        self._cards[task_id] = replace(
            card,
            stage=stage,
            actor=actor,
            last_heartbeat_at=heartbeat,
            evidence_test_id=evidence.test_id,
            evidence_red_reason=evidence.red_reason,
            evidence_green=evidence.green,
            evidence_commit=evidence.commit,
            finished_reason=evidence.finished_reason,
        )
        return True

    def _reset_card(self, task_id: str) -> bool:
        card = self._cards.get(task_id)
        if card is None or card.stage is Stage.UNATTENDED:
            return False
        self._cards[task_id] = replace(
            card,
            stage=Stage.UNATTENDED,
            actor=None,
            last_heartbeat_at=None,
            evidence_test_id="",
            evidence_red_reason="",
            evidence_green=False,
            evidence_commit="",
            finished_reason="",
        )
        return True

    def _record_answer(self, task_id: str, *, answer: str, actor: str, at: str) -> bool:
        card = self._cards.get(task_id)
        if card is None or card.stage is not Stage.UNATTENDED or card.answer:
            return False
        self._cards[task_id] = replace(
            card, answer=answer, answered_by=actor, answered_at=at
        )
        return True


class TestTheFactory:
    def test_no_url_opens_sqlite(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv(KANBAN_URL_ENV, raising=False)
        monkeypatch.setenv(kanban_store.KANBAN_STORE_PATH_ENV, str(tmp_path / "k.sqlite"))
        store = open_kanban_store()
        assert isinstance(store, SqliteKanbanStore)
        assert store.path == tmp_path / "k.sqlite"

    def test_a_registered_scheme_is_opened_by_name(self, monkeypatch) -> None:
        """Extend by registering — `team-board-and-gap-reports/03` adds
        Postgres this way and edits nothing here."""
        registry = KanbanStoreRegistry()
        registry.register("fake", _FakeStore)
        monkeypatch.setenv(KANBAN_URL_ENV, "fake://board")
        store = open_kanban_store(registry=registry)
        assert isinstance(store, _FakeStore)
        assert store.url == "fake://board"

    def test_an_unregistered_scheme_is_refused_by_name(self, monkeypatch) -> None:
        monkeypatch.setenv(KANBAN_URL_ENV, "mysql://board")
        with pytest.raises(ValueError) as excinfo:
            open_kanban_store(registry=KanbanStoreRegistry())
        assert "mysql" in str(excinfo.value)
        assert KANBAN_URL_ENV in str(excinfo.value)

    def test_a_duplicate_registration_raises(self) -> None:
        registry = KanbanStoreRegistry()
        registry.register("fake", _FakeStore)
        with pytest.raises(ValueError):
            registry.register("fake", _FakeStore)
        registry.upsert("fake", _FakeStore)
        assert "fake" in registry.list()


class TestTheRulesRunOnAnyStore:
    """The proof that the gate is on the base and not in the sqlite: the same
    refusals, against a store that has never seen a file."""

    def _card(self, store: AbstractKanbanStore) -> str:
        store.file_card(
            task_id="proj-a:thread-1",
            board="workflows",
            kind="bug",
            category="tool",
            title="a thing",
        )
        return "proj-a:thread-1"

    def test_the_evidence_gate_refuses_a_finish_with_no_commit(self) -> None:
        store = _FakeStore("fake://board")
        task_id = self._card(store)
        store.set_stage(task_id, Stage.ATTENDED, actor="alice")
        store.set_stage(task_id, Stage.RED, actor="alice", test_id="t::x", reason="boom")
        store.set_stage(task_id, Stage.GREEN, actor="alice", test_id="t::x")
        with pytest.raises(kanban_store.MissingEvidenceError) as excinfo:
            store.set_stage(task_id, Stage.FINISHED, actor="alice")
        assert "commit" in str(excinfo.value)

    def test_the_claim_is_first_wins(self) -> None:
        store = _FakeStore("fake://board")
        task_id = self._card(store)
        assert store.set_stage(task_id, Stage.ATTENDED, actor="alice").ok
        second = store.set_stage(task_id, Stage.ATTENDED, actor="bob")
        assert not second.ok
        assert "alice" in second.reason
