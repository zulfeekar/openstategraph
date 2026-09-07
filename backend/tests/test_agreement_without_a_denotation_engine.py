"""Agreement needs no ground truth — and today it needs a SQLite file anyway.

`launch-readiness/170`. `126` built `eval --repeat N` for two questions it
could not then put in the dataset: the Persian Gulf and dark-vessel cases are
answered against Databricks, `denotation.connect_readonly` is `sqlite3`, and
`EvalCase` requires `gold_sql` for anything it will call answerable.

170 asks whether the answer is a second denotation engine, since agreement is
measured by comparing runs to *each other*. Reading the harness, the honest
answer is **neither of the two the ticket offers**:

- `gold_sql` is genuinely not required to *compare* two runs. It is required
  only by `EvalCase`'s validator, which is a rule about grading correctness.
- But permitting a gold-less case buys nothing on its own, because **both**
  axes `_case_agreement` compares today reach the database.
  `verdicts_agree` compares grades, which come from executing gold;
  `results_agree` re-executes each lap's own statement against the committed
  file. A gold-less warehouse case would report `verdicts` that agree because
  every lap was graded the same coarse way, and `results_agree: None`. Three
  different answers, all confident, would be published as agreement — which is
  the exact false green this map is named after, and strictly worse than the
  measurement being absent.

What is missing is neither gold nor an engine: it is a comparison axis that
needs no database at all. `126`'s symptom was *one question, three answers* —
three different **figures**. Comparing the quantities each lap asserted needs
no warehouse, no committed rows, no network and no model, and
`grounded_numbers.quantities_in` already draws the line between a quantity and
a version number or a list marker.

So this file pins the third axis. It never weakens the strong one: where rows
were comparable, rows decide. Where they were not — which is every warehouse
case, and today is reported only as `unmeasurable` — the figures decide, and
`unmeasurable` shrinks to the cases where nothing could tell at all.
"""

from __future__ import annotations

from openstategraph.evaluation.dataset import EvalCase
from openstategraph.evaluation.runner import Comparable, _agreement_block, _case_agreement


def _case(id_: str = "c1") -> EvalCase:
    return EvalCase(id=id_, question="how many?", gold_sql="SELECT 1")


def _lap(verdict: str, rows, figures: str):
    from openstategraph.evaluation.scoring import ItemVerdict

    item = ItemVerdict(
        case_id="c1",
        question="how many?",
        difficulty="easy",
        expects="answer",
        verdict=verdict,
    )
    return item, Comparable.of(rows=rows, answer=figures)


class TestTheFiguresAxis:
    def test_two_laps_asserting_the_same_figure_agree(self) -> None:
        graded = [
            _lap("correct", None, "There are 6,119 dark vessels."),
            _lap("correct", None, "6119 dark vessels were found."),
        ]
        assert _case_agreement(_case(), graded)["figures_agree"] is True

    def test_the_defect_126_was_written_for_is_a_disagreement(self) -> None:
        """One question, three answers, nothing to execute either against."""
        graded = [
            _lap("correct", None, "There are 6,119 dark vessels."),
            _lap("correct", None, "There are 1,454,449 dark vessels."),
            _lap("correct", None, "There are 10,096 dark vessels."),
        ]
        agreement = _case_agreement(_case(), graded)
        assert agreement["results_agree"] is None
        assert agreement["verdicts_agree"] is True, "the coarse axis cannot see it"
        assert agreement["figures_agree"] is False

    def test_fewer_than_two_answers_carrying_a_figure_is_not_a_disagreement(self) -> None:
        """`None`, never `False` — *we could not tell* and *they disagreed*
        are two findings, and this module's own rule about the first."""
        graded = [
            _lap("correct", None, "I could not determine that."),
            _lap("correct", None, "No figure is available."),
        ]
        assert _case_agreement(_case(), graded)["figures_agree"] is None

    def test_rows_still_decide_where_rows_exist(self) -> None:
        """The strong axis is never overridden. Two laps whose statements
        returned the same rows agree, whatever prose was wrapped round them —
        a lap that adds a coverage date is not a second answer."""
        rows = ((6119,),)
        graded = [
            _lap("correct", rows, "There are 6,119 dark vessels."),
            _lap("correct", rows, "There are 6,119 dark vessels, to 2026-05-12."),
        ]
        agreement = _case_agreement(_case(), graded)
        assert agreement["results_agree"] is True
        block = _agreement_block(2, [agreement])
        assert block["disagreement_rate"] == 0.0


class TestTheCardCountsIt:
    def test_a_figure_disagreement_counts_as_a_disagreement(self) -> None:
        graded = [
            _lap("correct", None, "6,119 vessels."),
            _lap("correct", None, "1,454,449 vessels."),
        ]
        block = _agreement_block(2, [_case_agreement(_case(), graded)])
        assert block["disagreement_rate"] == 1.0

    def test_unmeasurable_means_no_axis_could_tell(self) -> None:
        """The count that shrinks. A case whose rows were not comparable but
        whose figures were is measured, and must stop being reported as a case
        nothing could compare."""
        measurable = _case_agreement(
            _case("c1"),
            [
                _lap("correct", None, "There are 6,119 vessels."),
                _lap("correct", None, "There are 6,119 vessels."),
            ],
        )
        blind = _case_agreement(
            _case("c2"), [_lap("run_error", None, ""), _lap("run_error", None, "")]
        )
        block = _agreement_block(2, [measurable, blind])
        assert block["unmeasurable"] == 1
