"""What a number is measured in, declared by the developer and checked by the run.

`osg-agent-experience/75`. A pinned table's `quantity` column holds barrels; a
run answered *"51,106,422 tonnes"*, and every instrument agreed with it. The
vocabulary rows named *tonnes* and *barrels* as words the domain uses and
declared no unit for the column, so the model supplied one; the grader's rubric
asked that a unit be **present**, which it was.

Both halves of the defect are the same shape as the two failures this rung of
the ladder already exists for — `launch-readiness/127`'s *a word with no stated
sense* and `150`'s *a number with no stated source*. A number with no stated
unit and a number in the wrong unit are indistinguishable, and the second is
the one that gets published.

So the unit is **declared where the vocabulary already lives** — one more key
on the row the resolver already reads, never a second file — and travels the
rail `Substitution` and `SourceChoice` already travel, which is what puts it in
front of the agent and the grader with nobody having to remember to.

The narrowness is the safety and is asserted here as hard as the refusals are:
a run whose vocabulary declares no unit, and an answer that names none, must
compose exactly what it composed before this module existed.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from conftest import RespondingModel  # noqa: E402

from openstategraph.abc import tool_notes  # noqa: E402
from openstategraph.compile.node_runtime import NodeRuntime  # noqa: E402
from openstategraph.compile.workflow_compiler import CompiledPlan  # noqa: E402

from openstategraph.abc.tool_notes import (
    DeclaredUnit,
    Substitution,
    notes_for_grader,
    notes_for_model,
    notes_for_reader,
    record_notes,
    take_notes,
)
from openstategraph.units import (
    NEEDS_A_DENSITY,
    canonical_unit,
    unit_discipline,
    units_named_in,
)
from openstategraph.vocabulary import resolve_vocabulary


THREAD = "75-thread"

DOCUMENT: dict[str, Any] = {
    "nodes": [
        {"id": "a1", "type": "agent.llm", "data": {}},
        {"id": "g1", "type": "route.grader", "data": {"maxAttempts": 2}},
        {"id": "out1", "type": "output.formatted", "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "a1", "portId": "result"},
            "target": {"nodeId": "g1", "portId": "candidate"},
        }
    ],
}


@pytest.fixture(autouse=True)
def _a_run_to_record_against(monkeypatch: pytest.MonkeyPatch) -> Any:
    take_notes(THREAD)
    monkeypatch.setattr(tool_notes, "_current_thread", lambda: THREAD)
    yield
    take_notes(THREAD)


BARRELS = DeclaredUnit(axis="shipments.quantity", unit="barrels")
UNKNOWN = DeclaredUnit(axis="shipments.quantity", unit="")


def _source(rows):
    def search(_phrase: str):
        return rows

    return search


class TestTheRowDeclaresIt:
    """The pin file the resolvers already read, carrying one more key."""

    def test_a_row_naming_a_unit_is_read_as_declaring_it(self) -> None:
        resolution = resolve_vocabulary(
            "how much moved",
            _source([{"term": "quantity", "axis": "shipments.quantity", "unit": "barrels"}]),
            phrases=["quantity"],
        )
        assert resolution.entries[0].unit == "barrels"
        assert resolution.units == (BARRELS,)

    def test_a_row_saying_unknown_declares_that_nobody_knows(self) -> None:
        """The interview's second legal answer. It is a declaration, not a
        gap: it is what makes a named unit refusable below."""
        resolution = resolve_vocabulary(
            "how much moved",
            _source([{"term": "quantity", "axis": "shipments.quantity", "unit": "unknown"}]),
            phrases=["quantity"],
        )
        assert resolution.units == (UNKNOWN,)

    def test_a_row_that_declares_nothing_mints_nothing(self) -> None:
        """Silence by default, the whole module's rule. A row with no unit key
        makes no claim, so the run makes none on its behalf."""
        resolution = resolve_vocabulary(
            "how much moved",
            _source([{"term": "quantity", "axis": "shipments.quantity"}]),
            phrases=["quantity"],
        )
        assert resolution.units == ()

    def test_the_declared_unit_is_in_the_block_the_agent_reads(self) -> None:
        """Composed context, never an editable rule — the agent's half of the
        done-when. The block is what `resolve.vocabulary` writes downstream."""
        resolution = resolve_vocabulary(
            "how much moved",
            _source([{"term": "quantity", "axis": "shipments.quantity", "unit": "barrels"}]),
            phrases=["quantity"],
        )
        block = resolution.render()
        assert "shipments.quantity" in block and "barrels" in block

    def test_a_declared_conversion_is_read_from_the_same_row(self) -> None:
        resolution = resolve_vocabulary(
            "how much moved",
            _source([
                {
                    "term": "quantity",
                    "axis": "shipments.quantity",
                    "unit": "barrels",
                    "converts_to": ["tonnes"],
                }
            ]),
            phrases=["quantity"],
        )
        assert resolution.units[0].convertible_to == ("tonnes",)


class TestItReachesBothJudges:
    """The rail, not a fourth channel."""

    def test_the_model_is_told_the_unit_and_told_not_to_convert(self) -> None:
        line = notes_for_model([BARRELS])
        assert "shipments.quantity" in line and "barrels" in line

    def test_the_reader_is_told_what_the_figures_are_in(self) -> None:
        assert "barrels" in notes_for_reader([BARRELS])

    def test_the_grader_sees_it_framed_as_the_workflows_own(self) -> None:
        text = notes_for_grader([BARRELS])
        assert "barrels" in text and "This workflow appends" in text

    def test_an_undeclared_unit_says_so_rather_than_going_quiet(self) -> None:
        assert "no unit" in notes_for_reader([UNKNOWN]).lower()


class TestTheGraderRefusesRatherThanInvents:
    """The fixed sentences. Each is a `Verdict.reject` reason in the same
    deterministic prelude `unbound_capability_claim` and `unrun_query_claim`
    already sit in — a fact about the run, answered before a model is paid."""

    def test_barrels_declared_and_an_answer_in_tonnes_is_refused(self) -> None:
        reason = unit_discipline("The total was 51,106,422 tonnes.", [BARRELS])
        assert reason
        assert "tonnes" in reason and "barrels" in reason

    def test_an_undeclared_unit_is_refused_and_says_which(self) -> None:
        reason = unit_discipline("The total was 51,106,422 tonnes.", [UNKNOWN])
        assert reason
        assert "shipments.quantity" in reason
        assert "no unit" in reason.lower()

    def test_the_declared_unit_itself_passes(self) -> None:
        assert unit_discipline("The total was 51,106,422 barrels.", [BARRELS]) == ""

    def test_a_declared_synonym_of_the_declared_unit_passes(self) -> None:
        """Tolerant in reading. `bbl` is the same measurement as `barrels`, and
        refusing it would teach a developer to write prose the parser likes."""
        assert unit_discipline("51,106,422 bbl moved.", [BARRELS]) == ""

    def test_an_answer_naming_no_unit_at_all_is_left_alone(self) -> None:
        """The narrowness. This product prints figures constantly and most of
        them name nothing; a widening that fails here fails everywhere."""
        assert unit_discipline("The total was 51,106,422.", [BARRELS]) == ""

    def test_a_run_with_no_declaration_is_exactly_as_it_was(self) -> None:
        assert unit_discipline("The total was 51,106,422 tonnes.", []) == ""
        assert unit_discipline("The total was 51,106,422 tonnes.", [Substitution(
            user_term="MEG", axis="region", canonical_value="Middle East Gulf",
            how_matched="declared_synonym",
        )]) == ""


class TestAConversionNeedsSomethingTheTableDoesNotCarry:
    def test_tonnes_asked_barrels_declared_is_answered_with_the_density(self) -> None:
        reason = unit_discipline(
            "That is 6,970,000 tonnes.",
            [BARRELS],
            question="How many tonnes moved?",
        )
        assert "needs a density this table does not carry" in reason

    def test_a_declared_conversion_is_allowed(self) -> None:
        declared = DeclaredUnit(
            axis="shipments.quantity", unit="barrels", convertible_to=("tonnes",)
        )
        assert unit_discipline(
            "That is 6,970,000 tonnes.", [declared], question="How many tonnes moved?"
        ) == ""

    def test_declining_the_conversion_is_a_pass(self) -> None:
        """The refusal clause the grader base already makes: an answer that
        says it cannot be produced, and why, is a correct answer."""
        assert unit_discipline(
            "The data is in barrels; converting needs a density this table does "
            "not carry, so I cannot answer in tonnes.",
            [BARRELS],
            question="How many tonnes moved?",
        ) == ""

    def test_the_sentence_is_one_string_and_not_retyped(self) -> None:
        assert "needs a density this table does not carry" in NEEDS_A_DENSITY


class TestTheLexiconIsClosed:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("6,970,000 tonnes", {"tonnes"}),
            ("6,970,000 bbl", {"barrels"}),
            ("a barrel of laughs", {"barrels"}),
            ("the total was 51106422", set()),
            ("SELECT sum(quantity) FROM shipments", set()),
        ],
    )
    def test_only_a_recognised_unit_word_counts(self, text: str, expected: set[str]) -> None:
        assert units_named_in(text) == expected

    def test_an_unrecognised_declared_unit_is_its_own_family(self) -> None:
        """Strict in trusting, and it must not silently agree with everything:
        a developer who declares `TEU` gets `TEU`, not a guess."""
        assert canonical_unit("TEU") == "teu"
        assert canonical_unit("bbls") == "barrels"


class TestTheRealGraderRefusesWithoutAModel:
    """The layer the defect lives at: a compiled `route.grader`, a rail with a
    declaration on it, and no grading call paid for.

    A green unit engine wired into nothing is the trap `production-ready` 71
    and ticket 33 both paid for — a test at the wrong layer that stays green
    against a disabled fix. So this drives the node.
    """

    def _grade(self, candidate: str, question: str = "how much moved") -> tuple[dict, list]:
        model = RespondingModel([], default="PASS\nlooks fine")
        runtime = NodeRuntime(model=model)
        plan = CompiledPlan(
            nodes=["a1", "g1", "out1"],
            edges=[("a1", "g1")],
            conditional={"g1": {"pass": "out1", "revise": "a1"}},
        )
        run = runtime.factory(DOCUMENT)("g1", DOCUMENT["nodes"][1], plan)
        outcome = run(
            {"outputs": {"a1": candidate}, "question": question, "revisions": {}}
        )
        update = asyncio.run(outcome) if inspect.isawaitable(outcome) else outcome
        return update, model.calls

    def test_it_rejects_the_wrong_unit(self) -> None:
        record_notes((BARRELS,))
        update, _ = self._grade("The total was 51,106,422 tonnes.")
        assert update["verdicts"]["g1"]["verdict"] == "revise"
        assert update["verdicts"]["g1"]["check"] == "unit_mismatch"

    def test_no_model_was_asked_for_the_verdict(self) -> None:
        record_notes((BARRELS,))
        _, calls = self._grade("The total was 51,106,422 tonnes.")
        assert calls == []

    def test_the_reason_names_both_units(self) -> None:
        record_notes((BARRELS,))
        update, _ = self._grade("The total was 51,106,422 tonnes.")
        reason = update["verdicts"]["g1"]["reason"]
        assert "barrels" in reason and "tonnes" in reason

    def test_the_declared_unit_reaches_the_judgement_as_context(self) -> None:
        """The rubric half of the done-when: composed context, not an editable
        rule, and there whether or not a criterion mentions units."""
        record_notes((BARRELS,))
        _, calls = self._grade("The total was 51,106,422 barrels.")
        assert calls and "barrels" in calls[0]

    def test_a_run_with_no_declaration_still_asks_the_model(self) -> None:
        update, calls = self._grade("The total was 51,106,422 tonnes.")
        assert calls, "an ordinary run must compose exactly what it always did"
        assert update["verdicts"]["g1"]["verdict"] == "pass"
