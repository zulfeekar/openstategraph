"""`resolve.source` — which system of record answered, declared before the model.

`launch-readiness/150`, and the second rung of the declared ladder whose
first is `resolve.vocabulary` (`launch-readiness/135`, `2712704`).

Three of seven complaints in one round of user feedback were this failure,
and it is the least built of them:

> *"the AI should state the assumptions on which source (or BAV) is being
> used, and guide the user to the fact that there are multiple sources… In
> the may number 1664 is given in the table. I do not understand where this
> number comes from."*

> *"I expected the outage to reflect the plant tracker data. For russia we
> have 4031 kbd for the week starting on the 24.8. This is very different to
> the number presented in the table."*

Neither is a missing-data problem. `4031` and the table's figure **may both
be right** — the store holds the quantity at several grains from several
systems of record. The defect is that the answer named neither.

The constraint carried over from `135`, and here it is sharper:

> **A lens that declares no provider dimension and a lens with exactly one
> source must not look the same.**

One means *there is nothing to choose*; the other means *we could not tell*.
Every test below that exercises a miss asserts what the step **said about its
coverage**, not merely that it chose nothing.
"""

from __future__ import annotations

import pytest

from openstategraph.abc.tool_notes import (
    HOW_CHOSEN,
    SourceChoice,
    notes_for_model,
    notes_for_reader,
)
from openstategraph.sources import (
    DEFAULT_WHEN_UNDECIDED,
    DeclaredSource,
    resolve_source,
    unresolved_catalogue,
)

BAV = {
    "id": "bav",
    "name": "BAV",
    "default": True,
    "aliases": ["BAV", "balance a vue"],
    "grain": "monthly",
    "note": "The balances desk's own view.",
    "predicate": "WHERE provider_id = 'bav'",
}

PLANT_TRACKER = {
    "id": "plant_tracker",
    "name": "Plant tracker",
    "aliases": ["plant tracker", "tracker"],
    "grain": "weekly",
    "note": "Outage data as the refinery trackers file it.",
}

JODI = {"id": "jodi", "name": "JODI", "grain": "monthly"}


def _catalogue(rows, *, fails: bool = False):
    """A source catalogue with the contract this step asks of one."""

    def catalogue(question: str):
        if fails:
            raise RuntimeError("catalogue unreachable")
        return list(rows)

    return catalogue


class TestTheAlternativesAreThePayload:
    """`Substitution` is the wrong tuple, and this is why."""

    def test_a_source_choice_carries_what_was_not_taken(self) -> None:
        selection = resolve_source(
            "russian gasoline supply for may",
            _catalogue([BAV, PLANT_TRACKER, JODI]),
            quantity="Russian gasoline supply",
        )

        assert selection.chosen is not None
        assert selection.chosen.name == "BAV"
        assert [s.name for s in selection.alternatives] == ["JODI", "Plant tracker"]
        (note,) = selection.notes
        assert isinstance(note, SourceChoice)
        assert note.chosen == "BAV"
        assert note.alternatives == ("JODI", "Plant tracker")
        assert note.how_chosen == "declared_default"

    def test_how_chosen_is_required_and_has_no_default(self) -> None:
        """The honest field, for the same reason `how_matched` has no default.

        A choice that cannot say how it was made is exactly the record this
        must be unable to produce.
        """
        with pytest.raises(Exception):
            SourceChoice(quantity="x", chosen="BAV")  # type: ignore[call-arg]
        assert HOW_CHOSEN == ("named_in_question", "declared_default", "only_source")

    def test_the_reader_is_told_which_and_what_else(self) -> None:
        selection = resolve_source(
            "russian gasoline supply for may",
            _catalogue([BAV, PLANT_TRACKER, JODI]),
            quantity="Russian gasoline supply",
        )

        rendered = notes_for_reader(selection.notes)
        assert "BAV" in rendered
        assert "JODI" in rendered and "Plant tracker" in rendered
        assert "Russian gasoline supply" in rendered
        # The half the ticket is actually about: the reader must learn that
        # asking for another is a thing they may do.
        assert "ask for" in rendered.lower()

    def test_the_model_is_told_to_filter_rather_than_pick(self) -> None:
        selection = resolve_source(
            "russian gasoline supply", _catalogue([BAV, PLANT_TRACKER]), quantity="supply"
        )
        rendered = notes_for_model(selection.notes)
        assert "BAV" in rendered

    def test_a_substitution_and_a_source_choice_read_differently(self) -> None:
        """Two note kinds, and neither may be mistaken for the other."""
        from openstategraph.abc.tool_notes import Substitution

        substitution = Substitution(
            user_term="persian gulf",
            axis="load_shipping_region_v2",
            canonical_value="Middle East Gulf (MEG)",
            how_matched="declared_synonym",
        )
        choice = SourceChoice(
            quantity="supply", chosen="BAV", alternatives=("JODI",), how_chosen="declared_default"
        )
        assert notes_for_reader([substitution]) != notes_for_reader([choice])


