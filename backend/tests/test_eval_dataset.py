"""The shipped Chinook golden dataset — the regression tripwire itself.

`workflows/chinook-assistant/evals/chinook.eval.json` carries, for every
answerable question, the rows its gold SQL returns. Those rows are generated
(`scripts/refresh_eval_expectations.py`), never hand-written, and this module
is what makes them load-bearing: if the database, a gold query, or the
expectations move apart, the default test run fails and the diff shows which
rows changed. Without this, a stale expectation would be discovered only when
somebody wondered why the score dropped.

No model is involved. This is a test of the *dataset*, and it runs offline in
milliseconds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.evaluation import load_dataset, refresh_expectations

DATASET = (
    Path(__file__).resolve().parents[2]
    / "workflows"
    / "chinook-assistant"
    / "evals"
    / "chinook.eval.json"
)

#: Above this, a committed expectation stops being reviewable in a diff and
#: the question should be sharpened (ask for a top-N, not for everything).
MAX_COMMITTED_ROWS = 30


@pytest.fixture(scope="module")
def dataset():  # noqa: ANN201 - a pydantic model, named in the assertions below
    return load_dataset(DATASET)


def test_the_dataset_is_big_enough_to_mean_something(dataset) -> None:  # noqa: ANN001
    assert len(dataset.cases) >= 25
    assert len(dataset.refusals()) >= 3, "a harness with no unanswerable questions rewards guessing"


def test_it_spans_the_difficulty_range(dataset) -> None:  # noqa: ANN001
    levels = {case.difficulty for case in dataset.answerable()}
    assert levels == {"easy", "medium", "hard"}


def test_every_gold_query_executes_and_matches_its_committed_rows(dataset) -> None:  # noqa: ANN001
    database = dataset.database_path()
    assert database.is_file(), f"the Chinook database is missing at {database}"
    for case in dataset.answerable():
        outcome = case.run_gold(database)
        assert outcome.ok, f"case {case.id}: gold SQL failed — {outcome.error}"
        assert case.expected is not None, f"case {case.id} has no committed expectation"
        assert case.expected.as_rows() == outcome.rows, (
            f"case {case.id}: committed rows differ from the database. "
            "Run scripts/refresh_eval_expectations.py and review the diff."
        )
        assert list(outcome.columns) == case.expected.columns


def test_a_refresh_is_a_no_op(tmp_path: Path, dataset) -> None:  # noqa: ANN001
    """The whole point of committing the rows: regenerating changes nothing."""
    payload = json.loads(DATASET.read_text())
    payload["database"] = str(dataset.database_path())
    copy = tmp_path / "chinook.eval.json"
    copy.write_text(json.dumps(payload))

    _refreshed, changed = refresh_expectations(copy)

    assert changed == []


def test_expectations_stay_small_enough_to_review(dataset) -> None:  # noqa: ANN001
    for case in dataset.answerable():
        assert case.expected is not None
        assert case.expected.row_count <= MAX_COMMITTED_ROWS, (
            f"case {case.id} commits {case.expected.row_count} rows — ask for a top-N instead"
        )


def test_an_empty_result_set_is_one_of_the_cases(dataset) -> None:  # noqa: ANN001
    """"Nobody matches" is an answer, and a system that invents rows for it is
    doing the exact thing this workflow exists to prevent."""
    assert any(
        case.expected is not None and case.expected.row_count == 0
        for case in dataset.answerable()
    )


def test_the_refusal_cases_say_why_they_are_unanswerable(dataset) -> None:  # noqa: ANN001
    for case in dataset.refusals():
        assert case.notes, f"case {case.id}: an unanswerable question needs its reason written down"
