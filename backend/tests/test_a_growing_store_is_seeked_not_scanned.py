"""The store never sweeps, so every read of it must cost what it returns.

`the-cost-of-one-more/08`. Two defects, one axis — *runs per store*, the one
axis this product guarantees only ever grows:

- the default `runs list` had no index to order by, so returning 25 rows read
  and sorted every row ever written;
- `runs export` bound one SQL variable per row and so was refused, silently,
  at 32,766 runs — losing the cadence it exists to carry.

Both are asserted here by mechanism rather than by stopwatch: a query plan for
the first, and the number of variables one statement binds for the second. A
millisecond is noise on this map; a change of class is not.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from openstategraph import run_sinks
from openstategraph.readonly_sqlite import ReadOnlyConnection, readonly_closing
from openstategraph.run_sinks import (
    RunBurst,
    RunRecord,
    SqliteRunSink,
    read_runs,
)


def a_burst(**overrides: Any) -> RunBurst:
    fields: dict[str, Any] = {
        "node": "answer",
        "block": "text",
        "kind": "answer",
        "audience": "developer",
        "first_seq": 0,
        "last_seq": 1,
        "first_ms": 0,
        "last_ms": 5,
        "chunks": 2,
        "chars": 4,
        "text": "abcd",
        "cadence": b"\x02\x05",
    }
    fields.update(overrides)
    return RunBurst(**fields)


def a_store(path: Path, count: int, *, bursts: bool = True) -> Path:
    """`count` finished turns, spread over several workflows, threads and sessions."""
    sink = SqliteRunSink(path)
    for index in range(count):
        sink.record(
            RunRecord(
                kind="run",
                workflow_slug=f"w{index % 7}",
                thread_id=f"t{index % 11}",
                session_id=f"s{index % 13}",
                question=f"q{index}",
                answer=f"a{index}",
                seconds=0.1,
                bursts=[a_burst()] if bursts else [],
            )
        )
    sink.close()
    return path


class RefusingConnection(ReadOnlyConnection):
    """A store whose `run_bursts` read is refused, and nothing else.

    `sqlite3.Connection` is an immutable type, so the refusal is injected by
    the factory `readonly_connection` already takes rather than by patching a
    method onto it — which is also closer to the defect: the reader's own
    connection is what answered *too many SQL variables*.
    """

    def execute(self, sql: str, *args: Any) -> Any:  # type: ignore[override]
        if "FROM run_bursts" in sql:
            raise sqlite3.OperationalError("too many SQL variables")
        return super().execute(sql, *args)


def refuse_the_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(path: Any) -> RefusingConnection:
        connection = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, factory=RefusingConnection
        )
        assert isinstance(connection, RefusingConnection)
        return connection

    monkeypatch.setattr(run_sinks, "readonly_connection", connect)


def plan_for(path: Path, sql: str, args: tuple[Any, ...] = ()) -> list[str]:
    with readonly_closing(path) as connection:
        return [
            row[-1] for row in connection.execute("EXPLAIN QUERY PLAN " + sql, args)
        ]


# --------------------------------------------------------------------------
# 1. Every listing seeks
# --------------------------------------------------------------------------

#: The ordering every listing asks for, read out of the module rather than
#: spelled again here.
#:
#: It used to be the literal `ORDER BY at DESC`, and `the-cost-of-one-more/11`
#: is why it is not: an expression index answers only an `ORDER BY` naming the
#: *same* expression, so a second spelling of it in this file would not have
#: gone red — it would have quietly gone on measuring a query nobody runs, and
#: reported a plan for it.
ORDER = f"ORDER BY {run_sinks.CHRONOLOGICAL} DESC, rowid DESC"

LISTINGS = {
    "the default listing": (
        f"SELECT rowid,at FROM runs {ORDER} LIMIT ?",
        (25,),
    ),
    "--workflow": (
        f"SELECT rowid,at FROM runs WHERE workflow_slug = ? {ORDER} LIMIT ?",
        ("w1", 25),
    ),
    "--session": (
        f"SELECT rowid,at FROM runs WHERE session_id = ? {ORDER} LIMIT ?",
        ("s1", 25),
    ),
    "--thread": (
        f"SELECT rowid,at FROM runs WHERE thread_id = ? {ORDER} LIMIT ?",
        ("t1", 25),
    ),
}


@pytest.mark.parametrize("listing", sorted(LISTINGS))
def test_every_listing_is_answered_out_of_an_index(tmp_path: Path, listing: str) -> None:
    """The four listings `openstategraph runs list` can ask, by plan.

    `--session` was the one with no index at all: a `SCAN runs` with no
    covering index behind it, which on a table that never sweeps is O(every
    run ever recorded) to print a page of 25.

    A bare `SCAN` is the tell, not the word: the unfiltered listing is `SCAN
    runs USING INDEX runs_at_utc`, which walks the index in the order the
    query asked for and stops at the `LIMIT` — proved to be O(limit) by the
    counting test below rather than by reading the word "SCAN".

    `--thread` joined the other three in `the-cost-of-one-more/11`. `08` left
    it with a temp sort on the argument that one conversation is bounded by a
    person's patience, which was right; the index it needed anyway for the
    equality search is now one column longer and the sort is gone for free.
    """
    store = a_store(tmp_path / "runs.sqlite", 200)
    sql, args = LISTINGS[listing]

    plan = plan_for(store, sql, args)

    assert any("INDEX runs" in step for step in plan), (
        f"{listing} reads the whole store: {plan}"
    )


def test_the_default_listing_costs_the_page_and_not_the_store(tmp_path: Path) -> None:
    """A counting assertion, which is the shape this map asks its scaling tests for.

    Sqlite's progress handler fires every N virtual-machine steps, so the count
    is work done rather than time taken — no stopwatch, and nothing that varies
    with the machine. Eight times the store, for the same page.
    """

    def steps(store: Path) -> int:
        counted = 0

        def tick() -> int:
            nonlocal counted
            counted += 1
            return 0

        with readonly_closing(store) as connection:
            connection.set_progress_handler(tick, 20)
            connection.execute(*LISTINGS["the default listing"]).fetchall()
        return counted

    small = steps(a_store(tmp_path / "small.sqlite", 200))
    large = steps(a_store(tmp_path / "large.sqlite", 1600))

    assert large <= small * 1.5, (
        f"reading 25 rows costs {small} steps out of 200 runs and {large} out "
        f"of 1600 — the page is being paid for with the store"
    )


def test_the_default_listing_does_not_sort_the_whole_store_in_memory(
    tmp_path: Path,
) -> None:
    """`USE TEMP B-TREE FOR ORDER BY` is the whole table, sorted, to print 25.

    Only the default listing is held to this. A filter narrows to one
    conversation or one session — bounded by a person's patience rather than by
    the store — so a temp sort there is over a bounded set and is not on this
    axis. The unfiltered listing has nothing to narrow it.
    """
    store = a_store(tmp_path / "runs.sqlite", 200)
    sql, args = LISTINGS["the default listing"]

    plan = plan_for(store, sql, args)

    assert not any("TEMP B-TREE" in step for step in plan), (
        f"the default listing sorts every row to return a page: {plan}"
    )


def test_an_index_arrives_on_a_store_that_already_exists(tmp_path: Path) -> None:
    """A store written by an older build gets the indexes on its next write.

    `the-boundary-nobody-checked/07`'s shape and no second mechanism:
    `CREATE INDEX IF NOT EXISTS` is additive, is re-run on every `_open`, and
    costs nothing on a file that already has them. There is no backfill to do —
    sqlite builds the index from the rows that are there.
    """
    store = a_store(tmp_path / "runs.sqlite", 50)
    with sqlite3.connect(store) as connection:
        for name in ("runs_at_utc", "runs_session_utc"):
            connection.execute(f"DROP INDEX IF EXISTS {name}")
    with readonly_closing(store) as connection:
        before = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "runs_at_utc" not in before

    a_store(store, 1)  # one more run, through the ordinary write path

    with readonly_closing(store) as connection:
        after = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"runs_at_utc", "runs_session_utc"} <= after
    assert not any("TEMP B-TREE" in step for step in plan_for(store, *LISTINGS["the default listing"]))


# --------------------------------------------------------------------------
# 2. The export carries the cadence however large the store is
# --------------------------------------------------------------------------


def test_the_cadence_read_never_binds_more_variables_than_sqlite_takes() -> None:
    """32,766 is a real ceiling and it is reached by a store that only grows.

    `SQLITE_LIMIT_VARIABLE_NUMBER`; one variable per row id; `runs export`
    defaults to `--limit 100000`. The fix is a bound on the batch, which is
    why the bound is a named constant rather than a number inside a loop.
    """
    ceiling = sqlite3.connect(":memory:").getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    assert run_sinks.CADENCE_BATCH <= min(ceiling, 999), (
        "the batch must fit the oldest sqlite this package supports, not this one"
    )


def test_a_store_larger_than_the_batch_still_exports_every_run_s_cadence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The red test of the reproduction, at a size a suite can afford.

    The reproduction is 33,000 runs; the mechanism is *more row ids than one
    statement may bind*, and shrinking the bound reproduces it exactly at 40
    rows. Every row came back, and every row came back with what it arrived as.
    """
    monkeypatch.setattr(run_sinks, "CADENCE_BATCH", 7)
    store = a_store(tmp_path / "runs.sqlite", 40)

    rows = read_runs(path=store, limit=1000, with_bursts=True)

    assert len(rows) == 40
    assert [len(row.bursts) for row in rows] == [1] * 40