class TestTheUserMayNameTheSource:
    """*"Ask for another and I will re-run."* — deterministically, before the model."""

    def test_a_named_source_beats_the_declared_default(self) -> None:
        selection = resolve_source(
            "russian outages from the plant tracker",
            _catalogue([BAV, PLANT_TRACKER]),
            quantity="Russian outages",
        )
        assert selection.chosen is not None
        assert selection.chosen.name == "Plant tracker"
        assert selection.how_chosen == "named_in_question"
        assert [s.name for s in selection.alternatives] == ["BAV"]

    def test_a_name_is_matched_on_word_boundaries(self) -> None:
        """A source chosen from inside another word is a claim nobody made."""
        selection = resolve_source(
            "jodible figures please", _catalogue([BAV, JODI]), quantity="figures"
        )
        assert selection.chosen is not None
        assert selection.chosen.name == "BAV"  # the default, not JODI

    def test_two_named_sources_are_not_a_choice(self) -> None:
        selection = resolve_source(
            "compare BAV with the plant tracker",
            _catalogue([BAV, PLANT_TRACKER]),
            quantity="supply",
        )
        assert selection.chosen is None
        assert selection.notes == ()
        assert "named more than one" in selection.render().lower()


class TestTheFourStatesThatMustNotLookAlike:
    """`135`'s constraint, sharpened: *nothing to choose* is not *cannot tell*."""

    def test_no_provider_dimension_says_silence_is_not_evidence(self) -> None:
        selection = resolve_source("anything", _catalogue([]), quantity="supply")
        report = selection.render().lower()
        assert selection.chosen is None
        assert selection.notes == ()
        assert "not evidence" in report
        assert "nothing to choose" not in report

    def test_exactly_one_source_says_there_is_nothing_to_choose(self) -> None:
        selection = resolve_source("anything", _catalogue([JODI]), quantity="supply")
        report = selection.render().lower()
        assert selection.chosen is not None
        assert selection.how_chosen == "only_source"
        assert "nothing to choose" in report
        assert "not evidence" not in report

    def test_the_two_states_do_not_render_the_same_string(self) -> None:
        undeclared = resolve_source("anything", _catalogue([]), quantity="supply").render()
        single = resolve_source("anything", _catalogue([JODI]), quantity="supply").render()
        assert undeclared != single

    def test_a_failed_lookup_is_not_a_miss(self) -> None:
        selection = resolve_source(
            "anything", _catalogue([BAV], fails=True), quantity="supply"
        )
        report = selection.render().lower()
        assert selection.chosen is None
        assert "failed" in report
        assert "not a miss" in report
        assert "not evidence" not in report

    def test_nothing_consulted_is_its_own_state(self) -> None:
        report = unresolved_catalogue("function.balance_sources").lower()
        assert "nothing was consulted" in report
        assert "not a miss" not in report

    def test_all_four_states_are_distinguishable(self) -> None:
        states = {
            resolve_source("q", _catalogue([]), quantity="s").render(),
            resolve_source("q", _catalogue([JODI]), quantity="s").render(),
            resolve_source("q", _catalogue([BAV], fails=True), quantity="s").render(),
            unresolved_catalogue("function.missing"),
        }
        assert len(states) == 4


class TestSeveralSourcesAndNoDefault:
    """`guardrails/06`'s abstain — the seam, left rather than duplicated."""

    def test_it_records_no_choice_and_says_the_run_could_not_tell(self) -> None:
        selection = resolve_source(
            "outages for russia", _catalogue([PLANT_TRACKER, JODI]), quantity="outages"
        )
        assert selection.chosen is None
        assert selection.notes == ()
        report = selection.render()
        assert "Plant tracker" in report and "JODI" in report
        assert DEFAULT_WHEN_UNDECIDED in report

    def test_two_defaults_are_undecided_rather_than_the_first_one(self) -> None:
        both = [dict(PLANT_TRACKER, default=True), dict(JODI, default=True)]
        selection = resolve_source("outages", _catalogue(both), quantity="outages")
        assert selection.chosen is None
        assert "both declare themselves the default" in selection.render().lower()

    def test_the_undecided_sentence_is_the_developers_to_word(self) -> None:
        selection = resolve_source(
            "outages",
            _catalogue([PLANT_TRACKER, JODI]),
            quantity="outages",
            when_undecided="Ask which desk they mean.",
        )
        assert "Ask which desk they mean." in selection.render()


