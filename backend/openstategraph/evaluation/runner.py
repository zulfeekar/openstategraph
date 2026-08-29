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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from openstategraph.evaluation.dataset import EvalCase, EvalDataset, load_dataset
from openstategraph.evaluation.denotation import compare, execute_query, result_eq
from openstategraph.evaluation.recovery import recover_from_run
from openstategraph.evaluation.scoring import ItemVerdict, Scorecard

#: Why a cost block carries tokens and never dollars, stated once.
#:
#: **Tokens are a fact; money is a claim about a vendor's price sheet.** Prices
#: change, differ per account, and live in no file this repository owns, so a
#: dollar figure derived here would be a number that goes stale silently and
#: has nothing to fail against. A caller with a price table multiplies
#: `cost["tokens"]` themselves.
TOKENS_NOT_DOLLARS = (
    "tokens measured from the run itself (langchain-core's usage callback, no "
    "tracer). No dollar figure: prices are per-account and live in no file this "
    "project owns — multiply the token counts by your own price table."
)

#: Why a cost block is empty. Replaces `NO_COST_SIGNAL` (`workflow-gallery` 35),
#: which said `RunResult` carries no token usage — it does now, so the old
#: sentence became false the moment the field landed. This one says the
#: narrower thing that can still be true: nobody reported.
#:
#: An empty block is **unknown, not free**. `total_tokens` is `None` beside it
#: rather than `0`, for the reason `RunResult.usage` gives at the field.
NO_USAGE_REPORTED = (
    "not available — no model in this run reported usage. A provider that sends "
    "no `usage_metadata` (or no model name with it) has made no claim about what "
    "it spent; this is unknown, not zero."
)


@dataclass(frozen=True)
class AskOutcome:
    """What one question produced. The harness's view of a run, and nothing
    more — deliberately not `RunResult`, so a scripted asker is three lines."""

    answer: str
    outputs: dict[str, str]
    attempts: int = 0
    seconds: float = 0.0
    #: model name -> that one run's token usage, straight off `RunResult.usage`.
    #: Empty is *nobody reported*, never *free* — the scorecard preserves the
    #: distinction all the way to its cost row (`workflow-gallery` 35).
    usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: What the run actually executed, straight off `RunResult.statements`
    #: (`one-chinook-honest/30`). Used by the agreement measurement so two runs
    #: are compared on **what ran** rather than on the model's prose about what
    #: ran — which is the comparison `launch-readiness/126` said was blocked.
    #:
    #: Deliberately not fed into `ItemVerdict.sql`: that column and
    #: `sql_recovery_rate` measure whether the system *stated* its query, which
    #: is a real property of grading a product, and reading the record into
    #: them would rename the fact without saying so.
    statements: tuple[dict[str, Any], ...] = ()


Asker = Callable[[EvalCase], AskOutcome]


def evaluate(
    dataset: EvalDataset,
    ask: Asker,
    *,
    limit: int | None = None,
    database: Path | None = None,
    model: str = "",
    on_item: Callable[[ItemVerdict], None] | None = None,
    repeat: int = 1,
) -> Scorecard:
    """Grade every case (or the first `limit` of them, in file order).

    `repeat` asks each case that many times and reports whether the answers
    agreed (`launch-readiness/126`). The **first** repetition is the one that
    scores, so every number on the card keeps the meaning it had and a card
    from `repeat=1` is unchanged; the rest feed `Scorecard.agreement` and
    nothing else. Each repetition is a full model turn, so `repeat=3` over 36
    cases is 108 of them — this is run deliberately, never on a commit.
    """
    db = Path(database) if database else dataset.database_path()
    cases: Iterable[EvalCase] = dataset.cases[:limit] if limit is not None else dataset.cases
    laps = max(1, int(repeat))

    items: list[ItemVerdict] = []
    warnings: list[str] = []
    spent: dict[str, dict[str, Any]] = {}
    agreement: list[dict[str, Any]] = []
    for case in cases:
        graded = [_grade(case, ask, db, warnings, spent) for _ in range(laps)]
        item, _ = graded[0]
        items.append(item)
        if laps > 1:
            agreement.append(_case_agreement(case, graded))
        if on_item is not None:
            on_item(item)

    return Scorecard(
        dataset=dataset.name,
        database=db.name,
        model=model,
        items=tuple(items),
        warnings=tuple(warnings),
        cost=cost_block(spent),
        agreement=_agreement_block(laps, agreement),
    )


