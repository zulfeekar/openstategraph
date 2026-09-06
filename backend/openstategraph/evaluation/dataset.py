"""The golden dataset — questions, gold SQL, and the rows the gold SQL returns.

One JSON file, validated by Pydantic, living beside the workflow it grades
(`<package>/evals/<name>.eval.json`). Three properties of the format are
deliberate:

**The expected rows are committed.** They are produced by *running* the gold
SQL, never written by hand, and stored in the file. That is what makes a
regression visible in a diff: if somebody edits the database or the gold query,
the change shows up as changed rows in a pull request rather than as a number
that quietly moved on a dashboard. `scripts/refresh_eval_expectations.py`
regenerates them; the runner re-executes the gold query anyway and *warns* when
the two disagree, so a stale file cannot silently become the truth.

**Unanswerable questions are cases too.** A case with `expects: "refusal"` has
no gold SQL — Chinook has no customer birth dates, no streaming plays and no
cost of goods, so a system that answers those questions is inventing. Refusal
correctness is measured on the same run as execution accuracy, because a
harness that only scores answerable questions rewards a model for guessing.

**Ordering is a property of the question.** `order_matters` follows Spider's
rule by default (the gold query's own `ORDER BY` decides) and can be overridden
per case for the queries where a sort is incidental — a `LIMIT 1` "which genre
earns most" orders in order to pick, not in order to present.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from openstategraph.evaluation.denotation import QueryOutcome, execute_query, order_matters_for

Difficulty = Literal["easy", "medium", "hard"]
Expectation = Literal["answer", "refusal"]


class Expected(BaseModel):
    """What the gold SQL returned when it was last run against the database."""

    model_config = {"extra": "forbid"}

    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0

    def as_rows(self) -> tuple[tuple[Any, ...], ...]:
        return tuple(tuple(row) for row in self.rows)


class EvalCase(BaseModel):
    """One question, and how it is graded."""

    model_config = {"extra": "forbid"}

    id: str
    question: str
    difficulty: Difficulty = "medium"
    #: `"answer"` — grade by execution accuracy against `gold_sql`.
    #: `"refusal"` — the honest response is to decline; grade by not querying.
    expects: Expectation = "answer"
    gold_sql: str | None = None
    #: `None` means Spider's derivation from `gold_sql`.
    order_matters: bool | None = None
    #: Regexes that must NOT appear in a refusal — the shape of an invented
    #: answer for this specific question (a figure, a unit, a fabricated fact).
    forbidden_patterns: list[str] = Field(default_factory=list)
    #: Why this case exists, or what makes it unanswerable. Read by humans.
    notes: str = ""
    expected: Expected | None = None

    @model_validator(mode="after")
    def _gold_sql_matches_the_expectation(self) -> "EvalCase":
        if self.expects == "answer" and not (self.gold_sql or "").strip():
            raise ValueError(f"case {self.id!r} expects an answer but has no gold_sql")
        if self.expects == "refusal" and (self.gold_sql or "").strip():
            raise ValueError(f"case {self.id!r} expects a refusal but carries gold_sql")
        return self

    def ordering_matters(self) -> bool:
        if self.order_matters is not None:
            return self.order_matters
        return order_matters_for(self.gold_sql or "")

    def run_gold(self, database: Path) -> QueryOutcome:
        """Execute the gold SQL. The source of truth is always the database."""
        return execute_query(database, self.gold_sql or "")


class EvalDataset(BaseModel):
    """A named set of cases against one database."""

    model_config = {"extra": "forbid"}

    name: str
    #: Relative to this file, so the dataset travels with the package.
    database: str
    description: str = ""
    cases: list[EvalCase] = Field(default_factory=list)
    #: Where it was loaded from. Set by `load_dataset`, not by the file.
    source: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "EvalDataset":
        seen: set[str] = set()
        for case in self.cases:
            if case.id in seen:
                raise ValueError(f"duplicate case id {case.id!r}")
            seen.add(case.id)
        return self

    def database_path(self) -> Path:
        base = self.source.parent if self.source else Path.cwd()
        return (base / self.database).resolve()

    def answerable(self) -> list[EvalCase]:
        return [case for case in self.cases if case.expects == "answer"]

    def refusals(self) -> list[EvalCase]:
        return [case for case in self.cases if case.expects == "refusal"]


def load_dataset(path: str | Path) -> EvalDataset:
    """Read and validate one dataset file.

    A malformed dataset raises — unlike a failed *prediction*, which is data. A
    harness that grades against a file it could not fully understand is worse
    than one that refuses to start.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"no eval dataset at {source}")
    try:
        payload = json.loads(source.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} is not valid JSON: {exc}") from exc
    dataset = EvalDataset.model_validate(payload)
    return dataset.model_copy(update={"source": source})


def default_dataset_path(package_dir: str | Path) -> Path:
    """The convention: exactly one `*.eval.json` under `<package>/evals/`.

    Discovery by convention, the same way `tools/` and `knowledge/` work, so
    `openstategraph eval ./workflows/chinook-assistant` needs no flags. Two
    datasets is not an error the harness may resolve by guessing — it names
    both and asks for `--dataset`.
    """
    directory = Path(package_dir).expanduser().resolve() / "evals"
    found = sorted(directory.glob("*.eval.json"))
    if not found:
        raise FileNotFoundError(
            f"no *.eval.json in {directory} — pass --dataset, or add one (docs/evaluation.md)"
        )
    if len(found) > 1:
        names = ", ".join(path.name for path in found)
        raise ValueError(f"{directory} holds several datasets ({names}) — pass --dataset")
    return found[0]


def expected_for(case: EvalCase, database: Path) -> Expected:
    """Run the gold SQL and shape the result for committing."""
    outcome = case.run_gold(database)
    if not outcome.ok:
        raise ValueError(f"gold SQL for case {case.id!r} does not execute: {outcome.error}")
    return Expected(
        columns=list(outcome.columns),
        rows=[list(row) for row in outcome.rows],
        row_count=len(outcome.rows),
    )


def refresh_expectations(path: str | Path) -> tuple[EvalDataset, list[str]]:
    """Re-derive every `expected` block from the database and rewrite the file.

    Returns the refreshed dataset and the ids whose expectations changed — the
    list a reviewer wants next to the diff.
    """
    dataset = load_dataset(path)
    database = dataset.database_path()
    changed: list[str] = []
    cases: list[EvalCase] = []
    for case in dataset.cases:
        if case.expects != "answer":
            cases.append(case)
            continue
        fresh = expected_for(case, database)
        if case.expected is None or case.expected.model_dump() != fresh.model_dump():
            changed.append(case.id)
        cases.append(case.model_copy(update={"expected": fresh}))
    refreshed = dataset.model_copy(update={"cases": cases})
    target = Path(path).expanduser().resolve()
    target.write_text(json.dumps(dataset_payload(refreshed), indent=2, ensure_ascii=False) + "\n")
    return refreshed, changed


def dataset_payload(dataset: EvalDataset) -> dict[str, Any]:
    """The file's on-disk shape: declaration order, and no empty fields.

    A golden file is read in a diff, so an optional field that is empty is
    noise — `"notes": ""` on thirty cases hides the one line that changed.
    """
    payload = dataset.model_dump(exclude_none=True)
    payload["cases"] = [
        {key: value for key, value in case.items() if value != [] and value != ""}
        for case in payload["cases"]
    ]
    return payload


__all__ = [
    "Difficulty",
    "EvalCase",
    "EvalDataset",
    "Expectation",
    "Expected",
    "dataset_payload",
    "default_dataset_path",
    "expected_for",
    "load_dataset",
    "refresh_expectations",
]