class TestReadingACatalogueTolerantly:
    """Somebody else's Python, so its rows arrive in whatever shape it likes."""

    @pytest.mark.parametrize(
        "row, expected",
        [
            ({"source_id": "bav", "label": "BAV"}, "BAV"),
            ({"provider": "BAV"}, "BAV"),
            ({"name": "BAV", "is_default": True}, "BAV"),
            ("BAV", "BAV"),
        ],
    )
    def test_a_source_is_read_from_several_reasonable_shapes(self, row, expected) -> None:
        selection = resolve_source("q", _catalogue([row]), quantity="s")
        assert selection.chosen is not None
        assert selection.chosen.name == expected

    def test_an_unreadable_row_is_counted_never_dropped_in_silence(self) -> None:
        selection = resolve_source("q", _catalogue([JODI, 17, None]), quantity="s")
        assert selection.unreadable == 2
        assert "could not be read" in selection.render()

    def test_the_grain_is_carried_because_it_is_half_the_disagreement(self) -> None:
        """`4031` weekly and the table's monthly figure may both be right."""
        selection = resolve_source(
            "outages from the plant tracker", _catalogue([BAV, PLANT_TRACKER]), quantity="outages"
        )
        assert "weekly" in selection.render()

    def test_a_declared_source_renders_its_own_line(self) -> None:
        line = DeclaredSource(
            source_id="bav",
            name="BAV",
            is_default=True,
            aliases=("balance a vue",),
            grain="monthly",
            note="The balances desk's own view.",
            predicate="WHERE provider_id = 'bav'",
        ).render()
        assert "BAV" in line and "monthly" in line and "default" in line


class TestTheNodeType:
    """The drawn half: a `resolve.source` node, compiled and run."""

    @staticmethod
    def _document(data: dict) -> dict:
        return {
            "version": 2,
            "name": "source-test",
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
                {
                    "id": "s1",
                    "type": "resolve.source",
                    "position": {"x": 200, "y": 0},
                    "data": data,
                },
                {
                    "id": "out1",
                    "type": "output.formatted",
                    "position": {"x": 400, "y": 0},
                    "data": {},
                },
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "s1", "portId": "question"},
                },
                {
                    "source": {"nodeId": "s1", "portId": "result"},
                    "target": {"nodeId": "out1", "portId": "result"},
                },
            ],
        }

    def _run(self, data: dict, question: str, functions: dict):
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        runtime = NodeRuntime(functions=functions)
        document = self._document(data)
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        return runtime, graph.invoke({"question": question})

    def test_it_compiles_and_hands_the_declaration_downstream(self) -> None:
        _, final = self._run(
            {"catalogue": "balance_sources", "quantity": "Russian gasoline supply"},
            "russian gasoline supply for may",
            {"function.balance_sources": _catalogue([BAV, PLANT_TRACKER, JODI])},
        )
        answer = final["outputs"]["s1"]
        assert "russian gasoline supply for may" in answer  # the question survives
        assert "BAV" in answer
        assert "Plant tracker" in answer  # the alternatives travel with it
        assert "Coverage" in answer

    def test_an_unresolved_catalogue_is_reported_never_passed_through(self) -> None:
        from openstategraph.compile.diagnostics import Finding

        runtime, final = self._run({"catalogue": "missing"}, "balances", {})
        assert ("resolve.source:missing",) in runtime.diagnostics.subjects(
            Finding.UNRESOLVED_FUNCTION
        )
        assert "nothing was consulted" in final["outputs"]["s1"].lower()

    def test_the_declaration_reaches_the_reader_without_the_model(self) -> None:
        """The disclosure is not the model's to forget.

        The step records the choice against the run and `_output` renders it —
        which is the whole reason this is a node and not a prompt rule.
        """
        from openstategraph.abc.tool_notes import take_notes

        thread = "reader-rail-150"
        _, final = self._run(
            {"catalogue": "balance_sources", "quantity": "Russian gasoline supply"},
            "russian gasoline supply for may",
            {"function.balance_sources": _catalogue([BAV, JODI])},
        )
        # The run had no thread id, so nothing was recorded against one; the
        # rail itself is exercised where a thread exists.
        from openstategraph.abc.tool_notes import record_notes
        from openstategraph.sources import resolve_source as _resolve

        selection = _resolve(
            "russian gasoline supply for may",
            _catalogue([BAV, JODI]),
            quantity="Russian gasoline supply",
        )
        assert record_notes(selection.notes, thread_id=thread) is True
        assert notes_for_reader(take_notes(thread)).startswith(
            "The figures for Russian gasoline supply come from BAV"
        )
        assert "BAV" in final["outputs"]["s1"]

    def test_it_writes_no_answer(self) -> None:
        """An intermediate step, exactly like the vocabulary resolver.

        A declaration that landed in `answer` would let a run whose model
        never spoke end with a metadata block presented as its answer — so
        the step writes `outputs` only, and the answer is whatever the output
        node downstream of it makes of that.
        """
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        document = self._document({"catalogue": "balance_sources"})
        document["nodes"] = [n for n in document["nodes"] if n["id"] != "out1"]
        document["edges"] = document["edges"][:1]
        runtime = NodeRuntime(functions={"function.balance_sources": _catalogue([BAV, JODI])})
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke({"question": "balances"})

        assert "BAV" in final["outputs"]["s1"]
        assert not final.get("answer")
