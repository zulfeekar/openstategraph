"""Tests for the orchestrator ladder.

An orchestrator's whole job is turning one instruction into a bounded list of
named subtasks — it does not run or judge them. These tests are deliberately
about decomposition only; the fan-out and join are graph concerns, tested in
test_node_runtime.py against a real compiled graph.
"""

from __future__ import annotations

import pytest

from openstategraph.abc.orchestrator import (
    BaseOrchestrator,
    MAX_SUBTASKS,
    Orchestrator,
    PlanningOrchestrator,
    Subtask,
    orchestrator_for,
)

from conftest import RespondingModel  # noqa: F401  (shared test double)


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


class TestANumberedListsPreamble:
    """Ticket 15's batch-B facet, found in a `fanout-in-a-loop` control run.

    `_NUMBERED` splits on `(?:^|\n)`, so `re.split` hands back whatever
    precedes the first numbered item as piece #1. A brief written the way
    anyone writes one — a summary line, then the items — therefore planned
    one subtask too many, and with `maxSubtasks` set to the list's own length
    the *last real item* was then dropped by the ceiling. The judgement step
    of a three-part brief never ran and nothing said so.
    """

    BRIEF = (
        "Compare two ways to deploy a Python service, then judge which is safer.\n"
        "1. Describe deploying it in a container on a machine you run.\n"
        "2. Describe deploying it to a managed platform.\n"
        "3. Judge which of the two is safer to operate."
    )

    def test_a_leading_summary_is_not_a_subtask(self) -> None:
        subtasks = Orchestrator().plan(self.BRIEF)
        assert len(subtasks) == 3
        assert not subtasks[0].instruction.startswith("Compare two ways")

    def test_the_last_item_survives_a_cap_set_to_the_lists_own_length(self) -> None:
        subtasks = Orchestrator(max_subtasks=3).plan(self.BRIEF)
        assert "safer" in subtasks[-1].instruction

    def test_the_summary_is_carried_as_context_rather_than_discarded(self) -> None:
        # It is what makes the judgement item answerable at all: a worker
        # sees its own subtask and nothing else.
        subtasks = Orchestrator().plan(self.BRIEF)
        assert "Compare two ways to deploy" in subtasks[-1].instruction

    def test_a_bare_numbered_list_is_unchanged(self) -> None:
        subtasks = Orchestrator().plan("1. Find the genre\n2. Find the artist")
        assert [t.instruction for t in subtasks] == ["Find the genre", "Find the artist"]


class TestBounding:
    def test_a_runaway_split_is_capped(self) -> None:
        many = "\n".join(f"{i}. task {i}" for i in range(1, 30))
        subtasks = Orchestrator().plan(many)
        # A 500-item numbered list must not fan out to 500 subagents.
        assert len(subtasks) == MAX_SUBTASKS

    def test_the_cap_is_configurable(self) -> None:
        subtasks = Orchestrator(max_subtasks=2).plan("a; b; c; d")
        assert len(subtasks) == 2

    def test_dropping_a_subtask_at_the_ceiling_is_reported(self) -> None:
        """The other half of ticket 15's batch-B facet, and a bug on its own.

        Truncation was a silent slice: the report still had its sections and
        looked complete. A caller with a channel passes the sink; the note
        names what was dropped so the run says so.
        """
        notes: list[str] = []
        Orchestrator(max_subtasks=2).plan("a; b; c; d", notes=notes)
        assert len(notes) == 1
        assert "2" in notes[0] and "dropped" in notes[0].lower()

    def test_a_plan_that_fits_reports_nothing(self) -> None:
        notes: list[str] = []
        Orchestrator(max_subtasks=8).plan("a; b", notes=notes)
        assert notes == []


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
            def split(self, instruction: str, feedback: str = "") -> list[str]:
                # Stands in for a real model call.
                return [f"subtask number {i} of many" for i in range(20)]

        subtasks = ModelOrchestrator().plan("anything")
        assert len(subtasks) == MAX_SUBTASKS
        assert subtasks[0].id == "task-1"

    def test_subtask_is_a_named_shape_not_a_bare_string(self) -> None:
        subtask = Subtask(id="task-1", instruction="x")
        assert subtask.id == "task-1"
        assert subtask.instruction == "x"


