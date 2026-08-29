"""Text-to-SQL over a real database — the wiring, and the fixture that grades it.

Gallery example 17. Two things are settled here, neither of them needing a
model:

- **The wiring.** Three generic SQL Explorer atoms on one agent's `tools` bus,
  every one of them pointed at the package's *own* database file. The path is
  the part that rots: `_resolve_database` jails a configured path inside the
  **workflows root** and returns `None` for anything else, and a `None`
  surfaces at run time as a polite refusal rather than a crash — so a typo here
  would show up as a model politely explaining it has no database, four tokens
  too late. This test resolves the path the way the tool does.
- **The fixture.** This is the only one of the twenty whose expectation is a
  machine's. Every gold query must execute against the committed database and
  return exactly the rows committed beside it, or the fixture has drifted from
  the data and the score it produces means nothing.

What is deliberately *not* asserted is the answer's prose. That is what
`openstategraph eval workflows/sql-qa` is for, and the recorded scorecard in
`AGENTS.md` is its result.

**Where this package lives is part of the wiring test** (gallery ticket 07).
The gallery ships as package data, which is *outside* the workflows root on
purpose — so where it lies, the jail refuses this path, and it must: an example
inside `site-packages` is not a workflow anybody is running. It becomes
runnable by being copied (`openstategraph examples copy sql-qa`), and the
property worth pinning is the one that survives the copy: the configured path
is relative to the root that holds the package, whichever root that is.
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


def test_every_atom_points_at_a_database_the_jail_will_open(
    doc: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured once per node, and resolved here exactly as the tool does.

    The root is this package's own parent — which is what it will be once the
    example has been copied into somebody's `workflows/`. Pointing it here
    rather than letting it default is the whole point: it proves the path is
    relative to the package's home and carries no assumption about which home
    that is.
    """
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(PACKAGE.parent))
    configured = {
        n["id"]: n["data"]["database"] for n in doc["nodes"] if n["type"] in SQL_ATOMS
    }
    assert len(configured) == 3
    assert len(set(configured.values())) == 1, "three nodes, three spellings of one file"
    for node_id, path in configured.items():
        resolved = _resolve_database(path)
        assert resolved is not None, f"{node_id}: {path!r} is refused by the jail"
        assert resolved == (PACKAGE / "data" / "Chinook_Sqlite.sqlite").resolve()


def test_where_it_ships_the_jail_refuses_it_and_that_is_correct() -> None:
    """An example is inert until copied — `openstategraph.examples` states the
    bargain, and this is what it costs. Nothing under `site-packages` is a
    workflow the adopter is running, so nothing there may open a database."""
    from openstategraph import examples

    assert PACKAGE.parent == examples.DATA
    assert _resolve_database("sql-qa/data/Chinook_Sqlite.sqlite") is None


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


class TestATrueZeroIsAnAnswer:
    """`launch-readiness/172`: the shipped example answered a genuine zero
    with the digit `0` and nothing else.

    The question was *"How many customers are from Antarctica?"*, whose honest
    answer is none, and the run got it right — the timeline shows it listing
    tables, reading the `Customer` schema and running a filtered count. What
    reached `RunResult.answer`, and therefore the CLI, a package's `tests/`
    and anything embedding the library, was `0`.

    Two sentences of the prompt produced it together. *"Give the number, not a
    description of the number"* is a rule against hedging that reads, on the
    zero path, as a rule against the noun; and *"If the query returned no rows,
    say so"* never fires for a count, because `SELECT COUNT(*)` returns one row
    holding zero. So the one clause that could have caught this was written for
    a case that cannot happen.

    Phrasing is not what the scorecard grades — `scoring.NOT_MEASURED` says so
    in as many words, and widening the eval to grade prose would contradict a
    recorded boundary. This is a document assertion, which is what a package's
    `tests/` are for. The dataset's job is the other half: a suite with no zero
    case cannot catch a zero defect on the path that *is* graded.
    """

    def _prompt(self, doc: dict) -> str:
        return next(n for n in doc["nodes"] if n["id"] == "answer1")["data"]["systemPrompt"]

    def test_the_prompt_names_zero_as_a_case_of_its_own(self, doc: dict) -> None:
        assert "zero" in self._prompt(doc).lower()

    def test_the_prompt_forbids_the_bare_number(self, doc: dict) -> None:
        """The contract 165 asks for, stated where the node can obey it: the
        sentence names what was counted, never the figure alone."""
        prompt = self._prompt(doc)
        assert "never the number alone" in prompt

    def test_the_no_rows_clause_covers_a_count_of_none(self, doc: dict) -> None:
        """A count of zero is not "no rows", and the prompt must not conflate
        them — that conflation is the defect."""
        prompt = self._prompt(doc)
        assert "COUNT(*)" in prompt

    def test_the_fixture_carries_a_true_zero_case(self, dataset) -> None:
        """An answerable question whose answer is none — a third category
        beside *answerable* and *refusal*, and the one the five shipped cases
        did not have."""
        zeros = [
            case
            for case in dataset.answerable()
            if case.expected is not None and case.expected.rows == [[0]]
        ]
        assert zeros, "no case in the dataset has a true zero for its answer"

    def test_the_zero_case_is_not_a_refusal(self, dataset) -> None:
        """The distinction the dataset exists to hold: Antarctica is a country
        `Customer` can record and does not, so the database *can* answer and
        the answer is none. `s05` is the other thing — a column that does not
        exist, where querying at all is the failure."""
        zeros = [
            case
            for case in dataset.answerable()
            if case.expected is not None and case.expected.rows == [[0]]
        ]
        for case in zeros:
            assert case.expects == "answer"
            assert (case.gold_sql or "").strip()
