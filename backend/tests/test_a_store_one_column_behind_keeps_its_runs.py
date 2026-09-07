"""A store written before a column existed, opened by the build that added it.

`the-cost-of-one-more/12`. `_open` created the indexes and *then* reconciled
the columns, so against a file whose `runs` table predates one of the columns
an index names, `CREATE INDEX` raised `no such column` — and the handler was
the whole-open handler, which latches `_broken` for the life of the sink. Every
run that process recorded afterwards was dropped, at `warning`, behind a
message naming a missing column rather than saying runs were being lost.

The fixture is the file an older build actually leaves: the table without the
column, its rows in it, and the indexes that build could have had — which are
derived here as *today's* indexes minus the ones naming the column it did not
have, so the fixture cannot go stale against `_INDEXES`. It is built with SQL
rather than by shortening `_COLUMNS`, because the column this defect turns on
(`session_id`) is not at the end of that tuple and the writer cannot be
persuaded to leave a hole in the middle of it.

`test_every_indexed_column_can_be_the_missing_one` is the part that holds the
class rather than the instance: it reads `_INDEXES`, so a fifth index on a
sixteenth column is covered on the day it is declared.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

import pytest

from openstategraph import run_sinks
from openstategraph.run_sinks import RunBurst, RunRecord, SqliteRunSink


def _names_column(keys: str, column: str) -> bool:
    return re.search(rf"\b{re.escape(column)}\b", keys) is not None


def _indexed_columns() -> list[tuple[str, str]]:
    """Every `(table, column)` any index names — derived, never listed."""
    declared = {table: columns for table, columns, _ in run_sinks._tables()}
    found = [
        (table, column)
        for table, columns in declared.items()
        for column in columns
        if any(
            indexed == table and _names_column(keys, column)
            for _, indexed, keys in run_sinks._INDEXES
        )
    ]
    assert ("runs", "session_id") in found  # the column the defect was found on
    return found


def _a_run(thread_id: str, at: str) -> RunRecord:
    record = RunRecord(
        workflow_slug="w",
        thread_id=thread_id,
        at=at,
        question="q",
        answer="a",
    )
    record.bursts = [RunBurst(node="n", block="b", kind="text", text="hi")]
    return record


def _a_store_without(path: Path, table: str, missing: str) -> None:
    """The file a build that had never heard of `missing` leaves behind."""
    connection = sqlite3.connect(path)
    try:
        with connection:
            for name, columns, types in run_sinks._tables():
                kept = [
                    column
                    for column in columns
                    if not (name == table and column == missing)
                ]
                declared = ",".join(
                    f"{column} {types.get(column, 'TEXT')}" for column in kept
                )
                connection.execute(f"CREATE TABLE {name} ({declared})")
                if name == "runs":
                    row = {
                        "kind": "run",
                        "at": "2026-08-29T00:00:00+0000",
                        "thread_id": "before",
                    }
                    placeholders = ",".join("?" for _ in kept)
                    connection.execute(
                        f"INSERT INTO runs ({','.join(kept)}) "
                        f"VALUES ({placeholders})",
                        [row.get(column) for column in kept],
                    )
            for name, indexed, keys in run_sinks._INDEXES:
                if indexed == table and _names_column(keys, missing):
                    continue
                connection.execute(f"CREATE INDEX {name} ON {indexed} ({keys})")
    finally:
        connection.close()


def _threads(path: Path) -> list[str]:
    return [record.thread_id for record in run_sinks.read_runs(path=path)]


def test_a_store_missing_an_indexed_column_keeps_the_runs_it_is_given(
    tmp_path: Path,
) -> None:
    """The whole ticket: the column arrives, the row lands, the old row stays."""
    path = tmp_path / "runs.sqlite"
    _a_store_without(path, "runs", "session_id")

    sink = SqliteRunSink(path)
    sink.record(_a_run("after", "2026-08-29T00:00:01+0000"))
    sink.close()

    assert _threads(path) == ["after", "before"]


def test_every_run_after_it_is_lost_too(tmp_path: Path) -> None:
    """The severity, asserted rather than described.

    One refused open latched `_broken`, so the loss was not one row — it was
    every row that process would ever record, with nothing raised to the caller
    to say so.
    """
    path = tmp_path / "runs.sqlite"
    _a_store_without(path, "runs", "session_id")

    sink = SqliteRunSink(path)
    for index in range(3):
        sink.record(_a_run(f"after-{index}", f"2026-08-29T00:00:0{index + 1}+0000"))
    sink.close()

    assert _threads(path) == ["after-2", "after-1", "after-0", "before"]


@pytest.mark.parametrize(("table", "column"), _indexed_columns())
def test_every_indexed_column_can_be_the_missing_one(
    tmp_path: Path, table: str, column: str
) -> None:
    """The class, not the instance — the census comes from `_INDEXES` itself.

    Reconciling before indexing fixes the column this was found on. It is the
    *order* that has to hold, and an order held by a comment is one a future
    statement gets wrong, so every column any index names is exercised as the
    one an older store lacks.
    """
    path = tmp_path / "runs.sqlite"
    _a_store_without(path, table, column)

    sink = SqliteRunSink(path)
    sink.record(_a_run("after", "2026-08-29T00:00:01+0000"))
    sink.close()

    assert "after" in _threads(path)
    read_back = run_sinks.read_runs(path=path, with_bursts=True, audience="developer")
    assert [burst.text for burst in read_back[0].bursts] == ["hi"]


def test_the_column_is_added_and_the_index_that_names_it_is_built(
    tmp_path: Path,
) -> None:
    """Not merely tolerated: the store comes out in this build's shape."""
    path = tmp_path / "runs.sqlite"
    _a_store_without(path, "runs", "session_id")

    sink = SqliteRunSink(path)
    sink.record(_a_run("after", "2026-08-29T00:00:01+0000"))
    sink.close()

    connection = sqlite3.connect(path)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(runs)")]
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    finally:
        connection.close()

    assert "session_id" in columns
    assert {name for name, _, _ in run_sinks._INDEXES} <= indexes