class TestModelDrivenPlanning:
    """Ticket 15: decomposing English is a judgement, not a rule.

    The deterministic splitter is kept and still runs for a rule-less card;
    what a developer's rules now buy is a planning *call*, which is the only
    thing that can turn "two arguments for and against daily standups" into
    two answerable subtasks instead of two grammatical fragments.
    """

    def test_the_model_decides_the_subtasks(self) -> None:
        model = RespondingModel(
            [],
            default=(
                "Give two arguments in favour of daily standups.\n"
                "Give two arguments against daily standups."
            ),
        )
        subtasks = PlanningOrchestrator(model=model, rules="Split by stance.").plan(
            "Give me two arguments for and against daily standups."
        )
        assert [t.instruction for t in subtasks] == [
            "Give two arguments in favour of daily standups.",
            "Give two arguments against daily standups.",
        ]

    def test_the_planning_call_carries_the_locked_machinery_and_the_rules(self) -> None:
        model = RespondingModel([], default="one\ntwo")
        PlanningOrchestrator(model=model, rules="Never plan more than two.").plan("x and y")
        prompt = model.calls[0]
        assert BaseOrchestrator.PREAMBLE in prompt
        # The contract is last, and a developer's rules cannot displace it.
        assert prompt.rindex(BaseOrchestrator.OUTPUT_CONTRACT) > prompt.rindex(
            "Never plan more than two."
        )

    def test_the_ceiling_is_stated_to_the_planner(self) -> None:
        # Cheaper than planning eight and dropping five at the ceiling.
        model = RespondingModel([], default="one\ntwo")
        PlanningOrchestrator(model=model, rules="r", max_subtasks=3).plan("x and y")
        assert "3" in model.calls[0]

    def test_numbering_and_bullets_in_the_reply_are_stripped(self) -> None:
        model = RespondingModel(
            [],
            default="1. Find the first thing\n- Find the second thing\n* Find the third thing",
        )
        subtasks = PlanningOrchestrator(model=model, rules="r").plan("anything")
        assert [t.instruction for t in subtasks] == [
            "Find the first thing",
            "Find the second thing",
            "Find the third thing",
        ]

    def test_a_failed_planning_call_falls_back_to_the_deterministic_split(self) -> None:
        class Exploding:
            def invoke(self, _messages: object) -> object:
                raise RuntimeError("no")

        subtasks = PlanningOrchestrator(model=Exploding(), rules="r").plan(
            "count the invoices; count the tracks"
        )
        assert [t.instruction for t in subtasks] == [
            "count the invoices",
            "count the tracks",
        ]

    def test_an_empty_reply_falls_back_rather_than_planning_nothing(self) -> None:
        model = RespondingModel([], default="   ")
        subtasks = PlanningOrchestrator(model=model, rules="r").plan("a; b")
        assert len(subtasks) == 2

    def test_the_rejection_reaches_the_planning_call(self) -> None:
        """Ticket 23: a supervisor's feedback edge could re-dispatch but not
        re-plan, because the splitter was deterministic on an instruction that
        never changed. Feeding the rejection *into* the split — rather than
        appending it to each subtask afterwards — is what makes the port name
        true."""
        model = RespondingModel([], default="one\ntwo")
        PlanningOrchestrator(model=model, rules="r").plan(
            "compare two deployments",
            feedback="Name the safer option in the first sentence of task 3.",
        )
        assert "Name the safer option" in model.calls[0]

    def test_the_deterministic_splitter_ignores_feedback_by_design(self) -> None:
        # Documented, unchanged behaviour: a regex cannot act on a critique,
        # and pretending otherwise would put the rejection text through the
        # separators as if it were more work to do.
        assert Orchestrator().split("a; b", "please be more decisive") == ["a", "b"]


class TestStrategySelection:
    """`orchestrator_for` is the one place config chooses a decomposition."""

    def test_authored_rules_and_a_model_plan_with_the_model(self) -> None:
        planner = orchestrator_for(rules="Split by stance.", model=object())
        assert isinstance(planner, PlanningOrchestrator)

    def test_a_wired_skill_counts_as_authored_rules(self) -> None:
        planner = orchestrator_for(skill="# how to split\n...", model=object())
        assert isinstance(planner, PlanningOrchestrator)

    def test_no_rules_stays_deterministic_and_therefore_free(self) -> None:
        # The zero-token path is the default, and a card that says nothing
        # must not start paying for a planning call.
        planner = orchestrator_for(model=object())
        assert type(planner) is Orchestrator

    def test_rules_with_no_model_stay_deterministic(self) -> None:
        planner = orchestrator_for(rules="Split by stance.", model=None)
        assert type(planner) is Orchestrator


class TestSubtaskHygiene:
    """Ticket 61 residual: fragments carry context, duplicates collapse."""

    def test_a_conjunction_fragment_carries_the_parent_instruction(self) -> None:
        from openstategraph.abc.orchestrator import Orchestrator
        plan = Orchestrator().plan("Compare the current weather in Oslo and Madrid.")
        assert len(plan) == 2
        assert "part of the request" in plan[1].instruction
        assert "Madrid" in plan[1].instruction and "Oslo" in plan[1].instruction

    def test_duplicate_pieces_collapse_to_one_dispatch(self) -> None:
        from openstategraph.abc.orchestrator import Orchestrator
        plan = Orchestrator().plan("check the weather; check the weather; count the tables")
        assert [t.instruction for t in plan][0].startswith("check the weather")
        assert len(plan) == 2

    def test_a_single_piece_instruction_is_never_decorated(self) -> None:
        from openstategraph.abc.orchestrator import Orchestrator
        plan = Orchestrator().plan("Top sellers")
        assert plan[0].instruction == "Top sellers"
