"""Running the dataset against a workflow, one question at a time.

**One execution path.** The asker built here calls `load_workflow(...).ask()` —
the same seam the CLI, the HTTP API and an adopter's own script use. A harness
with its own way of invoking a graph measures a graph nobody runs.

**The seam that makes the harness testable.** `evaluate()` takes an `Asker`, a
plain callable from a case to an `AskOutcome`. `package_asker()` is the one
that spends money; a test passes a scripted function instead and exercises the
whole scorecard offline, in milliseconds. That is why the live eval is not in
the default CI job and the harness still is.

**Grading, in the order the checks are applied**, because the order is the
semantics:

1. The workflow raised → `run_error`. Never swallowed; a provider outage must
   not read as a wrong answer.
2. The case expects a refusal → correct exactly when no query was recovered
   *and* no forbidden pattern appears in the answer.
3. Otherwise the gold SQL is executed (the database, not the committed file,
   is the truth) and compared with `denotation.compare`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from openstategraph.evaluation.dataset import EvalCase, EvalDataset, load_dataset
from openstategraph.evaluation.denotation import compare, execute_query
from openstategraph.evaluation.recovery import recover_from_run
from openstategraph.evaluation.scoring import ItemVerdict, Scorecard

#: Why the scorecard's cost block is usually empty, stated once.
NO_COST_SIGNAL = (
    "not available — `RunResult` carries no token usage, so no dollar figure can "
    "be derived without a tracer. Attach LangSmith (LANGSMITH_TRACING=true) for "
    "per-run token and cost accounting."
)


@dataclass(frozen=True)
class AskOutcome:
    """What one question produced. The harness's view of a run, and nothing
    more — deliberately not `RunResult`, so a scripted asker is three lines."""

    answer: str
    outputs: dict[str, str]
    attempts: int = 0
    seconds: float = 0.0


Asker = Callable[[EvalCase], AskOutcome]


def evaluate(
    dataset: EvalDataset,
    ask: Asker,
    *,
    limit: int | None = None,
    database: Path | None = None,
    model: str = "",
    on_item: Callable[[ItemVerdict], None] | None = None,
) -> Scorecard:
    """Grade every case (or the first `limit` of them, in file order)."""
    db = Path(database) if database else dataset.database_path()
    cases: Iterable[EvalCase] = dataset.cases[:limit] if limit is not None else dataset.cases

    items: list[ItemVerdict] = []
    warnings: list[str] = []
    for case in cases:
        item = _grade(case, ask, db, warnings)
        items.append(item)
        if on_item is not None:
            on_item(item)

    return Scorecard(
        dataset=dataset.name,
        database=db.name,
        model=model,
        items=tuple(items),
        warnings=tuple(warnings),
        cost={"usd": None, "note": NO_COST_SIGNAL},
    )


def _grade(case: EvalCase, ask: Asker, database: Path, warnings: list[str]) -> ItemVerdict:
    started = time.monotonic()
    try:
        outcome = ask(case)
    except Exception as exc:  # a provider outage is a finding, not a crash
        return ItemVerdict(
            case_id=case.id,
            question=case.question,
            difficulty=case.difficulty,
            expects=case.expects,
            verdict="run_error",
            seconds=round(time.monotonic() - started, 3),
            error=f"{type(exc).__name__}: {exc}",
        )

    sql, source = recover_from_run(outcome.answer, outcome.outputs)
    common: dict[str, Any] = {
        "case_id": case.id,
        "question": case.question,
        "difficulty": case.difficulty,
        "expects": case.expects,
        "seconds": outcome.seconds,
        "attempts": outcome.attempts,
        "sql": sql,
        "sql_source": source,
    }

    if case.expects == "refusal":
        return _grade_refusal(case, outcome, common)

    gold = execute_query(database, case.gold_sql or "")
    if not gold.ok:
        warnings.append(f"case {case.id}: the GOLD query does not execute — {gold.error}")
        return ItemVerdict(**common, verdict="dataset_error", error=gold.error)
    if case.expected is not None and set(case.expected.as_rows()) != set(gold.rows):
        warnings.append(
            f"case {case.id}: committed expected rows differ from the database "
            "— run scripts/refresh_eval_expectations.py and review the diff"
        )

    if sql is None:
        return ItemVerdict(
            **common,
            verdict="no_sql",
            execution_match=False,
            exact_set_match=False,
            gold_row_count=len(gold.rows),
        )

    predicted = execute_query(database, sql)
    if not predicted.ok:
        return ItemVerdict(
            **common,
            verdict="sql_error",
            execution_match=False,
            exact_set_match=False,
            gold_row_count=len(gold.rows),
            error=predicted.error,
        )

    verdicts = compare(gold, predicted, order_matters=case.ordering_matters())
    return ItemVerdict(
        **common,
        verdict="correct" if verdicts.execution_match else "wrong_result",
        execution_match=verdicts.execution_match,
        exact_set_match=verdicts.exact_set_match,
        gold_row_count=len(gold.rows),
        predicted_row_count=len(predicted.rows),
    )


def _grade_refusal(case: EvalCase, outcome: AskOutcome, common: dict[str, Any]) -> ItemVerdict:
    """An unanswerable question is graded on what the system *did not* do.

    Querying at all is the failure: there is nothing in this database to query.
    `forbidden_patterns` catches the other shape — a confident sentence with a
    figure in it, produced from parametric knowledge with no query behind it,
    which is the exact failure this workflow exists to prevent.
    """
    import re

    if common["sql"]:
        return ItemVerdict(**common, verdict="should_have_refused")
    for pattern in case.forbidden_patterns:
        if re.search(pattern, outcome.answer, re.IGNORECASE):
            return ItemVerdict(
                **common,
                verdict="invented_answer",
                error=f"answer matches forbidden pattern {pattern!r}",
            )
    return ItemVerdict(**common, verdict="refused_correctly")


# --------------------------------------------------------------------------
# the live asker


def package_asker(workflow: Any) -> Asker:
    """An `Asker` over a loaded `CompiledWorkflow`.

    Each case runs on its own thread id, so one question never continues
    another's conversation — the dataset is a set of independent questions, and
    letting case 12 see case 11's history would make the score depend on file
    order.
    """

    def ask(case: EvalCase) -> AskOutcome:
        started = time.monotonic()
        result = workflow.ask(case.question, thread_id=f"eval-{case.id}")
        return AskOutcome(
            answer=str(result),
            outputs=dict(result.outputs),
            attempts=int(result.attempts),
            seconds=round(time.monotonic() - started, 3),
        )

    return ask


def evaluate_package(
    package_dir: str | Path,
    *,
    dataset_path: str | Path | None = None,
    model: Any = None,
    limit: int | None = None,
    on_item: Callable[[ItemVerdict], None] | None = None,
) -> Scorecard:
    """Load a workflow package and grade it against its dataset.

    This is the seam `openstategraph eval` wraps and the one a CI job calls;
    it adds no execution path of its own.
    """
    from openstategraph import load_workflow
    from openstategraph.evaluation.dataset import default_dataset_path

    package = Path(package_dir).expanduser().resolve()
    dataset = load_dataset(dataset_path or default_dataset_path(package))
    with load_workflow(package, model=model) as workflow:
        return evaluate(
            dataset,
            package_asker(workflow),
            limit=limit,
            model=str(model) if model else "(package default)",
            on_item=on_item,
        )


__all__ = [
    "AskOutcome",
    "Asker",
    "NO_COST_SIGNAL",
    "evaluate",
    "evaluate_package",
    "package_asker",
]
