""""What did the work cost" asked of the store instead of of one run.

`stable-beta-public/03`, slice 2 of `docs/plans/token-status-bar/04-slices.md`.
Slice 1 landed the door and the published shape with every figure at its
fresh-install value; this is the query behind it.

**Every fixture is written through `SqliteRunSink`.** Nothing here inserts a
row by hand, and that is the point rather than tidiness: the column this sum
reads (`total_tokens`) is *derived on write* by `_column`, from a mapping keyed
by model, and a hand-written `INSERT` would let a test agree with itself about
a number the product never computes. A fixture that goes through the sink is a
fixture that would notice.

The two answers that are easy to conflate, and are separated here on purpose:

- `usage == {}` is **nobody reported**. It is a run — it happened, it is
  counted in its sitting — and it contributes no tokens and no model row. A
  by-model table with a nameless row in it would be inventing a model.
- A sitting's order is by **instant**, not by the text of `at`
  (`the-cost-of-one-more/11`). The stamps below differ only in offset, so a
  reader that sorted them as text would pass every other assertion in this file
  and fail that one.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.run_sinks import (
    RunRecord,
    SqliteRunSink,
    spend_summary,
)


def write(path: Path, *records: RunRecord) -> Path:
    """A store holding exactly these runs, written the way a run writes them."""
    sink = SqliteRunSink(path)
    for record in records:
        sink.record(record)
    sink.close()
    return path


def run(
    *,
    at: str = "2026-09-04T10:00:00+0000",
    session_id: str = "s-1",
    usage: dict | None = None,
) -> RunRecord:
    return RunRecord(
        kind="run",
        at=at,
        session_id=session_id,
        thread_id="t",
        workflow_slug="w",
        usage=usage or {},
    )


def spent(model: str, *, inp: int, out: int) -> dict:
    return {model: {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}}


class TestAStoreWithNothingInIt:
    def test_a_fresh_store_is_zero_not_missing(self, tmp_path: Path) -> None:
        """No file at all — the first thing a fresh install asks.

        A raise here would put an error in the editor's status bar on a
        machine that has simply not run anything yet, which is the ordinary
        state of every install on its first morning.
        """
        summary = spend_summary(tmp_path / "never-written.sqlite")

        assert summary.grand_total == 0
        assert summary.cached_total is None
        assert summary.by_model == ()
        assert summary.sessions == ()
        assert summary.session_by_model == ()
        assert summary.session_total == 0


class TestTheGrandTotal:
    def test_grand_total_sums_every_run_across_sessions(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1", usage=spent("m", inp=100, out=10)),
            run(session_id="s-1", usage=spent("m", inp=200, out=20)),
            run(session_id="s-2", usage=spent("m", inp=300, out=30)),
        )

        assert spend_summary(store).grand_total == 660

    def test_a_run_that_reported_nothing_counts_zero_tokens_and_one_run(
        self, tmp_path: Path
    ) -> None:
        """*Nobody reported* is not *nothing was spent*, and neither is it *no run*.

        The row is real: it is counted in its sitting, so a person reading the
        sessions list sees the run they remember making. What it may not do is
        add a zero to a model's table, because there is no model to add it to.
        """
        store = write(
            tmp_path / "runs.sqlite",
            run(usage=spent("m", inp=100, out=10)),
            run(usage={}),
        )

        summary = spend_summary(store)

        assert summary.grand_total == 110
        assert [row.model for row in summary.by_model] == ["m"]
        assert summary.by_model[0].runs == 1
        assert summary.sessions[0].runs == 2


class TestTheModels:
    def test_by_model_keeps_two_models_apart(self, tmp_path: Path) -> None:
        """*Which model cost what* is only answerable while they are apart —
        `RunRecord.usage`' own rule, carried through the sum."""
        store = write(
            tmp_path / "runs.sqlite",
            RunRecord(
                kind="run",
                at="2026-09-04T10:00:00+0000",
                session_id="s-1",
                usage={
                    **spent("big", inp=1000, out=100),
                    **spent("small", inp=10, out=1),
                },
            ),
        )

        summary = spend_summary(store)

        assert [row.model for row in summary.by_model] == ["big", "small"]
        assert (summary.by_model[0].input_tokens, summary.by_model[0].output_tokens) == (
            1000,
            100,
        )
        assert summary.by_model[0].total_tokens == 1100
        assert summary.by_model[1].total_tokens == 11

    def test_the_largest_model_is_first(self, tmp_path: Path) -> None:
        """Ordered by what it cost, not by the order it was met in: the bar
        shows the head of this list, and the head should be the answer to
        *what is expensive*."""
        store = write(
            tmp_path / "runs.sqlite",
            run(usage=spent("cheap", inp=1, out=1)),
            run(usage=spent("dear", inp=900, out=90)),
        )

        assert [row.model for row in spend_summary(store).by_model] == ["dear", "cheap"]

    def test_one_model_over_several_runs_is_one_row(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1", usage=spent("m", inp=100, out=10)),
            run(session_id="s-2", usage=spent("m", inp=200, out=20)),
        )

        summary = spend_summary(store)

        assert len(summary.by_model) == 1
        assert summary.by_model[0].runs == 2
        assert summary.by_model[0].total_tokens == 330

    def test_the_detail_figures_wait_for_their_own_slice(self, tmp_path: Path) -> None:
        """Slice 2 fills four figures and leaves three at *not reported*.

        Asserted rather than left implicit, because `None` is a claim on this
        wire — *no run carried the key* — and until slice 4 reads the keys it
        is the only honest one this query can make.
        """
        store = write(tmp_path / "runs.sqlite", run(usage=spent("m", inp=1, out=1)))

        row = spend_summary(store).by_model[0]

        assert row.cached_tokens is None
        assert row.cache_creation_tokens is None
        assert row.reasoning_tokens is None
        assert spend_summary(store).cached_total is None


