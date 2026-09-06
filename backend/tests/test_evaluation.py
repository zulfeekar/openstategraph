"""The evaluation harness's own unit tests — the metric, not the model.

The whole point of `openstategraph.evaluation` is that a text-to-SQL answer is
graded by **executing** the SQL and comparing result sets, the way Spider's
test-suite evaluator and BIRD do. That comparison is where all the subtlety
lives — bag semantics, column permutation, `ORDER BY`, `None` in a row, floats
that differ in the last bit — so it is the part with the most tests here.

Nothing in this module runs a model, and nothing in it needs a network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.evaluation import (
    AskOutcome,
    EvalCase,
    EvalDataset,
    Expected,
    ItemVerdict,
    Scorecard,
    evaluate,
    execute_query,
    load_dataset,
    order_matters_for,
    recover_sql,
    result_eq,
    strict_set_eq,
)


# --------------------------------------------------------------------------
# denotation — the Spider test-suite comparison, ported


def test_empty_results_are_equal() -> None:
    assert result_eq([], [], order_matters=False)


def test_row_order_is_ignored_when_the_gold_query_does_not_order() -> None:
    assert result_eq([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], order_matters=False)


def test_row_order_is_enforced_when_the_gold_query_orders() -> None:
    assert not result_eq([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], order_matters=True)


def test_column_order_is_ignored() -> None:
    """Spider searches column permutations: `SELECT name, id` == `SELECT id, name`."""
    assert result_eq([("rock", 3)], [(3, "rock")], order_matters=False)


def test_bag_semantics_not_set_semantics() -> None:
    """Two rows that collapse to one under `set()` must not compare equal."""
    assert not result_eq([(1,), (1,)], [(1,), (2,)], order_matters=False)
    assert not result_eq([(1,), (1,)], [(1,)], order_matters=False)


def test_a_different_number_of_columns_is_never_equal() -> None:
    assert not result_eq([(1, 2)], [(1,)], order_matters=False)


def test_none_in_a_row_does_not_raise() -> None:
    """`sorted(row)` over mixed `None`/`str` raises TypeError.

    Spider's `unorder_row` sorts by `str(x) + str(type(x))` precisely so a NULL
    in a result set is a comparison, not a crash. A harness that throws on the
    first NULL is a harness nobody runs twice.
    """
    assert result_eq([(None, "x")], [(None, "x")], order_matters=False)
    assert not result_eq([(None, "x")], [("x", "x")], order_matters=False)


def test_floats_are_compared_at_a_declared_precision() -> None:
    """Our one deliberate deviation from Spider, and the reason for it.

    `SUM(UnitPrice * Quantity)` and `SUM(UnitPrice) * ...` disagree in the last
    bits of a double. Exact equality would score a correct query wrong for a
    reason that has nothing to do with the model.
    """
    assert result_eq([(1.0 / 3.0,)], [(0.3333333333,)], order_matters=False, float_places=6)
    assert not result_eq([(1.0,)], [(1.01,)], order_matters=False, float_places=6)


def test_strict_set_match_is_stricter_than_execution_accuracy() -> None:
    """The BIRD-style `set(pred) == set(gold)` sibling: no column permutation,
    no float tolerance. Reported beside execution accuracy as the lower bound."""
    assert strict_set_eq([("rock", 3)], [("rock", 3)])
    assert not strict_set_eq([("rock", 3)], [(3, "rock")])


def test_order_matters_is_derived_from_the_gold_query() -> None:
    assert order_matters_for("SELECT Name FROM Genre ORDER BY Name")
    assert order_matters_for("select x from t order   by x")  # whitespace-insensitive
    assert not order_matters_for("SELECT COUNT(*) FROM Genre")


def test_an_explicit_case_override_beats_the_derivation() -> None:
    case = EvalCase(
        id="x",
        question="q",
        difficulty="easy",
        gold_sql="SELECT a FROM t",
        order_matters=True,
    )
    assert case.ordering_matters() is True


# --------------------------------------------------------------------------
# execute_query — read-only, and never raises at the caller


def test_execute_query_returns_columns_and_rows(tiny_db: Path) -> None:
    outcome = execute_query(tiny_db, "SELECT name, id FROM genre ORDER BY id")
    assert outcome.ok
    assert outcome.columns == ("name", "id")
    assert outcome.rows == (("Rock", 1), ("Latin", 2), ("Metal", 3))


def test_a_broken_query_is_an_outcome_not_an_exception(tiny_db: Path) -> None:
    outcome = execute_query(tiny_db, "SELECT nope FROM genre")
    assert not outcome.ok
    assert "nope" in outcome.error


def test_the_evaluation_connection_is_read_only(tiny_db: Path) -> None:
    """Predicted SQL comes from a model. It is executed at `mode=ro`, which
    SQLite enforces itself — not by grepping the string for DROP."""
    outcome = execute_query(tiny_db, "DELETE FROM genre")
    assert not outcome.ok
    assert "readonly" in outcome.error.lower() or "read-only" in outcome.error.lower()


# --------------------------------------------------------------------------
# recovery — getting the SQL back out of an answer written for a human


def test_sql_is_recovered_from_a_fenced_block() -> None:
    answer = "Here is what I ran:\n\n```sql\nSELECT COUNT(*) FROM Track;\n```\n\nThere are 3503."
    assert recover_sql(answer) == "SELECT COUNT(*) FROM Track"


def test_sql_is_recovered_from_a_bare_statement() -> None:
    answer = "I used SELECT COUNT(*) FROM Track; and the answer is 3503."
    assert recover_sql(answer) == "SELECT COUNT(*) FROM Track"


def test_a_with_clause_is_recovered() -> None:
    answer = "```\nWITH t AS (SELECT 1 AS a) SELECT a FROM t;\n```"
    assert recover_sql(answer) == "WITH t AS (SELECT 1 AS a) SELECT a FROM t"


def test_the_last_query_wins() -> None:
    """A retry loop narrates the query it abandoned before the one it kept."""
    answer = "First I tried ```sql\nSELECT 1;\n``` then ```sql\nSELECT 2;\n```"
    assert recover_sql(answer) == "SELECT 2"


def test_no_sql_in_a_refusal() -> None:
    assert recover_sql("I answer questions about the Chinook music store.") is None
    assert recover_sql("") is None


# --------------------------------------------------------------------------
# dataset


def _dataset_payload() -> dict[str, object]:
    return {
        "name": "tiny",
        "database": "tiny.sqlite",
        "cases": [
            {
                "id": "e01",
                "question": "How many genres are there?",
                "difficulty": "easy",
                "gold_sql": "SELECT COUNT(*) FROM genre",
            },
            {
                "id": "u01",
                "question": "What is the weather?",
                "difficulty": "easy",
                "expects": "refusal",
            },
        ],
    }


def test_a_dataset_round_trips_and_resolves_its_database(tmp_path: Path) -> None:
    (tmp_path / "d.eval.json").write_text(json.dumps(_dataset_payload()))
    dataset = load_dataset(tmp_path / "d.eval.json")
    assert [case.id for case in dataset.cases] == ["e01", "u01"]
    assert dataset.database_path() == (tmp_path / "tiny.sqlite")


def test_an_answerable_case_without_gold_sql_is_refused(tmp_path: Path) -> None:
    payload = _dataset_payload()
    payload["cases"] = [{"id": "x", "question": "q", "difficulty": "easy"}]
    (tmp_path / "d.eval.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="gold_sql"):
        load_dataset(tmp_path / "d.eval.json")


def test_a_refusal_case_with_gold_sql_is_refused(tmp_path: Path) -> None:
    payload = _dataset_payload()
    payload["cases"] = [
        {"id": "x", "question": "q", "difficulty": "easy", "expects": "refusal", "gold_sql": "SELECT 1"}
    ]
    (tmp_path / "d.eval.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="gold_sql"):
        load_dataset(tmp_path / "d.eval.json")


def test_duplicate_ids_are_refused(tmp_path: Path) -> None:
    payload = _dataset_payload()
    payload["cases"] = [
        {"id": "x", "question": "q", "difficulty": "easy", "gold_sql": "SELECT 1"},
        {"id": "x", "question": "r", "difficulty": "easy", "gold_sql": "SELECT 2"},
    ]
    (tmp_path / "d.eval.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset(tmp_path / "d.eval.json")


# --------------------------------------------------------------------------
# the runner and the scorecard, driven by a scripted asker


def _tiny_dataset(tmp_path: Path, db: Path) -> EvalDataset:
    payload = {
        "name": "tiny",
        "database": db.name,
        "cases": [
            {
                "id": "e01",
                "question": "How many genres are there?",
                "difficulty": "easy",
                "gold_sql": "SELECT COUNT(*) AS n FROM genre",
            },
            {
                "id": "m01",
                "question": "Which genre earns the most?",
                "difficulty": "medium",
                "gold_sql": "SELECT name, revenue FROM genre ORDER BY revenue DESC LIMIT 1",
            },
            {
                "id": "u01",
                "question": "What is the weather in Berlin?",
                "difficulty": "easy",
                "expects": "refusal",
                "forbidden_patterns": ["degrees"],
            },
        ],
    }
    path = db.parent / "tiny.eval.json"
    path.write_text(json.dumps(payload))
    return load_dataset(path)


def _scripted(answers: dict[str, str]) -> object:
    def ask(case: EvalCase) -> AskOutcome:
        return AskOutcome(answer=answers[case.id], outputs={}, attempts=0, seconds=0.5)

    return ask


def test_a_perfect_run_scores_one(tmp_path: Path, tiny_db: Path) -> None:
    dataset = _tiny_dataset(tmp_path, tiny_db)
    card = evaluate(
        dataset,
        _scripted(
            {
                # Different SQL from the gold, same denotation — the whole
                # reason the metric is execution accuracy and not string match.
                "e01": "```sql\nSELECT COUNT(id) FROM genre\n```\nThree.",
                "m01": "```sql\nSELECT revenue, name FROM genre WHERE name='Rock'\n```\nRock.",
                "u01": "I only answer questions about this music store.",
            }
        ),
    )
    assert card.execution_accuracy == 1.0
    assert card.refusal_accuracy == 1.0
    assert card.overall_accuracy == 1.0


def test_a_wrong_result_set_scores_zero(tmp_path: Path, tiny_db: Path) -> None:
    dataset = _tiny_dataset(tmp_path, tiny_db)
    card = evaluate(
        dataset,
        _scripted(
            {
                "e01": "```sql\nSELECT COUNT(*) FROM genre WHERE id < 3\n```\nTwo.",
                "m01": "```sql\nSELECT name, revenue FROM genre ORDER BY revenue LIMIT 1\n```",
                "u01": "It is 21 degrees and sunny in Berlin.",
            }
        ),
    )
    assert card.execution_accuracy == 0.0
    assert card.refusal_accuracy == 0.0
    assert card.overall_accuracy == 0.0
    verdicts = {item.case_id: item.verdict for item in card.items}
    assert verdicts["e01"] == "wrong_result"
    assert verdicts["m01"] == "wrong_result"
    assert verdicts["u01"] == "invented_answer"


def test_an_answer_with_no_sql_at_all_is_a_named_failure(tmp_path: Path, tiny_db: Path) -> None:
    """A confident answer from parametric knowledge — the failure this whole
    workflow exists to prevent — must be visible as its own verdict, not
    lumped in with a wrong join."""
    dataset = _tiny_dataset(tmp_path, tiny_db)
    card = evaluate(dataset, _scripted({"e01": "There are three genres.", "m01": "Rock.", "u01": "no"}))
    verdicts = {item.case_id: item.verdict for item in card.items}
    assert verdicts["e01"] == "no_sql"
    assert card.sql_recovery_rate == 0.0


def test_broken_sql_is_its_own_verdict(tmp_path: Path, tiny_db: Path) -> None:
    dataset = _tiny_dataset(tmp_path, tiny_db)
    card = evaluate(dataset, _scripted({"e01": "```sql\nSELECT nope FROM genre\n```", "m01": "x", "u01": "no"}))
    item = next(i for i in card.items if i.case_id == "e01")
    assert item.verdict == "sql_error"
    assert "nope" in item.error


def test_a_refusal_case_that_runs_sql_should_have_refused(tmp_path: Path, tiny_db: Path) -> None:
    dataset = _tiny_dataset(tmp_path, tiny_db)
    card = evaluate(
        dataset,
        _scripted({"e01": "x", "m01": "x", "u01": "```sql\nSELECT * FROM genre\n```"}),
    )
    item = next(i for i in card.items if i.case_id == "u01")
    assert item.verdict == "should_have_refused"


def test_limit_takes_the_first_n_cases_in_file_order(tmp_path: Path, tiny_db: Path) -> None:
    dataset = _tiny_dataset(tmp_path, tiny_db)
    card = evaluate(dataset, _scripted({"e01": "x"}), limit=1)
    assert [item.case_id for item in card.items] == ["e01"]


def test_the_scorecard_json_is_deterministic(tmp_path: Path, tiny_db: Path) -> None:
    """Two runs of the same answers must produce byte-identical JSON apart from
    the timing block, or a scorecard cannot be diffed in a pull request."""
    dataset = _tiny_dataset(tmp_path, tiny_db)
    answers = _scripted({"e01": "```sql\nSELECT COUNT(*) FROM genre\n```", "m01": "x", "u01": "no"})
    first = json.dumps(evaluate(dataset, answers).to_json(), indent=2, sort_keys=True)
    second = json.dumps(evaluate(dataset, answers).to_json(), indent=2, sort_keys=True)
    assert first == second


def test_the_scorecard_renders_a_table_with_every_headline_number(
    tmp_path: Path, tiny_db: Path
) -> None:
    dataset = _tiny_dataset(tmp_path, tiny_db)
    card = evaluate(dataset, _scripted({"e01": "x", "m01": "x", "u01": "no"}))
    table = card.render()
    for heading in (
        "execution accuracy",
        "exact set match",
        "refusal accuracy",
        "sql recovered",
        "latency p50",
        "latency p95",
        "attempts",
    ):
        assert heading in table


def test_the_scorecard_says_what_it_does_not_measure(tmp_path: Path, tiny_db: Path) -> None:
    """Honesty is a feature of the artifact, not of the README. Anyone reading a
    scorecard must see its blind spots on the same page as its numbers."""
    dataset = _tiny_dataset(tmp_path, tiny_db)
    card = evaluate(dataset, _scripted({"e01": "x", "m01": "x", "u01": "no"}))
    assert card.not_measured
    assert "not measured" in card.render().lower()
    assert card.to_json()["not_measured"] == list(card.not_measured)


def test_a_threshold_gate_is_a_boolean_on_the_scorecard(tmp_path: Path, tiny_db: Path) -> None:
    dataset = _tiny_dataset(tmp_path, tiny_db)
    card = evaluate(dataset, _scripted({"e01": "x", "m01": "x", "u01": "no"}))
    # Rounded to four places on purpose: a rate is a committed number in a
    # diffable artifact, not a float that trails 17 digits of noise.
    assert card.overall_accuracy == 0.3333
    assert card.meets(0.3)
    assert not card.meets(0.5)


def test_latency_percentiles_use_nearest_rank(tmp_path: Path, tiny_db: Path) -> None:
    dataset = _tiny_dataset(tmp_path, tiny_db)
    seconds = iter([1.0, 3.0, 2.0])

    def ask(case: EvalCase) -> AskOutcome:
        return AskOutcome(answer="x", outputs={}, attempts=1, seconds=next(seconds))

    card = evaluate(dataset, ask)
    assert card.latency_p50 == 2.0
    assert card.latency_p95 == 3.0
    assert card.attempts_total == 3


def test_a_run_that_raised_is_recorded_not_swallowed(tmp_path: Path, tiny_db: Path) -> None:
    dataset = _tiny_dataset(tmp_path, tiny_db)

    def ask(case: EvalCase) -> AskOutcome:
        if case.id == "e01":
            raise RuntimeError("provider exploded")
        return AskOutcome(answer="x", outputs={}, attempts=0, seconds=0.1)

    card = evaluate(dataset, ask)
    item = next(i for i in card.items if i.case_id == "e01")
    assert item.verdict == "run_error"
    assert "provider exploded" in item.error


def test_committed_expectations_that_drift_from_the_database_warn(
    tmp_path: Path, tiny_db: Path
) -> None:
    """The committed `expected` block is the regression tripwire. If the
    database moves under it, the scorecard says so rather than quietly grading
    against a stale truth."""
    dataset = _tiny_dataset(tmp_path, tiny_db)
    stale = dataset.cases[0].model_copy(
        update={"expected": Expected(columns=["n"], rows=[[999]], row_count=1)}
    )
    dataset = dataset.model_copy(update={"cases": [stale]})
    card = evaluate(dataset, _scripted({"e01": "```sql\nSELECT COUNT(*) FROM genre\n```"}))
    assert any("e01" in warning for warning in card.warnings)


def test_sql_is_recovered_from_a_node_output_when_the_answer_has_none(
    tmp_path: Path, tiny_db: Path
) -> None:
    """`RunResult.outputs` carries each node's own text. If the final answer is
    prose but the agent node stated its query, the query is still evidence."""
    dataset = _tiny_dataset(tmp_path, tiny_db)

    def ask(case: EvalCase) -> AskOutcome:
        return AskOutcome(
            answer="There are three genres.",
            outputs={"agent-sql": "```sql\nSELECT COUNT(*) FROM genre\n```"},
            attempts=0,
            seconds=0.1,
        )

    card = evaluate(dataset, ask, limit=1)
    item = card.items[0]
    assert item.verdict == "correct"
    assert item.sql_source == "outputs"


def test_item_verdicts_and_the_scorecard_are_frozen_value_objects() -> None:
    assert ItemVerdict.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert Scorecard.__dataclass_params__.frozen  # type: ignore[attr-defined]
