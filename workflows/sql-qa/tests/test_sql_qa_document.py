"""Text-to-SQL over a real database — the wiring, and the fixture that grades it.

Gallery example 17. Two things are settled here, neither of them needing a
model:

- **The wiring.** Three generic SQL Explorer atoms on one agent's `tools` bus,
  every one of them pointed at the package's *own* database file. The path is
  the part that rots: `_resolve_database` jails a configured path inside
  `workflows/` and returns `None` for anything else, and a `None` surfaces at
  run time as a polite refusal rather than a crash — so a typo here would show
  up as a model politely explaining it has no database, four tokens too late.
  This test resolves the path the way the tool does.
- **The fixture.** This is the only one of the twenty whose expectation is a
  machine's. Every gold query must execute against the committed database and
  return exactly the rows committed beside it, or the fixture has drifted from
  the data and the score it produces means nothing.

What is deliberately *not* asserted is the answer's prose. That is what
`openstategraph eval workflows/sql-qa` is for, and the recorded scorecard in
`AGENTS.md` is its result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.package_testing import (
    assert_document_shape,
    load_document,
)
from openstategraph.evaluation.dataset import load_dataset
from openstategraph.prebuilt_sql import _resolve_database

PACKAGE = Path(__file__).resolve().parents[1]

#: The three atoms this example exists to demonstrate, in the order the prompt
#: tells the agent to reach for them.
SQL_ATOMS = ("tool.sql-list-tables", "tool.sql-get-schema", "tool.sql-query")


@pytest.fixture(scope="module")
def doc() -> dict:
    return load_document(PACKAGE)


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(PACKAGE / "evals" / "sql-qa.eval.json")


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(doc)


def test_it_is_the_generic_atoms_not_the_chinook_ones(doc: dict) -> None:
    """The whole reason this package exists beside `chinook-assistant`.

    That package binds workflow-scoped `tool.chinook-*` code it ships itself;
    this one binds the platform's generic SQL Explorer family and configures
    it with a path. Same database, and the difference is the point.
    """
    types = [n["type"] for n in doc["nodes"]]
    assert set(SQL_ATOMS) <= set(types)
    assert not any(t.startswith("tool.chinook-") for t in types)


def test_all_three_atoms_are_on_the_one_agent(doc: dict) -> None:
    plan = WorkflowCompiler().plan(doc)
    assert plan.tool_bindings == {"answer1": ["t-tables", "t-schema", "t-query"]}


def test_every_atom_points_at_a_database_the_jail_will_open(doc: dict) -> None:
    """Configured once per node, and resolved here exactly as the tool does."""
    configured = {
        n["id"]: n["data"]["database"] for n in doc["nodes"] if n["type"] in SQL_ATOMS
    }
    assert len(configured) == 3
    assert len(set(configured.values())) == 1, "three nodes, three spellings of one file"
    for node_id, path in configured.items():
        resolved = _resolve_database(path)
        assert resolved is not None, f"{node_id}: {path!r} is refused by the workflows/ jail"
        assert resolved == (PACKAGE / "data" / "Chinook_Sqlite.sqlite").resolve()


def test_the_package_carries_its_own_database(doc: dict) -> None:
    """Self-contained on purpose: a mount, a wheel or a relocation moves the
    package, and a path into a sibling package's `data/` would not survive it."""
    assert (PACKAGE / "data" / "Chinook_Sqlite.sqlite").is_file()


def test_the_prompt_asks_for_the_query_as_evidence(doc: dict) -> None:
    """Execution accuracy cannot grade an answer that states no query.

    `evaluation/recovery.py` recovers a fenced ```sql block from the answer;
    an answer without one scores `no_sql`, which is neither right nor wrong but
    *unverifiable*. So the instruction to show the query is load-bearing for
    the fixture, not a stylistic choice, and removing it would silently turn a
    100% scorecard into a 0% one.
    """
    prompt = next(n for n in doc["nodes"] if n["id"] == "answer1")["data"]["systemPrompt"]
    assert "```sql" in prompt


class TestTheFixtureMatchesTheDatabase:
    def test_the_dataset_points_at_the_packages_own_file(self, dataset) -> None:
        assert dataset.database_path() == (PACKAGE / "data" / "Chinook_Sqlite.sqlite").resolve()

    def test_every_gold_query_still_returns_what_is_committed(self, dataset) -> None:
        """The regression that matters: data changed, or a gold query did.

        `refresh_expectations` writes these rows by running the query; this
        re-runs them and demands the same answer. A diff here is either a fix
        to review or a fixture nobody refreshed.
        """
        database = dataset.database_path()
        for case in dataset.answerable():
            outcome = case.run_gold(database)
            assert outcome.ok, f"{case.id}: gold SQL does not execute — {outcome.error}"
            assert case.expected is not None, f"{case.id}: no committed expectation"
            assert list(outcome.columns) == case.expected.columns, case.id
            assert set(outcome.rows) == set(case.expected.as_rows()), case.id

    def test_the_catalogues_own_number_is_in_the_fixture(self, dataset) -> None:
        """59 customers — the row the catalogue names, asserted where it lives."""
        case = next(c for c in dataset.cases if c.id == "s01")
        assert case.expected is not None
        assert case.expected.rows == [[59]]

    def test_the_unanswerable_case_carries_no_gold_sql(self, dataset) -> None:
        """A refusal is graded on what did not happen, so there is nothing to
        execute — and `forbidden_patterns` is what catches the other failure,
        a confident date produced from parametric knowledge."""
        refusals = dataset.refusals()
        assert len(refusals) == 1
        assert refusals[0].gold_sql is None
        assert refusals[0].forbidden_patterns