#: Three sittings, in the order they happened, spelled in three zones — the
#: fixture shape `test_newest_first_is_the_latest_instant.py` arrived at. Read
#: as text the newest sorts last, so a `max(at)` reads this list backwards.
BY_INSTANT: tuple[tuple[str, str], ...] = (
    ("oldest", "2026-10-25T03:10:00+0300"),  # 00:10Z
    ("middle", "2026-10-25T02:50:00+0200"),  # 00:50Z
    ("newest", "2026-10-25T01:30:00+0000"),  # 01:30Z
)


class TestTheSittings:
    def test_the_fixture_is_wrong_under_a_text_sort(self) -> None:
        """The control, so the ordering test below cannot pass vacuously."""
        assert [name for name, _ in sorted(BY_INSTANT, key=lambda p: p[1])] == [
            "newest",
            "middle",
            "oldest",
        ]

    def test_sessions_are_newest_first_by_last_at(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            *(
                run(at=at, session_id=name, usage=spent("m", inp=1, out=1))
                for name, at in BY_INSTANT
            ),
        )

        assert [row.session_id for row in spend_summary(store).sessions] == [
            "newest",
            "middle",
            "oldest",
        ]

    def test_a_sitting_carries_its_span_and_its_count(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(at=BY_INSTANT[0][1], session_id="s", usage=spent("m", inp=1, out=1)),
            run(at=BY_INSTANT[2][1], session_id="s", usage=spent("m", inp=3, out=1)),
        )

        (sitting,) = spend_summary(store).sessions

        assert sitting.runs == 2
        assert sitting.total_tokens == 6
        assert (sitting.first_at, sitting.last_at) == (
            BY_INSTANT[0][1],
            BY_INSTANT[2][1],
        )

    def test_every_sitting_is_listed(self, tmp_path: Path) -> None:
        store = write(
            tmp_path / "runs.sqlite",
            run(session_id="s-1"),
            run(session_id="s-2"),
            run(session_id=""),
        )

        assert len(spend_summary(store).sessions) == 3
