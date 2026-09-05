"""Triage — `osg-agent-experience/25`.

An idea board with a dozen cards is not a queue; nothing says which to pick
up first. `triage` is the owner's rule made a pure function, so both the MCP
door and the CLI answer with the same order and can be tested without a
store: unblocked work that other work is waiting on comes first (more
dependents earlier), then unblocked work by priority, then blocked work last
— and every row says, in one sentence, which of those rules put it there.

Pure and stateless on purpose (decision 10 / least-confident-decision 2 in
`03-program-design.md`): nothing is stored, so nothing can drift from the
board it was computed from.
"""

from __future__ import annotations

from openstategraph.kanban_store import Card, Stage, TriageRow, triage


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


class TestUnblockedThatBlockOthersComeFirst:
    def test_more_dependents_ranks_earlier(self) -> None:
        # b and c both block a bit; d blocks nothing.
        a = _card("a")
        b = _card("b")
        c = _card("c")
        d = _card("d", blocked_by=("a", "b"))
        e = _card("e", blocked_by=("a", "b", "c"))
        rows = triage([a, b, c, d, e])
        # a and b each block 2 (d, e); c blocks 1 (e); d and e block nothing
        # and are themselves blocked, so they sort to the tail.
        ids = [row.card.task_id for row in rows]
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("c")
        assert ids[-2:] == ["d", "e"] or set(ids[-2:]) == {"d", "e"}

    def test_why_here_names_the_dependent_count(self) -> None:
        a = _card("a")
        _b = _card("b", blocked_by=("a",))
        _c = _card("c", blocked_by=("a",))
        rows = triage([a, _b, _c])
        top = rows[0]
        assert top.card.task_id == "a"
        assert "unblocks 2 cards" in top.why_here


class TestUnblockedNonBlockersOrderByPriority:
    def test_high_before_med_before_low(self) -> None:
        low = _card("low", priority="low")
        med = _card("med", priority="med")
        high = _card("high", priority="high")
        rows = triage([low, med, high])
        assert [row.card.task_id for row in rows] == ["high", "med", "low"]

    def test_why_here_names_priority_and_that_nothing_waits(self) -> None:
        high = _card("high", priority="high")
        rows = triage([high])
        assert rows[0].why_here == "high priority, nothing waits on it"


class TestBlockedCardsSortLast:
    def test_blocked_after_every_unblocked_card(self) -> None:
        blocker = _card("blocker")
        blocked = _card("blocked", blocked_by=("blocker",))
        low_unblocked = _card("low-unblocked", priority="low")
        rows = triage([blocked, blocker, low_unblocked])
        ids = [row.card.task_id for row in rows]
        assert ids.index("blocked") > ids.index("blocker")
        assert ids.index("blocked") > ids.index("low-unblocked")

    def test_why_here_names_the_blocker(self) -> None:
        blocker = _card("blocker-one")
        blocked = _card("blocked-one", blocked_by=("blocker-one",))
        rows = triage([blocker, blocked])
        row = next(r for r in rows if r.card.task_id == "blocked-one")
        assert "blocker-one" in row.why_here
        assert "blocked" in row.why_here.lower()

    def test_blocked_cards_keep_the_same_sub_order(self) -> None:
        # Both blocked; "many-deps" blocks two live cards, "few-deps" blocks
        # none of the live cards itself — the blocked group is ordered by
        # the same dependents-then-priority rule as the unblocked group.
        root = _card("root")
        many_deps = _card("many-deps", blocked_by=("root",))
        dep_a = _card("dep-a", blocked_by=("many-deps",))
        dep_b = _card("dep-b", blocked_by=("many-deps",))
        few_deps = _card("few-deps", blocked_by=("root",), priority="low")
        rows = triage([root, many_deps, dep_a, dep_b, few_deps])
        ids = [row.card.task_id for row in rows]
        assert ids.index("many-deps") < ids.index("few-deps")


class TestFinishedCardsAreExcluded:
    def test_a_finished_card_is_not_in_the_output(self) -> None:
        done = _card("done", stage=Stage.FINISHED)
        open_card = _card("open")
        rows = triage([done, open_card])
        assert [row.card.task_id for row in rows] == ["open"]

    def test_a_finished_blocker_does_not_block(self) -> None:
        finished_blocker = _card("finished-blocker", stage=Stage.FINISHED)
        formerly_blocked = _card("formerly-blocked", blocked_by=("finished-blocker",))
        rows = triage([finished_blocker, formerly_blocked])
        assert len(rows) == 1
        row = rows[0]
        assert row.card.task_id == "formerly-blocked"
        assert "blocked by" not in row.why_here.lower()


class TestEveryRowHasARank:
    def test_rank_is_one_indexed_and_sequential(self) -> None:
        rows = triage([_card("a"), _card("b"), _card("c")])
        assert [row.rank for row in rows] == [1, 2, 3]

    def test_every_row_carries_a_non_empty_why_here(self) -> None:
        rows = triage(
            [
                _card("a"),
                _card("b", blocked_by=("a",)),
                _card("c", priority="low"),
            ]
        )
        for row in rows:
            assert isinstance(row, TriageRow)
            assert row.why_here.strip()

    def test_empty_board_is_empty_output(self) -> None:
        assert triage([]) == ()


class TestABlockerNoCardCarriesIsSaidDifferently:
    """`osg-agent-experience/30`'s second done-when. "blocked by <id>" reads
    the same whether the blocker is a card somebody will finish or an id that
    will never exist, and only one of those two clears by working the board."""

    def test_a_blocker_that_is_a_card_reads_as_before(self) -> None:
        rows = triage([_card("blocker"), _card("blocked", blocked_by=("blocker",))])
        blocked = next(r for r in rows if r.card.task_id == "blocked")
        assert blocked.why_here == "blocked by blocker"

    def test_a_blocker_no_card_carries_says_so(self) -> None:
        rows = triage([_card("blocked", blocked_by=("ghost",))])
        assert rows[0].why_here == "blocked by an id no card carries: ghost"

    def test_a_mix_names_both_halves(self) -> None:
        rows = triage(
            [_card("blocker"), _card("blocked", blocked_by=("blocker", "ghost"))]
        )
        blocked = next(r for r in rows if r.card.task_id == "blocked")
        assert blocked.why_here == (
            "blocked by blocker, and by an id no card carries: ghost"
        )

    def test_a_finished_card_still_counts_as_a_card_that_carries_the_id(self) -> None:
        """A finished blocker is spent, so it does not block at all — it must
        never be reported as an id nothing carries."""
        rows = triage(
            [
                _card("done", stage=Stage.FINISHED),
                _card("blocked", blocked_by=("done",)),
            ]
        )
        assert "no card carries" not in rows[0].why_here
