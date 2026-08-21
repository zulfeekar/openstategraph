"""The scorecard: one verdict per case, and the aggregate numbers.

**What is measured**, and the name each number goes by in the literature:

| Field | Meaning |
| --- | --- |
| `execution_accuracy` | Spider/BIRD **execution accuracy (EX)** — the predicted SQL and the gold SQL return the same rows, under bag semantics, ignoring column order, honouring row order only when the gold query sorts. |
| `exact_set_match` | BIRD's blunt `set(pred) == set(gold)`: no column permutation, no float tolerance. A strictly harder bar, reported as the lower bound. |
| `refusal_accuracy` | Of the deliberately unanswerable questions, the share the system declined instead of inventing. |
| `sql_recovery_rate` | The share of answerable questions where a query could be recovered from the answer at all. A system that is right but silent about its query is unverifiable, and that is a finding. |
| `attempts_total` / `retried` | Grader revise laps — how much the loop is working. |
| `latency_p50` / `p95` | Nearest-rank percentiles over per-item wall clock. |
| `cost` | Token counts measured from the runs themselves, per model, plus their sum. `usd` is always `null` and says why: prices are per-account and live in no file this project owns. An unmetered provider leaves `total_tokens` **null**, never `0`. |

**What is deliberately not measured** is on `NOT_MEASURED` and is printed on
the scorecard itself, not buried in a document: phrasing, tone, whether an
explanation is right for the reasons it gives, conversational behaviour across
turns, and safety. Execution accuracy grades the denotation of a query and
nothing else. Anyone reading a 0.9 should read that sentence on the same page.

**Determinism.** `to_json()` emits the same bytes for the same verdicts, in
dataset order, with floats rounded — so two scorecards diff cleanly and only
the timing block moves. There is no timestamp: a wall-clock field would make
every rerun a diff.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

#: The verdict vocabulary, in the order a reader should think about it. Fixed
#: strings: a scorecard is compared across runs, so these are an interface.
VERDICTS = (
    "correct",  # answerable, and the result sets agree
    "wrong_result",  # SQL ran, denotation differs
    "sql_error",  # SQL was recovered but did not execute
    "no_sql",  # answered with no query to check — unverifiable
    "refused_correctly",  # unanswerable, and it declined
    "should_have_refused",  # unanswerable, and it queried anyway
    "invented_answer",  # unanswerable, and it asserted a forbidden claim
    "dataset_error",  # the GOLD query failed — our bug, not the model's
    "run_error",  # the workflow itself raised
)

#: Printed on every scorecard. See the module docstring.
NOT_MEASURED = (
    "answer phrasing, tone, and whether the explanation is right for the right reasons",
    "conversational behaviour across turns (every case is a fresh thread)",
    "safety, prompt injection, and data exfiltration",
    # Tokens ARE measured now (`workflow-gallery` 35); what is still not
    # measured is money, and this line says only that.
    "money — tokens are measured, but no price table is owned here to cost them",
    "SQL efficiency (BIRD's Valid Efficiency Score is not computed)",
)


def _cost_row(cost: dict[str, Any]) -> str:
    """One line for the terminal: the measured total, then the caveat.

    `None` prints as the note alone — a row reading `0 tokens` for a run
    nothing metered would be a claim the dataset was free, which is the one
    thing this row must never say (`workflow-gallery` 35).
    """
    total = cost.get("total_tokens")
    note = str(cost.get("note") or "")
    if not isinstance(total, int) or isinstance(total, bool):
        return note or str(cost.get("usd"))
    models = cost.get("tokens") or {}
    who = f" across {len(models)} model(s)" if models else ""
    return f"{total:,} tokens{who} — {note}"


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile, stated explicitly so two runs agree.

    `numpy` is not a dependency and never should be for this; more importantly,
    "p95" is ambiguous across implementations (linear interpolation, exclusive
    ranks), and a benchmark number whose definition is implicit is a benchmark
    number nobody can reproduce.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(fraction * len(ordered))))
    return round(ordered[rank - 1], 3)


@dataclass(frozen=True)
class ItemVerdict:
    """One case, graded."""

    case_id: str
    question: str
    difficulty: str
    expects: str
    verdict: str
    seconds: float = 0.0
    attempts: int = 0
    execution_match: bool | None = None
    exact_set_match: bool | None = None
    sql: str | None = None
    sql_source: str = ""
    gold_row_count: int | None = None
    predicted_row_count: int | None = None
    error: str = ""

    @property
    def correct(self) -> bool:
        return self.verdict in ("correct", "refused_correctly")

    def to_json(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "difficulty": self.difficulty,
            "expects": self.expects,
            "verdict": self.verdict,
            "execution_match": self.execution_match,
            "exact_set_match": self.exact_set_match,
            "sql": self.sql,
            "sql_source": self.sql_source,
            "gold_row_count": self.gold_row_count,
            "predicted_row_count": self.predicted_row_count,
            "attempts": self.attempts,
            "seconds": round(self.seconds, 3),
            "error": self.error,
        }


@dataclass(frozen=True)
class Scorecard:
    """Every number the harness produces, and the honest caveats beside them."""

    dataset: str
    database: str
    model: str
    items: tuple[ItemVerdict, ...] = ()
    warnings: tuple[str, ...] = ()
    cost: dict[str, Any] = field(default_factory=dict)
    not_measured: tuple[str, ...] = NOT_MEASURED

    # -- headline numbers ---------------------------------------------------

    @property
    def answerable(self) -> tuple[ItemVerdict, ...]:
        return tuple(item for item in self.items if item.expects == "answer")

    @property
    def refusal_items(self) -> tuple[ItemVerdict, ...]:
        return tuple(item for item in self.items if item.expects == "refusal")

    @property
    def execution_accuracy(self) -> float:
        return _rate(sum(1 for i in self.answerable if i.execution_match), len(self.answerable))

    @property
    def exact_set_match(self) -> float:
        return _rate(sum(1 for i in self.answerable if i.exact_set_match), len(self.answerable))

    @property
    def refusal_accuracy(self) -> float:
        return _rate(
            sum(1 for i in self.refusal_items if i.verdict == "refused_correctly"),
            len(self.refusal_items),
        )

    @property
    def overall_accuracy(self) -> float:
        return _rate(sum(1 for i in self.items if i.correct), len(self.items))

    @property
    def sql_recovery_rate(self) -> float:
        return _rate(sum(1 for i in self.answerable if i.sql), len(self.answerable))

    @property
    def attempts_total(self) -> int:
        return sum(item.attempts for item in self.items)

    @property
    def retried(self) -> int:
        return sum(1 for item in self.items if item.attempts > 1)

    @property
    def latency_p50(self) -> float:
        return percentile([item.seconds for item in self.items], 0.5)

    @property
    def latency_p95(self) -> float:
        return percentile([item.seconds for item in self.items], 0.95)

    @property
    def total_seconds(self) -> float:
        return round(sum(item.seconds for item in self.items), 3)

    def by_difficulty(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for level in ("easy", "medium", "hard"):
            items = [i for i in self.answerable if i.difficulty == level]
            if not items:
                continue
            out[level] = {
                "n": len(items),
                "execution_accuracy": _rate(sum(1 for i in items if i.execution_match), len(items)),
            }
        return out

    def verdict_counts(self) -> dict[str, int]:
        """Every verdict in `VERDICTS` order, including the zeroes — a missing
        key in a diff reads as a format change, not as a number that moved."""
        counts = {name: 0 for name in VERDICTS}
        for item in self.items:
            counts[item.verdict] = counts.get(item.verdict, 0) + 1
        return counts

    def meets(self, threshold: float) -> bool:
        """The CI gate. `overall_accuracy`, because a harness that gated on
        execution accuracy alone would let a system score well by refusing
        nothing and inventing freely."""
        return self.overall_accuracy >= threshold

    # -- output -------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "database": self.database,
            "model": self.model,
            "cases": len(self.items),
            "metrics": {
                "execution_accuracy": self.execution_accuracy,
                "exact_set_match": self.exact_set_match,
                "refusal_accuracy": self.refusal_accuracy,
                "overall_accuracy": self.overall_accuracy,
                "sql_recovery_rate": self.sql_recovery_rate,
            },
            "by_difficulty": self.by_difficulty(),
            "verdicts": self.verdict_counts(),
            "effort": {
                "attempts_total": self.attempts_total,
                "retried_items": self.retried,
                "latency_p50": self.latency_p50,
                "latency_p95": self.latency_p95,
                "total_seconds": self.total_seconds,
            },
            "cost": self.cost,
            "not_measured": list(self.not_measured),
            "warnings": list(self.warnings),
            "items": [item.to_json() for item in self.items],
        }

    def render(self) -> str:
        """A fixed-width table. Same information as the JSON, for a terminal."""
        lines = [
            f"dataset            {self.dataset}  ({len(self.items)} cases)",
            f"database           {self.database}",
            f"model              {self.model or '(unspecified)'}",
            "",
            f"execution accuracy {self.execution_accuracy:>8.1%}   "
            f"({sum(1 for i in self.answerable if i.execution_match)}/{len(self.answerable)}"
            " answerable)",
            f"exact set match    {self.exact_set_match:>8.1%}   (stricter: BIRD-style set equality)",
            f"refusal accuracy   {self.refusal_accuracy:>8.1%}   "
            f"({len(self.refusal_items)} unanswerable cases)",
            f"overall accuracy   {self.overall_accuracy:>8.1%}   <- the CI gate",
            f"sql recovered      {self.sql_recovery_rate:>8.1%}",
            "",
            f"attempts           {self.attempts_total} total, {self.retried} item(s) retried",
            f"latency p50        {self.latency_p50:>8.2f}s",
            f"latency p95        {self.latency_p95:>8.2f}s",
            f"total              {self.total_seconds:>8.2f}s",
            f"cost               {_cost_row(self.cost)}",
        ]
        if self.by_difficulty():
            lines.append("")
            for level, block in self.by_difficulty().items():
                lines.append(
                    f"  {level:<8} {block['execution_accuracy']:>7.1%}  (n={block['n']})"
                )
        lines += ["", _verdict_block(self.verdict_counts()), "", _item_table(self.items)]
        if self.warnings:
            lines += ["", "warnings:"] + [f"  - {warning}" for warning in self.warnings]
        lines += ["", "not measured:"] + [f"  - {caveat}" for caveat in self.not_measured]
        return "\n".join(lines)


def _verdict_block(counts: dict[str, int]) -> str:
    return "verdicts: " + "  ".join(f"{name}={count}" for name, count in counts.items() if count)


def _item_table(items: Sequence[ItemVerdict]) -> str:
    width = max((len(item.case_id) for item in items), default=4)
    header = f"{'case'.ljust(width)}  {'verdict':<20} {'diff':<7} {'secs':>6}  question"
    rows = [header, "-" * len(header)]
    for item in items:
        question = item.question if len(item.question) <= 58 else item.question[:55] + "..."
        rows.append(
            f"{item.case_id.ljust(width)}  {item.verdict:<20} {item.difficulty:<7} "
            f"{item.seconds:>6.2f}  {question}"
        )
    return "\n".join(rows)


__all__ = ["ItemVerdict", "NOT_MEASURED", "Scorecard", "VERDICTS", "percentile"]
