"""What the bottom bar's one question costs on a store that only grows.

`stable-beta-public/03`, slice 6 of `docs/plans/token-status-bar/04-slices.md`,
and the `the-cost-of-one-more` axis it belongs to: **runs per store**. The run
store is designed never to sweep — *conversations are gold* — so every reader
of it inherits a table that grows forever, and `spend_summary` is the third
such reader beside `read_runs` and `read_run_bursts`. Its own docstring already
says the by-model walk is O(runs) *deliberately*, because sqlite cannot group
by a key inside a JSON document and the alternative is a per-model table for a
figure a status bar reads once a minute. A cost accepted on purpose is exactly
the kind that has to be measured, or the sentence accepting it is a story.

**Measured on this checkout, 2026-09-04, no model called** — ten thousand runs
written through `SqliteRunSink`, three models, forty sittings, one run in seven
reporting nothing:

| runs | `spend_summary()` best of 5 | ratio |
| --- | --- | --- |
| 2,500 | 7.3 ms | |
| 5,000 | 14.4 ms | ×1.98 |
| 10,000 | 28.4 ms | ×1.98 |
| 20,000 | 67.1 ms | ×2.36 |

Linear, and about **3 µs per run**. The other axis a user moves is *sittings*,
because a sitting is a browser tab: `_SESSION_SPEND` groups by `session_id` and
makes two correlated seeks per group, so a store of ten thousand runs in ten
thousand tabs is the worst case anybody can actually produce. It costs 48.5 ms
against the 26.4 ms of the same rows in forty tabs — the seeks ride
`runs_session_utc`, so the group count is a coefficient rather than an exponent.

**Two pins, deliberately different in kind**, following
`test_the_setup_path_stays_cheap.py`:

- **A ceiling, which is a smoke alarm and not a stopwatch.** A wall-clock
  assertion tight enough to catch a 3× regression would flake on a loaded
  machine — these numbers are one laptop's, and CI's will differ. The ceiling
  is ~35× the measured figure, so what it actually catches is the regression
  that would matter here: a query issued *per row*, an open of the store per
  read, or a network call acquired by a path that has none.
- **A shape, which is sharp.** Four times the rows must not cost eight times
  the time. That is what catches a change of complexity class, which the loose
  ceiling by construction cannot: quadratic at ten thousand rows would still
  land comfortably under a second.

And an exactness assertion beside both, because a fast wrong answer is worse
than a slow right one: the grand total at ten thousand rows is checked against
the arithmetic the fixture knows.

The fixtures are module-scoped: writing 12,500 rows through the real sink is
~10 s of this suite, and the sink commits per row on purpose. Nothing here
inserts a row by hand, for the reason `test_spend_summary.py` gives — the
column this sum reads is derived on write, and a hand-written `INSERT` would
let the test agree with itself about a number the product never computes.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from openstategraph.run_sinks import RunRecord, SqliteRunSink, spend_summary

#: ~35× the 28 ms measured for ten thousand runs. Loose on purpose; see the
#: module docstring for what that looseness buys and what the ratio pin below
#: covers instead.
BUDGET_SECONDS = 1.0

#: Four times the rows, linear, would be ×4. Twice that is the line between
#: "this machine was busy" and "this walk changed class".
LINEAR_ENOUGH = 8.0

SMALL = 2_500
LARGE = 10_000

MODELS = ("gpt-4.1-mini", "claude-sonnet-4-5", "gpt-oss:120b-cloud")
SITTINGS = 40

#: One run in seven reported nothing — the `usage == {}` case, which is a run
#: and not a spend. Keeping it in the fixture means the walk being timed is the
#: walk the product does, branch and all.
SILENT_EVERY = 7


def _usage(index: int) -> dict:
    if index % SILENT_EVERY == 0:
        return {}
    return {
        MODELS[index % len(MODELS)]: {
            "input_tokens": 100,
            "output_tokens": 40,
            "total_tokens": 140,
            "input_token_details": {"cache_read": 11},
        }
    }


def _spent(count: int) -> int:
    """What the fixture below must add up to, computed the other way round."""
    return sum(140 for index in range(count) if index % SILENT_EVERY)


def _store(path: Path, count: int) -> Path:
    sink = SqliteRunSink(path)
    for index in range(count):
        sink.record(
            RunRecord(
                kind="run",
                at=f"2026-09-04T10:{index % 60:02d}:00+0000",
                session_id=f"s-{index % SITTINGS}",
                thread_id=f"t-{index}",
                workflow_slug="w",
                usage=_usage(index),
            )
        )
    sink.close()
    return path


def _best_of(store: Path, *, attempts: int = 3) -> float:
    spend_summary(store, session_id="s-3")  # warm the page cache, as a live server is
    return min(
        _timed(store) for _ in range(attempts)
    )


def _timed(store: Path) -> float:
    started = time.perf_counter()
    spend_summary(store, session_id="s-3")
    return time.perf_counter() - started


@pytest.fixture(scope="module")
def ten_thousand(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _store(tmp_path_factory.mktemp("spend-large") / "runs.sqlite", LARGE)


@pytest.fixture(scope="module")
def two_and_a_half_thousand(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _store(tmp_path_factory.mktemp("spend-small") / "runs.sqlite", SMALL)


class TestTenThousandRuns:
    def test_the_bar_s_question_stays_milliseconds_not_seconds(
        self, ten_thousand: Path
    ) -> None:
        elapsed = _best_of(ten_thousand)

        assert elapsed < BUDGET_SECONDS, (
            f"spend_summary() over {LARGE:,} runs took {elapsed * 1000:.0f} ms "
            f"against a {BUDGET_SECONDS * 1000:.0f} ms ceiling. That ceiling is "
            "~35x the measured figure on purpose, so crossing it means the read "
            "acquired a cost per row rather than merely slowing down. Re-measure "
            "before raising it, and record the number in "
            ".scratch/the-cost-of-one-more/."
        )

    def test_and_answers_correctly_at_that_size(self, ten_thousand: Path) -> None:
        """A fast wrong answer would satisfy every assertion above."""
        summary = spend_summary(ten_thousand, session_id="s-3")

        assert summary.grand_total == _spent(LARGE)
        assert len(summary.sessions) == SITTINGS
        assert {row.model for row in summary.by_model} == set(MODELS)
        assert summary.session_total == sum(
            row.total_tokens for row in summary.session_by_model
        )

    def test_four_times_the_runs_does_not_cost_eight_times_the_time(
        self, ten_thousand: Path, two_and_a_half_thousand: Path
    ) -> None:
        """The pin the loose ceiling cannot carry: a change of complexity
        class. Quadratic here would be ×16 and still under a second."""
        small = _best_of(two_and_a_half_thousand)
        large = _best_of(ten_thousand)

        ratio = large / small
        assert ratio < LINEAR_ENOUGH, (
            f"{SMALL:,} runs cost {small * 1000:.1f} ms and {LARGE:,} cost "
            f"{large * 1000:.1f} ms — x{ratio:.1f} for four times the rows, "
            "against x2 measured. A walk over the store's usage documents is "
            "O(runs) by design; this says it has stopped being O(runs)."
        )
