"""Result-set equivalence — the metric the text-to-SQL field actually uses.

**Execution accuracy** compares the *denotation* of two queries: run the
predicted SQL and the gold SQL against the same database and ask whether they
produced the same rows. It exists because the obvious alternative — comparing
the SQL strings — scores a correct query wrong whenever the model spells a
join differently, aliases a column differently, or reaches the same answer by
a `GROUP BY` where the gold used a subquery.

The comparison below is a faithful port of Spider's official test-suite
evaluator, `exec_eval.py` from `taoyds/test-suite-sql-eval` (Zhong, Yu and
Klein, *Semantic Evaluation for Text-to-SQL with Distilled Test Suites*, EMNLP
2020), which is the script the Spider leaderboard runs. Four decisions come
from there verbatim, and each one is load-bearing:

1. **Bag semantics, not set semantics.** Two identical rows are two rows.
   `multiset_eq` counts occurrences, so a query that loses a duplicate is
   wrong even though `set()` cannot tell.
2. **Row order matters only when the gold query orders.** Upstream:
   ``order_matters = 'order by' in g_str.lower()``. A question that did not ask
   for a sort must not be graded on one.
3. **Column order does not matter.** The evaluator searches column
   permutations, so `SELECT name, revenue` and `SELECT revenue, name` agree.
4. **Rows are canonicalised for the quick rejection by sorting each row's
   values under ``str(x) + str(type(x))``** — which is also why a `NULL` in a
   result set is a comparison rather than the `TypeError` that `sorted(row)`
   over mixed `None`/`str` would raise.

BIRD (Li et al., NeurIPS 2023) grades the same way with a blunter comparison,
``set(predicted_res) == set(ground_truth_res)``; that is `strict_set_eq` here,
reported beside execution accuracy as the stricter lower bound.

**Two deliberate deviations from upstream, both in the direction of a
reproducible number:**

- **Float tolerance.** Spider compares floats exactly. `SUM(UnitPrice *
  Quantity)` and an equivalent expression differ in the last bits of a double,
  and scoring that wrong measures IEEE 754, not the model. Values are
  canonicalised to `float_places` significant digits before comparison.
- **Deterministic permutation pruning.** Upstream's
  `get_constraint_permutation` samples 20 *random* rows to prune the column
  permutation space, so the same inputs can take different paths on different
  runs. The pruning is only a heuristic — it never changes the answer, only the
  work — so here it reads a fixed prefix of the rows instead. A scorecard that
  is not reproducible is not evidence.

**Predicted SQL is executed read-only at the driver level** (`mode=ro`), the
same boundary the Chinook tools use: the string comes from a model, and a
substring check for `DROP` is not a security control.

That sentence is why this module is **not** exempt from
`the-boundary-nobody-checked/06`. Grading is offline and a dataset's *gold*
SQL is the operator's, but the *predicted* query is the model's — the same
trust as a tool call, executed against the same connection shape — so it goes
through `openstategraph.readonly_sqlite` with every other read-only open, and
`ATTACH`/`VACUUM INTO` cannot write a file from inside a scorecard either.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Sequence

from openstategraph.readonly_sqlite import (
    ReadOnlyConnection,
    readonly_connection,
    sql_error_text,
)

Row = tuple[Any, ...]

#: Significant digits a float is rounded to before comparison. Six is well
#: below double precision and well above any figure Chinook holds (money to
#: two decimals, durations in whole milliseconds).
DEFAULT_FLOAT_PLACES = 6

#: How many rows of the candidate result the permutation pruner reads. A fixed
#: prefix, never a random sample — see the module docstring.
_PRUNE_SAMPLE = 50

#: Wall-clock ceiling for one query. A model can write a cartesian join.
DEFAULT_TIMEOUT_SECONDS = 30.0

_ORDER_BY = re.compile(r"\border\s+by\b", re.IGNORECASE)


@dataclass(frozen=True)
class QueryOutcome:
    """What one query did. Never an exception at the caller.

    A predicted query failing is *data* — it is one of the failure modes the
    scorecard names — so it must not be able to end the run.
    """

    ok: bool
    columns: tuple[str, ...] = ()
    rows: tuple[Row, ...] = ()
    error: str = ""
    seconds: float = 0.0


def order_matters_for(gold_sql: str) -> bool:
    """Spider's rule: the gold query's own `ORDER BY` decides."""
    return bool(_ORDER_BY.search(gold_sql or ""))


def connect_readonly(database: Path) -> ReadOnlyConnection:
    """`mode=ro` and one file, enforced by SQLite rather than by inspection."""
    if not Path(database).exists():
        raise FileNotFoundError(f"no database at {database}")
    connection = readonly_connection(Path(database))
    # Chinook holds a few rows whose bytes are not clean UTF-8. Upstream does
    # the same: a decoding error in one artist name must not fail an eval.
    connection.text_factory = lambda b: b.decode(errors="ignore")
    return connection


def execute_query(
    database: Path,
    sql: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> QueryOutcome:
    """Run one statement read-only and return its rows, or the error text."""
    import time

    started = time.monotonic()
    try:
        connection = connect_readonly(database)
    except FileNotFoundError as exc:
        return QueryOutcome(ok=False, error=str(exc))
    try:
        _install_deadline(connection, started, timeout)
        cursor = connection.execute(sql)
        rows = tuple(tuple(row) for row in cursor.fetchall())
        columns = tuple(str(column[0]) for column in (cursor.description or ()))
        return QueryOutcome(
            ok=True, columns=columns, rows=rows, seconds=time.monotonic() - started
        )
    except Exception as exc:  # sqlite3 raises half a dozen distinct classes
        # A refused second file reports as `not authorized`, which would land
        # in the scorecard as an unexplained failure rather than as a finding.
        refused = connection.refused_second_file
        text = (
            sql_error_text(connection, exc)
            if refused
            else f"{type(exc).__name__}: {exc}"
        )
        return QueryOutcome(ok=False, error=text, seconds=time.monotonic() - started)
    finally:
        connection.close()


def _install_deadline(connection: sqlite3.Connection, started: float, timeout: float) -> None:
    """Interrupt a runaway query without a second thread.

    `set_progress_handler` is called every N virtual-machine instructions;
    returning non-zero aborts the statement. That is the only in-process way to
    bound a `sqlite3` call, and a bound is required: a model can write a
    cross join over three tables without noticing.
    """
    import time

    def _handler() -> int:
        return 1 if (time.monotonic() - started) > timeout else 0

    connection.set_progress_handler(_handler, 10_000)


# --------------------------------------------------------------------------
# the comparison itself


def canonicalize(value: Any, places: int) -> Any:
    """One value, in the form the comparison sees.

    Only floats are touched, and only to `places` significant digits. `None`,
    `int`, `str` and `bytes` pass through: SQLite's own type affinity already
    makes `1` and `1.0` equal in Python, and rewriting strings would start
    grading spelling instead of denotation.
    """
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            return str(value)
        return float(f"%.{places}g" % value)
    return value


def _canonical_rows(rows: Iterable[Sequence[Any]], places: int) -> list[Row]:
    return [tuple(canonicalize(value, places) for value in row) for row in rows]


def permute_tuple(element: Row, perm: Sequence[int]) -> Row:
    """Upstream `permute_tuple`."""
    return tuple(element[i] for i in perm)


def unorder_row(row: Row) -> Row:
    """Upstream `unorder_row` — the `str(x) + str(type(x))` key is what makes a
    row containing `None` sortable at all."""
    return tuple(sorted(row, key=lambda x: str(x) + str(type(x))))


def quick_rej(result1: list[Row], result2: list[Row], order_matters: bool) -> bool:
    """Upstream `quick_rej`: a necessary condition, checked before the
    expensive permutation search."""
    s1 = [unorder_row(row) for row in result1]
    s2 = [unorder_row(row) for row in result2]
    if order_matters:
        return s1 == s2
    return set(s1) == set(s2)


def multiset_eq(l1: Sequence[Any], l2: Sequence[Any]) -> bool:
    """Upstream `multiset_eq` — bag equality, so duplicates count."""
    if len(l1) != len(l2):
        return False
    counts: dict[Any, int] = defaultdict(int)
    for element in l1:
        counts[element] += 1
    for element in l2:
        counts[element] -= 1
        if counts[element] < 0:
            return False
    return True


def _constraint_permutations(
    columns_of_1: list[set[Any]], result2: list[Row]
) -> Iterable[tuple[int, ...]]:
    """Upstream `get_constraint_permutation`, made deterministic.

    A column of result2 can only map onto a column of result1 if every value it
    holds is present in that column of result1. Checking a fixed prefix of rows
    prunes soundly and identically on every run.
    """
    num_cols = len(result2[0])
    constraints = [set(range(num_cols)) for _ in range(num_cols)]
    if num_cols <= 3:
        return product(*constraints)
    for row in result2[:_PRUNE_SAMPLE]:
        for col1 in range(num_cols):
            for col2 in set(constraints[col1]):
                if row[col2] not in columns_of_1[col1]:
                    constraints[col1].discard(col2)
    return product(*constraints)


def result_eq(
    gold: Sequence[Sequence[Any]],
    predicted: Sequence[Sequence[Any]],
    *,
    order_matters: bool,
    float_places: int = DEFAULT_FLOAT_PLACES,
) -> bool:
    """Execution accuracy for one item: do these two result sets denote the same
    answer? Upstream `result_eq`, with the two deviations named at the top."""
    result1 = _canonical_rows(gold, float_places)
    result2 = _canonical_rows(predicted, float_places)

    if not result1 and not result2:
        return True
    if len(result1) != len(result2):
        return False

    num_cols = len(result1[0])
    if len(result2[0]) != num_cols:
        return False
    if not quick_rej(result1, result2, order_matters):
        return False

    columns_of_1 = [{row[i] for row in result1} for i in range(num_cols)]
    for perm in _constraint_permutations(columns_of_1, result2):
        if len(perm) != len(set(perm)):
            continue
        permuted = result2 if num_cols == 1 else [permute_tuple(row, perm) for row in result2]
        if order_matters:
            if result1 == permuted:
                return True
        elif set(result1) == set(permuted) and multiset_eq(result1, permuted):
            return True
    return False


def strict_set_eq(
    gold: Sequence[Sequence[Any]], predicted: Sequence[Sequence[Any]]
) -> bool:
    """BIRD's comparison: `set(predicted) == set(gold)`, no permutation search
    and no float tolerance. Strictly harder to satisfy than `result_eq`, which
    is exactly why the scorecard carries both — the gap between them is the
    share of items that are right for a reason a blunt comparison would miss."""
    return {tuple(row) for row in gold} == {tuple(row) for row in predicted}


@dataclass(frozen=True)
class Comparison:
    """The two verdicts for one item, together with what the queries returned."""

    execution_match: bool
    exact_set_match: bool
    gold_rows: tuple[Row, ...] = field(default=())
    predicted_rows: tuple[Row, ...] = field(default=())


def compare(
    gold: QueryOutcome,
    predicted: QueryOutcome,
    *,
    order_matters: bool,
    float_places: int = DEFAULT_FLOAT_PLACES,
) -> Comparison:
    """Both metrics in one pass, so a caller cannot compute one and forget the
    other."""
    return Comparison(
        execution_match=result_eq(
            gold.rows, predicted.rows, order_matters=order_matters, float_places=float_places
        ),
        exact_set_match=strict_set_eq(gold.rows, predicted.rows),
        gold_rows=gold.rows,
        predicted_rows=predicted.rows,
    )


__all__ = [
    "Comparison",
    "DEFAULT_FLOAT_PLACES",
    "DEFAULT_TIMEOUT_SECONDS",
    "QueryOutcome",
    "canonicalize",
    "compare",
    "connect_readonly",
    "execute_query",
    "multiset_eq",
    "order_matters_for",
    "permute_tuple",
    "quick_rej",
    "result_eq",
    "strict_set_eq",
    "unorder_row",
]
