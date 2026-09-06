"""One behaviour suite, run against every store there is —
`team-board-and-gap-reports/03`.

The failure this is written against is the one `team-board-and-gap-reports/11`
names: a second store ships, its tests need a database, CI has none, so they
skip and go green forever while the suite reports on the store nobody looks at.

So the body below is written once and parametrised over the implementations.
SQLite always runs. Postgres runs when — and only when —
`OPENSTATEGRAPH_KANBAN_TEST_URL` names a database to run it against; unset, it
skips with a message naming the variable, and CI never sets it. **A separate
variable from `OPENSTATEGRAPH_KANBAN_URL` on purpose**: the board variable
points at the maintainers' real board, and a test suite that filed and staged
cards against whatever a developer had exported would be a suite that writes
on the board it is meant to be independent of.

What is deliberately still open, so it is not mistaken for covered: the
in-memory fake that would let CI run this body against a third implementation,
the RLS *denial* case (a connection scoped to one project reading zero rows of
another), and the browser pass on the tab. Those are ticket 11's, named there,
and inventing a second fake here is work that ticket would have to undo.

The live run leaves its rows where they are. Every case scopes itself with a
fresh random `project_hash`, so two runs never see each other, and a store with
no delete on its interface is a store this suite cannot tidy up through —
which is the correct shape, since retention on the shared board is a job that
runs as the owner (`team-board-and-gap-reports/09`/`10`).
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Iterator

import pytest

from openstategraph.abc.kanban_store import AbstractKanbanStore
from openstategraph.kanban_store import (
    MissingEvidenceError,
    Stage,
    StageOrderError,
)
from openstategraph.kanban_sqlite import SqliteKanbanStore

LIVE_URL_ENV = "OPENSTATEGRAPH_KANBAN_TEST_URL"


@pytest.fixture(params=["sqlite", "postgres"])
def store(request: pytest.FixtureRequest, tmp_path) -> Iterator[AbstractKanbanStore]:
    if request.param == "sqlite":
        yield SqliteKanbanStore(tmp_path / "kanban.sqlite")
        return

    url = os.environ.get(LIVE_URL_ENV, "").strip()
    if not url:
        pytest.skip(
            f"{LIVE_URL_ENV} is not set — the Postgres half of this contract "
            "needs a database to be true about, and CI has none. Export it to "
            "a scratch database to run it."
        )
    from openstategraph.kanban_postgres import PostgresKanbanStore

    yield PostgresKanbanStore(url, project_hash=secrets.token_hex(16))


def file_one(store: AbstractKanbanStore, task_id: str = "t-1") -> str:
    store.file_card(
        task_id=task_id,
        board="workflows",
        kind="task",
        category="redundant-tool-calls",
        title="A title",
        priority="high",
        area="backend",
        priority_reason="because",
    )
    return task_id


def test_a_filed_card_reads_back_as_it_was_written(store: AbstractKanbanStore) -> None:
    task_id = file_one(store)
    card = store.read_card(task_id)
    assert card.task_id == task_id
    assert card.board == "workflows"
    assert card.stage is Stage.UNATTENDED
    assert card.priority == "high"
    assert card.area == "backend"
    assert card.evidence_green is False
    assert card.blocked_by == ()
    assert [one.task_id for one in store.list_cards()] == [task_id]


def test_filing_the_same_finding_twice_is_one_card(store: AbstractKanbanStore) -> None:
    file_one(store)
    file_one(store)
    assert len(store.list_cards()) == 1


def test_an_unknown_card_is_a_key_error(store: AbstractKanbanStore) -> None:
    with pytest.raises(KeyError):
        store.read_card("nobody-filed-this")


def test_the_stage_machine_runs_end_to_end(store: AbstractKanbanStore) -> None:
    task_id = file_one(store)
    assert store.set_stage(task_id, Stage.ATTENDED, actor="agent-a").ok
    assert store.set_stage(
        task_id, Stage.RED, actor="agent-a", test_id="tests/x.py::y", reason="fails"
    ).ok
    assert store.set_stage(
        task_id, Stage.GREEN, actor="agent-a", test_id="tests/x.py::y"
    ).ok
    assert store.set_stage(
        task_id, Stage.FINISHED, actor="agent-a", commit="abc1234", reason="all green"
    ).ok
    card = store.read_card(task_id)
    assert card.stage is Stage.FINISHED
    assert card.evidence_green is True
    assert card.evidence_commit == "abc1234"
    assert card.finished_reason == "all green"


def test_a_skipped_stage_is_refused(store: AbstractKanbanStore) -> None:
    task_id = file_one(store)
    with pytest.raises(StageOrderError):
        store.set_stage(task_id, Stage.GREEN, actor="agent-a", test_id="tests/x.py::y")


def test_red_without_evidence_is_refused(store: AbstractKanbanStore) -> None:
    task_id = file_one(store)
    store.set_stage(task_id, Stage.ATTENDED, actor="agent-a")
    with pytest.raises(MissingEvidenceError):
        store.set_stage(task_id, Stage.RED, actor="agent-a", reason="no test id")


def test_the_second_claimant_is_told_who_holds_it(store: AbstractKanbanStore) -> None:
    """The one guarantee that is a conditional write rather than a rule, and
    the reason `_advance_stage` is a single `UPDATE ... WHERE stage = ?` in
    both stores. On the shared board two maintainers racing is ordinary."""
    task_id = file_one(store)
    assert store.set_stage(task_id, Stage.ATTENDED, actor="agent-a").ok
    lost = store.set_stage(task_id, Stage.ATTENDED, actor="agent-b")
    assert lost.ok is False
    assert "agent-a" in lost.reason
    assert store.read_card(task_id).actor == "agent-a"


def test_an_answer_is_written_once(store: AbstractKanbanStore) -> None:
    task_id = "t-question"
    store.file_card(
        task_id=task_id,
        board="workflows",
        kind="grilling",
        category="judgement",
        title="Which way?",
    )
    assert store.answer_card(task_id, actor="owner", answer="that way").ok
    second = store.answer_card(task_id, actor="someone-else", answer="this way")
    assert second.ok is False
    assert "owner" in second.reason
    assert store.read_card(task_id).answer == "that way"


def test_a_card_that_is_not_stale_is_not_released(store: AbstractKanbanStore) -> None:
    task_id = file_one(store)
    store.set_stage(task_id, Stage.ATTENDED, actor="agent-a")
    result = store.release_card(task_id)
    assert result.ok is False
    assert store.read_card(task_id).stage is Stage.ATTENDED


def test_an_idea_card_keeps_its_brief_and_its_blockers(
    store: AbstractKanbanStore,
) -> None:
    first = store.file_idea_card(
        project_id="proj",
        kind="task",
        title="The first",
        story="a story",
        done_when="an assertion",
        priority="med",
        priority_reason="a reason",
    )
    second = store.file_idea_card(
        project_id="proj",
        kind="task",
        title="The second",
        story="a story",
        done_when="an assertion",
        priority="med",
        priority_reason="a reason",
        blocked_by=[first],
    )
    card = store.read_card(second)
    assert card.story == "a story"
    assert card.blocked_by == (first,)


def test_the_digest_moves_on_a_write_and_not_on_a_read(
    store: AbstractKanbanStore,
) -> None:
    """What the board's live poll actually asks. A digest that moved on a read
    would push a refetch to every open board once a second; one that did not
    move on a write would leave a filed card invisible until a reload."""
    before = store.store_digest()
    task_id = file_one(store)
    after = store.store_digest()
    assert after != before
    store.read_card(task_id)
    store.list_cards()
    assert store.store_digest() == after


def test_every_store_the_registry_holds_is_covered_here() -> None:
    """The parametrisation above is a list, and a list goes stale the day a
    third store is registered. This is the row that notices."""
    from openstategraph.kanban_store import default_kanban_store_registry

    assert set(default_kanban_store_registry().list()) == {
        "sqlite",
        "postgresql",
        "postgres",
    }


def opener_for(scheme: str) -> Callable[[str], object]:
    from openstategraph.kanban_store import default_kanban_store_registry

    opener = default_kanban_store_registry().get(scheme)
    assert opener is not None
    return opener


@pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
def test_both_spellings_open_the_same_store(scheme: str) -> None:
    from openstategraph.kanban_postgres import open_postgres_kanban_store

    assert opener_for(scheme) is open_postgres_kanban_store


def test_an_unreachable_board_raises_and_names_the_variable() -> None:
    """`postgres.py`'s rule, and the one that must not be softened: a board
    that quietly fell back to this laptop's file when the shared one was asked
    for is two people disagreeing about what the board says, a week later.
    Port 1 is closed everywhere, so this connects to nothing and does it fast.
    """
    psycopg_pool = pytest.importorskip("psycopg_pool")
    assert psycopg_pool is not None
    from openstategraph.kanban_postgres import open_postgres_kanban_store
    from openstategraph.postgres import PostgresUnavailable

    with pytest.raises(PostgresUnavailable) as raised:
        open_postgres_kanban_store("postgresql://someone:secret@127.0.0.1:1/board")

    message = str(raised.value)
    assert "OPENSTATEGRAPH_KANBAN_URL" in message
    assert "OPENSTATEGRAPH_POSTGRES_URL" not in message
    assert "secret" not in message, "a DSN's password never reaches a message"