def _case_agreement(case: EvalCase, graded: list["GradedRun"]) -> dict[str, Any]:
    """One case's repetitions, compared on both axes.

    **Verdicts** are the coarse signal and are always available. **Results**
    are the strong one — the rows each repetition's statement returned,
    compared with the same `result_eq` execution accuracy uses, so a different
    column alias or a moved `DISTINCT` is not a disagreement. That is the whole
    reason a literal-statement pin was refused: it would be red on a correct
    run.

    `results_agree` is `None`, never `False`, when fewer than two repetitions
    produced rows to compare. *We could not tell* and *they disagreed* are two
    findings, and reporting the first as the second is the failure shape this
    map is named after.
    """
    verdicts = [item.verdict for item, _ in graded]
    comparable = [rows for _, rows in graded if rows is not None]

    distinct: list[tuple[tuple[Any, ...], ...]] = []
    for rows in comparable:
        if not any(
            result_eq(list(seen), list(rows), order_matters=case.ordering_matters())
            for seen in distinct
        ):
            distinct.append(rows)

    return {
        "case_id": case.id,
        "verdicts": verdicts,
        "verdicts_agree": len(set(verdicts)) == 1,
        "results_agree": None if len(comparable) < 2 else len(distinct) == 1,
        "distinct_results": len(distinct),
    }


