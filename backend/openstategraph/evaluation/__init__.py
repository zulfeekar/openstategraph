"""Measuring a text-to-SQL workflow the way the field measures one.

**Tier 2, provisional** as a Python module (`docs/stability.md`); the
`openstategraph eval` command it backs follows the CLI's own contract.

The metric is **execution accuracy**: run the generated SQL and the gold SQL
against the same database and compare the result sets. It is what Spider's
official test-suite evaluator and BIRD both report, and it exists because
comparing SQL *strings* scores a correct query wrong whenever the model spells
a join differently. See `denotation` for the port and its two documented
deviations, `dataset` for the golden file format, `scoring` for what the
scorecard does and does not claim, and `docs/evaluation.md` for how to run it.

Four small modules, one job each — no `Abstract*`/`Base*` ladder here, and that
is deliberate rather than an omission: there is exactly one comparison, one
dataset format and one runner, so a hierarchy would be inheritance with nothing
to inherit. If a second metric ever earns its place (BIRD's Valid Efficiency
Score is the obvious candidate), it composes beside `compare`.
"""

from __future__ import annotations

from openstategraph.evaluation.dataset import (
    Difficulty,
    EvalCase,
    EvalDataset,
    Expectation,
    Expected,
    dataset_payload,
    default_dataset_path,
    expected_for,
    load_dataset,
    refresh_expectations,
)
from openstategraph.evaluation.denotation import (
    Comparison,
    QueryOutcome,
    compare,
    execute_query,
    order_matters_for,
    result_eq,
    strict_set_eq,
)
from openstategraph.evaluation.recovery import recover_from_run, recover_sql
from openstategraph.evaluation.runner import (
    Asker,
    AskOutcome,
    evaluate,
    evaluate_package,
    package_asker,
)
from openstategraph.evaluation.scoring import NOT_MEASURED, VERDICTS, ItemVerdict, Scorecard

__all__ = [
    "AskOutcome",
    "Asker",
    "Comparison",
    "Difficulty",
    "EvalCase",
    "EvalDataset",
    "Expectation",
    "Expected",
    "ItemVerdict",
    "NOT_MEASURED",
    "QueryOutcome",
    "Scorecard",
    "VERDICTS",
    "compare",
    "dataset_payload",
    "default_dataset_path",
    "evaluate",
    "evaluate_package",
    "execute_query",
    "expected_for",
    "load_dataset",
    "order_matters_for",
    "package_asker",
    "recover_from_run",
    "recover_sql",
    "refresh_expectations",
    "result_eq",
    "strict_set_eq",
]
