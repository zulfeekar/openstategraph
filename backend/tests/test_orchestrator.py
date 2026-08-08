"""Tests for the orchestrator ladder.

An orchestrator's whole job is turning one instruction into a bounded list of
named subtasks — it does not run or judge them. These tests are deliberately
about decomposition only; the fan-out and join are graph concerns, tested in
test_node_runtime.py against a real compiled graph.
"""

from __future__ import annotations

import pytest

from dyflow.abc.orchestrator import BaseOrchestrator, MAX_SUBTASKS, Orchestrator, Subtask


class TestDeterministicSplit:
    def test_a_numbered_list_becomes_one_subtask_per_item(self) -> None:
        subtasks = Orchestrator().plan(
            "1. Find the top genre by revenue\n2. Find the top artist by revenue"
        )
        assert [t.instruction for t in subtasks] == [
            "Find the top genre by revenue",
            "Find the top artist by revenue",
        ]

    def test_semicolons_split_independent_instructions(self) -> None:
        subtasks = Orchestrator().plan("List all tables; get the Track schema")
        assert len(subtasks) == 2
        assert subtasks[0].instruction == "List all tables"
        assert subtasks[1].instruction == "get the Track schema"

    def test_the_word_and_splits_when_nothing_more_explicit_is_present(self) -> None:
        subtasks = Orchestrator().plan("Query genre revenue and query artist revenue")
        assert len(subtasks) == 2

    def test_an_unsplittable_instruction_is_still_one_subtask_not_zero(self) -> None:
        # A single unit of work is not a dead end.
        subtasks = Orchestrator().plan("Which genre earned the most revenue?")
        assert len(subtasks) == 1
        assert subtasks[0].instruction == "Which genre earned the most revenue?"

    def test_an_empty_instruction_produces_no_subtasks_rather_than_a_blank_one(self) -> None:
        assert Orchestrator().plan("   ") == []

    def test_numbered_lists_are_preferred_over_splitting_on_and_inside_an_item(self) -> None:
        # "1. Revenue by genre and by artist" should stay one subtask per number,
        # not further fragment on the "and" inside item 1.
        subtasks = Orchestrator().plan(
            "1. Revenue by genre and by artist\n2. Top customer by spend"
        )
        assert len(subtasks) == 2
        assert "and" in subtasks[0].instruction


class TestBounding:
    def test_a_runaway_split_is_capped(self) -> None:
        many = "\n".join(f"{i}. task {i}" for i in range(1, 30))
        subtasks = Orchestrator().plan(many)
        # A 500-item numbered list must not fan out to 500 subagents.
        assert len(subtasks) == MAX_SUBTASKS

    def test_the_cap_is_configurable(self) -> None:
        subtasks = Orchestrator(max_subtasks=2).plan("a; b; c; d")
        assert len(subtasks) == 2


class TestIdentity:
    def test_every_subtask_gets_a_stable_readable_id(self) -> None:
        subtasks = Orchestrator().plan("a; b; c")
        assert [t.id for t in subtasks] == ["task-1", "task-2", "task-3"]

    def test_ids_are_usable_as_dict_keys_for_joining_results(self) -> None:
        subtasks = Orchestrator().plan("a; b")
        joined = {t.id: f"result for {t.instruction}" for t in subtasks}
        # Fragments carry parent context (ticket 61) — the property under
        # test is that ids key the join, not the instruction spelling.
        assert joined["task-1"].startswith("result for a")

    def test_a_later_generation_never_reuses_an_earlier_ones_ids(self) -> None:
        """Found live, not hypothetically.

        A real revise loop replanned with the plain `plan()` default and
        produced `task-1`/`task-2` again on the second attempt — identical to
        the first — which silently aliased onto the *rejected* attempt's
        entries in the shared `worker_results` dict, blending stale and fresh
        results under one key. `generation` is what a caller uses to keep every
        attempt's ids in their own namespace.
        """
        first = {t.id for t in Orchestrator().plan("a; b", generation=0)}
        second = {t.id for t in Orchestrator().plan("a; b", generation=1)}
        assert first.isdisjoint(second)

    def test_generation_zero_keeps_the_plain_id_scheme(self) -> None:
        # Backward compatible with every caller that never passes generation.
        assert [t.id for t in Orchestrator().plan("a; b", generation=0)] == [
            "task-1",
            "task-2",
        ]


class TestLadder:
    def test_the_default_needs_no_model(self) -> None:
        # Deterministic decomposition of a punctuated instruction is a rule's
        # job, not a judgement — so no model dependency for the common case.
        assert Orchestrator().plan("a; b")

    def test_the_base_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            BaseOrchestrator()  # type: ignore[abstract]

    def test_a_model_driven_subclass_inherits_bounding_and_ids_for_free(self) -> None:
        class ModelOrchestrator(BaseOrchestrator):
            def split(self, instruction: str) -> list[str]:
                # Stands in for a real model call.
                return [f"sub-{i}" for i in range(20)]

        subtasks = ModelOrchestrator().plan("anything")
        assert len(subtasks) == MAX_SUBTASKS
        assert subtasks[0].id == "task-1"

    def test_subtask_is_a_named_shape_not_a_bare_string(self) -> None:
        subtask = Subtask(id="task-1", instruction="x")
        assert subtask.id == "task-1"
        assert subtask.instruction == "x"


class TestSubtaskHygiene:
    """Ticket 61 residual: fragments carry context, duplicates collapse."""

    def test_a_conjunction_fragment_carries_the_parent_instruction(self) -> None:
        from dyflow.abc.orchestrator import Orchestrator
        plan = Orchestrator().plan("Compare the current weather in Oslo and Madrid.")
        assert len(plan) == 2
        assert "part of the request" in plan[1].instruction
        assert "Madrid" in plan[1].instruction and "Oslo" in plan[1].instruction

    def test_duplicate_pieces_collapse_to_one_dispatch(self) -> None:
        from dyflow.abc.orchestrator import Orchestrator
        plan = Orchestrator().plan("check the weather; check the weather; count the tables")
        assert [t.instruction for t in plan][0].startswith("check the weather")
        assert len(plan) == 2

    def test_a_single_piece_instruction_is_never_decorated(self) -> None:
        from dyflow.abc.orchestrator import Orchestrator
        plan = Orchestrator().plan("Top sellers")
        assert plan[0].instruction == "Top sellers"
