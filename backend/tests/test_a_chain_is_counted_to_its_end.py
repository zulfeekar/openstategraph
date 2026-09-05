"""`osg-agent-experience/66` — triage counted only what a card blocks directly.

Three cards in a chain — A blocks B, B blocks C — and `kanban triage` put A
first with

    unblocks 1 card

The *order* was right and the *evidence printed beside it* understated the case
by two thirds. `why_here` exists so a reader can weigh the rule that put a card
where it is, and a reader weighing "unblocks 1 card" against a `high` priority
card with nothing waiting on it would reasonably take the other one — which is
the whole failure mode, since nothing else on that board can start until A
lands.

So the count is transitive, and the sort key with it: a count the reader is
shown and a count the order was computed from that disagree is worse than
either alone. When the two numbers differ the line says both, because "unblocks
4 cards" for a card one thing waits on directly is its own kind of misreport.

Cycles are guarded rather than assumed away. `blocked_by` is free text
resolved against the board (`resolve_blocked_by`), so nothing on the write path
refuses A→B→A, and a reachability walk that trusts the graph is acyclic hangs
the door rather than mis-sorting it.
"""

from __future__ import annotations

import pytest

from openstategraph.kanban_store import Card, Stage, triage


def _card(
    task_id: str,
    *,
    priority: str = "med",
    blocked_by: tuple[str, ...] = (),
    stage: Stage = Stage.UNATTENDED,
) -> Card:
    return Card(
        task_id=task_id,
        board="workflows",
        kind="task",
        category="task",
        title=task_id,
        stage=stage,
        actor=None,
        last_heartbeat_at=None,
        priority=priority,
        area="backend",
        priority_reason="because",
        filed_at="2026-09-04T00:00:00+00:00",
        evidence_test_id="",
        evidence_red_reason="",
        evidence_green=False,
        evidence_commit="",
        answer="",
        answered_by="",
        answered_at="",
        blocked_by=blocked_by,
    )


def _why(rows, task_id: str) -> str:
    return next(row.why_here for row in rows if row.card.task_id == task_id)


class TestTheChainTheTicketWasFiledOver:
    def test_a_three_card_chain_counts_to_its_end(self) -> None:
        a = _card("a")
        b = _card("b", blocked_by=("a",))
        c = _card("c", blocked_by=("b",))

        rows = triage([a, b, c])

        assert rows[0].card.task_id == "a"
        assert _why(rows, "a") == "unblocks 1 card directly, 2 in all"

    def test_a_card_that_blocks_one_leaf_says_one_number(self) -> None:
        """The other half: when direct and transitive agree there is one
        number, because a second clause that always says the same thing is a
        clause a reader stops reading."""
        a = _card("a")
        b = _card("b", blocked_by=("a",))

        rows = triage([a, b])

        assert _why(rows, "a") == "unblocks 1 card"

    def test_a_chain_outranks_a_high_priority_card_nothing_waits_on(self) -> None:
        """The decision the understated number was being weighed against."""
        a = _card("a", priority="low")
        b = _card("b", blocked_by=("a",))
        c = _card("c", blocked_by=("b",))
        lone = _card("lone", priority="high")

        rows = triage([a, b, c, lone])

        assert rows[0].card.task_id == "a"

    def test_the_order_uses_the_same_number_it_prints(self) -> None:
        """A deep chain against a wide fan-out of two. Under the direct count
        the fan-out wins; under the transitive count the chain does, and the
        printed sentence has to be the one the sort used."""
        deep = _card("deep")
        d1 = _card("d1", blocked_by=("deep",))
        d2 = _card("d2", blocked_by=("d1",))
        d3 = _card("d3", blocked_by=("d2",))
        wide = _card("wide")
        w1 = _card("w1", blocked_by=("wide",))
        w2 = _card("w2", blocked_by=("wide",))

        rows = triage([deep, d1, d2, d3, wide, w1, w2])

        assert rows[0].card.task_id == "deep"
        assert _why(rows, "deep") == "unblocks 1 card directly, 3 in all"
        assert _why(rows, "wide") == "unblocks 2 cards"


class TestWhatIsNotCounted:
    def test_a_finished_blocker_is_spent_at_every_depth(self) -> None:
        """`triage` already treats a finished card's hold as discharged. A
        transitive walk must inherit that at depth, not only at the first
        hop."""
        a = _card("a")
        b = _card("b", blocked_by=("a",), stage=Stage.FINISHED)
        c = _card("c", blocked_by=("b",))

        rows = triage([a, b, c])

        # `c` is unblocked (its blocker finished) and nothing waits on `a`.
        assert _why(rows, "a") == "med priority, nothing waits on it"

    def test_a_diamond_counts_each_card_once(self) -> None:
        a = _card("a")
        b = _card("b", blocked_by=("a",))
        c = _card("c", blocked_by=("a",))
        d = _card("d", blocked_by=("b", "c"))

        rows = triage([a, b, c, d])

        assert _why(rows, "a") == "unblocks 2 cards directly, 3 in all"

    def test_an_id_no_card_carries_adds_nothing(self) -> None:
        a = _card("a", blocked_by=("nobody:has-this",))

        rows = triage([a])

        assert "unblocks" not in _why(rows, "a")


class TestTheCycleGuard:
    def test_a_two_card_cycle_terminates(self) -> None:
        a = _card("a", blocked_by=("b",))
        b = _card("b", blocked_by=("a",))

        rows = triage([a, b])

        assert len(rows) == 2

    def test_a_card_never_counts_itself(self) -> None:
        """Reachability from `a` in a cycle includes `a`. Counting it would
        report a card as unblocking itself, which is not a fact about the
        board."""
        a = _card("a", blocked_by=("c",))
        b = _card("b", blocked_by=("a",))
        c = _card("c", blocked_by=("b",))

        rows = triage([a, b, c])

        # Every card in the cycle reaches the other two, itself excluded.
        for task_id in ("a", "b", "c"):
            assert "3 in all" not in _why(rows, task_id)


class TestBothDoorsSayIt:
    """The CLI and the MCP tool call the identical `triage`, so this is one
    assertion that the sentence survives the trip rather than two orderings."""

    def test_the_cli_prints_the_transitive_sentence(self, tmp_path, capsys) -> None:
        from openstategraph import cli
        from openstategraph.kanban_store import (
            ensure_schema,
            file_idea_card,
            kanban_store_path,
        )

        (tmp_path / "workflows").mkdir()
        db = kanban_store_path(tmp_path / "workflows")
        ensure_schema(db)
        blocked: tuple[str, ...] = ()
        for title in ("first", "second", "third"):
            task_id = file_idea_card(
                db,
                project_id="p",
                kind="task",
                title=title,
                story="a story",
                done_when="a check",
                priority="med",
                priority_reason="because",
                blocked_by=blocked,
            )
            blocked = (task_id,)

        cli.main(["kanban", "triage", "--workflows-root", str(tmp_path / "workflows")])

        assert "unblocks 1 card directly, 2 in all" in capsys.readouterr().out


@pytest.mark.parametrize("depth", [2, 5, 20])
def test_a_chain_of_any_depth_counts_every_card_below_it(depth: int) -> None:
    cards = [_card("c0")] + [_card(f"c{i}", blocked_by=(f"c{i - 1}",)) for i in range(1, depth)]

    rows = triage(cards)

    expected = "unblocks 1 card" if depth == 2 else f"unblocks 1 card directly, {depth - 1} in all"
    assert _why(rows, "c0") == expected