def _agreement_block(repeat: int, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """The card's agreement block — `{}` for a single pass.

    A case disagrees when its verdicts differ **or** its results do. The second
    half is the silent one this ticket is actually about: three answers, all
    graded the same way, all delivered with identical confidence, reached
    through statements that returned different rows.
    """
    if repeat < 2 or not cases:
        return {}
    disagreed = sum(
        1 for case in cases if not case["verdicts_agree"] or case["results_agree"] is False
    )
    return {
        "repeat": repeat,
        "cases": cases,
        "disagreement_rate": round(disagreed / len(cases), 3),
        # Named rather than folded into the rate: a case nothing could compare
        # is not a case that agreed.
        "unmeasurable": sum(1 for case in cases if case["results_agree"] is None),
    }


def cost_block(spent: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The scorecard's cost row, from what the runs actually reported.

    `usd` stays `None` and says why: see `TOKENS_NOT_DOLLARS`. `total_tokens`
    is `None` — never `0` — when nothing reported, so a reader (or a CI job)
    cannot mistake an unmetered provider for a free one.
    """
    total: int | None = None
    if spent:
        total = 0
        for row in spent.values():
            value = row.get("total_tokens")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            total += int(value)
    return {
        "usd": None,
        "tokens": {name: dict(row) for name, row in sorted(spent.items())},
        "total_tokens": total,
        "note": TOKENS_NOT_DOLLARS if spent else NO_USAGE_REPORTED,
    }


def _accumulate(spent: dict[str, dict[str, Any]], usage: Any) -> None:
    """Add one run's per-model usage into the dataset's running total.

    Added **per field**, so a provider that reports a detail block another does
    not is not flattened to the intersection; a value that is not a number is
    skipped rather than raising, because a malformed usage block must not turn
    a graded dataset into a crash. Nested detail dicts (`input_token_details`)
    are summed one level down, which is where providers put cache reads —
    the field that makes prompt caching measurable at all.
    """
    if not isinstance(usage, dict):
        return
    for name, row in usage.items():
        if not isinstance(row, dict):
            continue
        into = spent.setdefault(str(name), {})
        for field_name, value in row.items():
            if isinstance(value, dict):
                nested = into.setdefault(field_name, {})
                if isinstance(nested, dict):
                    for key, inner in value.items():
                        if isinstance(inner, bool) or not isinstance(inner, (int, float)):
                            continue
                        nested[key] = int(nested.get(key, 0)) + int(inner)
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            into[field_name] = int(into.get(field_name, 0)) + int(value)


#: One graded repetition: the verdict, and the rows the run's own statement
#: returned — `None` when nothing comparable ran.
#:
#: A pair rather than a field on `ItemVerdict`, because the rows are working
#: material for the agreement comparison and not a number on a published
#: scorecard. `Scorecard.to_json()` is diffed between releases; a result set
#: has no business in that diff.
GradedRun = tuple[ItemVerdict, "tuple[tuple[Any, ...], ...] | None"]


def _executed_statement(outcome: AskOutcome) -> str | None:
    """What the run actually sent, from its own record — or `None`.

    `one-chinook-honest/30`. The **last** statement, for `recover_sql`'s own
    reason one layer up: a retry loop runs the query it abandoned before the
    one it kept.
    """
    for row in reversed(list(outcome.statements or ())):
        statement = str((row or {}).get("statement") or "").strip()
        if statement:
            return statement
    return None


def _comparable_rows(
    outcome: AskOutcome, recovered: str | None, database: Path
) -> "tuple[tuple[Any, ...], ...] | None":
    """The rows this repetition's statement returned, for the agreement axis.

    The **record** is preferred over the prose (`30`): an answer can quote a
    query the run never sent, which is `production-ready/95` in person, and two
    runs quoting the same query while executing different ones is precisely the
    disagreement this measurement exists to catch.
    """
    statement = _executed_statement(outcome) or recovered
    if not statement:
        return None
    outcome_rows = execute_query(database, statement)
    return outcome_rows.rows if outcome_rows.ok else None


def _grade(
    case: EvalCase,
    ask: Asker,
    database: Path,
    warnings: list[str],
    spent: dict[str, dict[str, Any]] | None = None,
) -> GradedRun:
    started = time.monotonic()
    try:
        outcome = ask(case)
    except Exception as exc:  # a provider outage is a finding, not a crash
        return (
            ItemVerdict(
                case_id=case.id,
                question=case.question,
                difficulty=case.difficulty,
                expects=case.expects,
                verdict="run_error",
                seconds=round(time.monotonic() - started, 3),
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )

    # Counted before grading, and for every verdict: a wrong answer costs the
    # same tokens as a right one, and a cost row that only counted the
    # successes would understate the bill by exactly the failures.
    if spent is not None:
        _accumulate(spent, outcome.usage)

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

    # Computed for every verdict, including a refusal: a case whose runs all
    # refused still has an agreement to report, and a *correct* refusal that
    # ran a query on one lap and not on another is exactly the instability
    # this measures.
    rows = _comparable_rows(outcome, sql, database)

    if case.expects == "refusal":
        return _grade_refusal(case, outcome, common), rows

    gold = execute_query(database, case.gold_sql or "")
    if not gold.ok:
        warnings.append(f"case {case.id}: the GOLD query does not execute — {gold.error}")
        return ItemVerdict(**common, verdict="dataset_error", error=gold.error), rows
    if case.expected is not None and set(case.expected.as_rows()) != set(gold.rows):
        warnings.append(
            f"case {case.id}: committed expected rows differ from the database "
            "— run scripts/refresh_eval_expectations.py and review the diff"
        )

    if sql is None:
        return (
            ItemVerdict(
                **common,
                verdict="no_sql",
                execution_match=False,
                exact_set_match=False,
                gold_row_count=len(gold.rows),
            ),
            rows,
        )

    predicted = execute_query(database, sql)
    if not predicted.ok:
        return (
            ItemVerdict(
                **common,
                verdict="sql_error",
                execution_match=False,
                exact_set_match=False,
                gold_row_count=len(gold.rows),
                error=predicted.error,
            ),
            rows,
        )

    verdicts = compare(gold, predicted, order_matters=case.ordering_matters())
    return (
        ItemVerdict(
            **common,
            verdict="correct" if verdicts.execution_match else "wrong_result",
            execution_match=verdicts.execution_match,
            exact_set_match=verdicts.exact_set_match,
            gold_row_count=len(gold.rows),
            predicted_row_count=len(predicted.rows),
        ),
        rows,
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
            # Straight off the door — the harness measures nothing itself, for
            # the same reason it invokes nothing itself.
            usage=dict(getattr(result, "usage", {}) or {}),
            # And what the run executed (`one-chinook-honest/30`), so the
            # agreement measurement compares what ran rather than what the
            # answer said ran. `getattr` for `usage`'s reason: a scripted
            # asker and an older `RunResult` both have to work here.
            statements=tuple(getattr(result, "statements", ()) or ()),
        )

    return ask


def evaluate_package(
    package_dir: str | Path,
    *,
    dataset_path: str | Path | None = None,
    model: Any = None,
    limit: int | None = None,
    on_item: Callable[[ItemVerdict], None] | None = None,
    repeat: int = 1,
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
            repeat=repeat,
        )


__all__ = [
    "AskOutcome",
    "Asker",
    "NO_USAGE_REPORTED",
    "TOKENS_NOT_DOLLARS",
    "cost_block",
    "evaluate",
    "evaluate_package",
    "package_asker",
]
