"""The run store, opened by a build whose schema has moved.

`the-boundary-nobody-checked/07`. `CREATE TABLE IF NOT EXISTS` is a no-op
against a table that already exists with the old shape, so before this ticket
the day `_COLUMNS` gained an entry an installation that had run once before
lost **every** run record from then on, behind one WARNING per run — on the
surface built to make runs visible. The reproduction found the reader is the
worse half: `read_runs` selects the columns it knows by name, so a store one
column behind answered `[]` for rows that were sitting in the file.

An older build is simulated by shortening `_COLUMNS` rather than by lengthening
it: a longer list would need a `RunRecord` field that does not exist, and the
property under test is *the table and the declaration disagree*, which is
symmetric.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from openstategraph import run_sinks
from openstategraph.run_sinks import RunBurst, RunRecord, SqliteRunSink


def _a_run(thread_id: str, at: str) -> RunRecord:
    return RunRecord(
        workflow_slug="w",
        thread_id=thread_id,
        at=at,
        question="q",
        answer="a",
        usage={"m": {"total_tokens": 3}},
    )


def _write_with_an_older_schema(
    monkeypatch: pytest.MonkeyPatch, path: Path, *, dropped: int = 2
) -> None:
    """A store as a build two columns ago would have left it."""
    monkeypatch.setattr(run_sinks, "_COLUMNS", run_sinks._COLUMNS[:-dropped])
    monkeypatch.setattr(run_sinks, "_BURST_COLUMNS", run_sinks._BURST_COLUMNS[:-1])
    sink = SqliteRunSink(path)
    sink.record(_a_run("before", "2026-08-29T00:00:00+0000"))
    sink.close()
    monkeypatch.undo()


def _columns(path: Path, table: str) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
    finally:
        connection.close()


def test_a_store_written_by_an_older_build_takes_todays_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole ticket: the row lands, and the old row is still there."""
    path = tmp_path / "runs.sqlite"
    _write_with_an_older_schema(monkeypatch, path)
    assert "usage" not in _columns(path, "runs")

    sink = SqliteRunSink(path)
    sink.record(_a_run("after", "2026-08-29T00:00:01+0000"))
    sink.close()

    assert "usage" in _columns(path, "runs")
    threads = [record.thread_id for record in run_sinks.read_runs(path=path)]
    assert threads == ["after", "before"]


def test_the_burst_table_is_reconciled_on_the_same_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both tables, because a burst insert shares the run row's transaction."""
    path = tmp_path / "runs.sqlite"
    _write_with_an_older_schema(monkeypatch, path)
    assert "capped" not in _columns(path, "run_bursts")

    record = _a_run("after", "2026-08-29T00:00:01+0000")
    record.bursts = [RunBurst(node="n", block="b", kind="text", text="hi", capped=True)]
    sink = SqliteRunSink(path)
    sink.record(record)
    sink.close()

    assert "capped" in _columns(path, "run_bursts")
    read_back = run_sinks.read_runs(path=path, with_bursts=True, audience="developer")
    assert [b.capped for b in read_back[0].bursts] == [True]


def test_a_reader_lists_what_an_older_store_holds_without_writing_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`openstategraph runs list` opens read-only and cannot reconcile anything.

    So the reader has to be tolerant on its own account: an installation that
    upgraded and has not run anything yet still has its history.
    """
    path = tmp_path / "runs.sqlite"
    _write_with_an_older_schema(monkeypatch, path)

    records = run_sinks.read_runs(path=path)

    assert [record.thread_id for record in records] == ["before"]
    assert records[0].usage == {}  # a column the file does not carry
    assert "usage" not in _columns(path, "runs")  # and reading added nothing


def test_reconciling_adds_and_never_removes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*Conversations are gold.* A column this build does not know is left alone."""
    path = tmp_path / "runs.sqlite"
    _write_with_an_older_schema(monkeypatch, path)
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("ALTER TABLE runs ADD COLUMN verdict TEXT")
    connection.close()

    sink = SqliteRunSink(path)
    sink.record(_a_run("after", "2026-08-29T00:00:01+0000"))
    sink.close()

    assert "verdict" in _columns(path, "runs")


def test_an_older_build_still_writes_and_reads_a_newer_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction, checked rather than assumed — and it already held.

    Every column is nullable and both the writer and the reader name their
    columns, so a build behind the store writes a row whose unknown columns are
    NULL and lists every row including the ones a newer build wrote.
    """
    path = tmp_path / "runs.sqlite"
    sink = SqliteRunSink(path)
    sink.record(_a_run("newer", "2026-08-29T00:00:00+0000"))
    sink.close()

    monkeypatch.setattr(run_sinks, "_COLUMNS", run_sinks._COLUMNS[:-2])
    older = SqliteRunSink(path)
    older.record(_a_run("older", "2026-08-29T00:00:01+0000"))
    older.close()

    threads = [record.thread_id for record in run_sinks.read_runs(path=path)]
    assert threads == ["older", "newer"]


def test_the_first_lost_row_is_louder_than_the_tenth(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A store that cannot record is a fact a reader needs, once, at ERROR.

    It still never raises: a sink is an observer, and `memory-and-replay/44`
    was careful that a door's turn does not depend on one.
    """
    path = tmp_path / "runs.sqlite"
    sink = SqliteRunSink(path)
    sink.record(_a_run("one", "2026-08-29T00:00:00+0000"))
    connection = sink._open()
    assert connection is not None
    with connection:
        connection.execute("CREATE TABLE gone AS SELECT * FROM runs")
        connection.execute("DROP TABLE runs")  # noqa: S608 - test-only sabotage

    with caplog.at_level(logging.DEBUG, logger="openstategraph.run_sinks"):
        sink.record(_a_run("two", "2026-08-29T00:00:01+0000"))
        sink.record(_a_run("three", "2026-08-29T00:00:02+0000"))

    levels = [
        record.levelno
        for record in caplog.records
        if record.name == "openstategraph.run_sinks"
    ]
    assert levels[0] == logging.ERROR
    assert levels[1:] and all(level < logging.ERROR for level in levels[1:])
    assert "runs list" in caplog.records[0].getMessage() or "export" in caplog.records[
        0
    ].getMessage()