def test_a_store_one_column_behind_is_not_a_broken_store(tmp_path: Path) -> None:
    """`_broken` means *this file is not a database I can use*, and this is."""
    path = tmp_path / "runs.sqlite"
    _a_store_without(path, "runs", "session_id")

    sink = SqliteRunSink(path)
    sink.record(_a_run("after", "2026-08-29T00:00:01+0000"))

    assert sink._broken is False
    sink.close()


def test_nothing_is_logged_for_a_store_that_only_needed_a_column(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Adding a column is the ordinary case, not an incident."""
    path = tmp_path / "runs.sqlite"
    _a_store_without(path, "runs", "session_id")

    sink = SqliteRunSink(path)
    with caplog.at_level(logging.DEBUG, logger="openstategraph.run_sinks"):
        sink.record(_a_run("after", "2026-08-29T00:00:01+0000"))
    sink.close()

    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "openstategraph.run_sinks"
    ] == []


class TestWhatEachKindOfFailureCosts:
    """The two facts `_broken` used to carry between them."""

    def test_a_file_that_will_not_open_says_runs_are_being_lost(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An ERROR that names the loss, not a warning that names a column.

        `the-boundary-nobody-checked/07` set that shape for one lost row; this
        is the loss of every row and may not be quieter.
        """
        path = tmp_path / "not-a-database"
        path.write_bytes(b"this is not a sqlite file, and never was\n" * 64)

        sink = SqliteRunSink(path)
        with caplog.at_level(logging.DEBUG, logger="openstategraph.run_sinks"):
            sink.record(_a_run("one", "2026-08-29T00:00:01+0000"))
        sink.close()

        loudest = max(
            record
            for record in caplog.records
            if record.name == "openstategraph.run_sinks"
        )
        assert loudest.levelno == logging.ERROR
        assert "runs list" in loudest.getMessage()

    def test_it_latches_rather_than_reopening_a_file_it_cannot_use(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A retry per record would be its own defect: one report, then silence."""
        path = tmp_path / "not-a-database"
        path.write_bytes(b"this is not a sqlite file, and never was\n" * 64)

        sink = SqliteRunSink(path)
        with caplog.at_level(logging.DEBUG, logger="openstategraph.run_sinks"):
            for index in range(4):
                sink.record(_a_run(f"n{index}", "2026-08-29T00:00:01+0000"))
        sink.close()

        assert sink._broken is True
        assert (
            len(
                [
                    record
                    for record in caplog.records
                    if record.name == "openstategraph.run_sinks"
                ]
            )
            == 1
        )

    def test_a_schema_this_build_could_not_finish_still_takes_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The other half of the split: an unbuildable index is not a lost run.

        A missing index costs speed; refusing every write costs the runs. The
        store is prepared once, said once, and used.
        """
        path = tmp_path / "runs.sqlite"
        first = SqliteRunSink(path)
        first.record(_a_run("before", "2026-08-29T00:00:00+0000"))
        first.close()

        monkeypatch.setattr(
            run_sinks,
            "_INDEXES",
            (*run_sinks._INDEXES, ("runs_nonsense", "runs", "no_such_column")),
        )
        sink = SqliteRunSink(path)
        with caplog.at_level(logging.DEBUG, logger="openstategraph.run_sinks"):
            sink.record(_a_run("after", "2026-08-29T00:00:01+0000"))
            sink.record(_a_run("later", "2026-08-29T00:00:02+0000"))
        sink.close()

        assert sink._broken is False
        assert _threads(path) == ["later", "after", "before"]
        said = [
            record
            for record in caplog.records
            if record.name == "openstategraph.run_sinks"
        ]
        assert len(said) == 1
        assert said[0].levelno == logging.ERROR