def test_the_batches_stay_in_step_with_the_rows_they_belong_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batching must not shuffle a cadence onto the wrong turn.

    `_attach_bursts`' own reason for keying on `runs.rowid` — a thread holds
    many turns and would give each of them the whole conversation's cadence —
    is what a batched read is most able to break.
    """
    monkeypatch.setattr(run_sinks, "CADENCE_BATCH", 3)
    sink = SqliteRunSink(tmp_path / "runs.sqlite")
    for index in range(20):
        sink.record(
            RunRecord(
                kind="run",
                thread_id="t",
                question=f"q{index}",
                bursts=[a_burst(text=f"burst-{index}")],
            )
        )
    sink.close()

    rows = read_runs(path=tmp_path / "runs.sqlite", limit=100, with_bursts=True)

    assert [row.bursts[0].text for row in rows] == [
        f"burst-{index}" for index in reversed(range(20))
    ]


# --------------------------------------------------------------------------
# 3. A refused read says so out loud; an absent one does not
# --------------------------------------------------------------------------


def test_a_store_with_no_cadence_table_is_an_answer_and_not_an_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """*This store predates the cadence table* is the docstring's own case.

    It stays a `debug` line and an empty list, because it is not a fault and a
    warning per listing would be a log flood on every store written before
    `memory-and-replay/47`.
    """
    store = a_store(tmp_path / "runs.sqlite", 3, bursts=False)
    with sqlite3.connect(store) as connection:
        connection.execute("DROP TABLE run_bursts")

    with caplog.at_level(logging.DEBUG, logger=run_sinks.logger.name):
        rows = read_runs(path=store, limit=10, with_bursts=True)

    assert [row.bursts for row in rows] == [[], [], []]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_refused_cadence_read_is_an_error_that_names_what_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`logger.debug` and exit 0 is how 33,000 rows lost their cadence in silence.

    The two cases share one `except` no longer: an absent table is *no
    cadence*, and a refused query is a read this build could not perform.
    `the-boundary-nobody-checked/07` set the shape — an ERROR that names the
    file and says what will be missing from it.
    """
    store = a_store(tmp_path / "runs.sqlite", 3)

    refuse_the_cadence(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger=run_sinks.logger.name):
        with pytest.raises(run_sinks.RunCadenceUnavailable):
            read_runs(path=store, limit=10, with_bursts=True)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a refused cadence read must not be a debug line"
    assert str(store) in errors[0].getMessage()
    assert "cadence" in errors[0].getMessage()


def test_an_export_that_could_not_carry_the_cadence_does_not_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command exists so nobody truncates on the strength of a partial file.

    So it refuses rather than under-delivers: a non-zero exit, no file written,
    and a sentence saying what would have been missing.
    """
    from openstategraph.cli import main

    store = a_store(tmp_path / "runs.sqlite", 3)
    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(store))

    refuse_the_cadence(monkeypatch)

    out = tmp_path / "exported" / "runs.json"
    assert main(["runs", "export", "--to", str(out)]) != 0
    assert not out.exists()
    assert "cadence" in capsys.readouterr().err
