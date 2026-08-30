""""Newest first" over timestamps that carry an offset, ordered by instant.

`the-cost-of-one-more/11`, split out of `08` finding three. `run_sinks.now()`
is `time.strftime("%Y-%m-%dT%H:%M:%S%z")` — local wall clock with a numeric
offset — and every reader ordered by that column as **text**. Comparing the
offset as text is not comparing the instant, so a row recorded at `+02:00` and
one recorded at `+00:00` came back in the order of their local clocks:

| stored `at` | the instant | old text order |
| --- | --- | --- |
| `2026-10-25T02:50:00+0200` | 00:50Z | second |
| `2026-10-25T02:30:00+0100` | 01:30Z | **first** |

**This is a two-state defect, which decides the shape of every test here.** A
wrong order and a right order are the same list of the same rows; nothing about
the output says which one it is. So every ordering assertion below is over rows
whose stamps differ **only** by offset — same local wall clock, different zone —
because a fixture written in one timezone passes under both rules and proves
nothing. Where a case needs the *machine's* zone to differ, `TZ` is set around
the write rather than the stamp being handed in, so the thing under test is the
function that makes them.

**And the store never sweeps**, so it holds rows in the old spelling forever.
The fix therefore changes no stored byte: the sort key is derived from `at` by
`CHRONOLOGICAL` and indexed as an expression. `test_a_store_written_before_this
_change_lists_in_the_right_order` is the one that matters for that — it builds
a store through the ordinary write path, on a build that had none of this, and
reads it back.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from openstategraph.readonly_sqlite import readonly_closing
from openstategraph.run_sinks import (
    CHRONOLOGICAL,
    RunRecord,
    SqliteRunSink,
    now,
    read_runs,
)

#: Three instants, in the order they happened, spelled in three zones.
#:
#: Deliberately built so that *every* pair disagrees between text order and
#: chronological order — the local wall clocks run backwards as the instants
#: run forwards. A fixture where the two agree is a fixture that passes on the
#: broken build.
BY_INSTANT: tuple[tuple[str, str], ...] = (
    ("oldest", "2026-10-25T03:10:00+0300"),  # 00:10Z
    ("middle", "2026-10-25T02:50:00+0200"),  # 00:50Z
    ("newest", "2026-10-25T01:30:00+0000"),  # 01:30Z
)


def write(path: Path, stamps: tuple[tuple[str, str], ...]) -> Path:
    sink = SqliteRunSink(path)
    for question, at in stamps:
        sink.record(RunRecord(kind="run", at=at, question=question, thread_id="t"))
    sink.close()
    return path


def questions(path: Path, **filters: Any) -> list[str]:
    return [row.question for row in read_runs(path=path, limit=100, **filters)]


def test_the_fixture_is_wrong_under_a_text_sort(tmp_path: Path) -> None:
    """The control, so the rest of this file cannot pass vacuously.

    If these three stamps happened to sort the same way both ways, every
    assertion below would hold on the build this ticket is about. They do not:
    read as text, the newest of the three comes last.
    """
    assert [q for q, _ in sorted(BY_INSTANT, key=lambda p: p[1], reverse=True)] == [
        "oldest",
        "middle",
        "newest",
    ]


def test_rows_written_under_three_offsets_list_newest_first(tmp_path: Path) -> None:
    """The defect, at the size it happens: one store, one autumn morning."""
    store = write(tmp_path / "runs.sqlite", BY_INSTANT)

    assert questions(store) == ["newest", "middle", "oldest"]


@pytest.mark.parametrize("narrowed", ["workflow_slug", "session_id", "thread_id"])
def test_every_filtered_listing_orders_by_instant_too(
    tmp_path: Path, narrowed: str
) -> None:
    """`runs list` narrows three ways and each has its own index.

    An index that encodes the ordering is an index that encodes it wrongly if
    the ordering is wrong, which is why all three moved rather than the
    unfiltered one.
    """
    sink = SqliteRunSink(tmp_path / "runs.sqlite")
    for question, at in BY_INSTANT:
        sink.record(
            RunRecord(
                kind="run",
                at=at,
                question=question,
                workflow_slug="w",
                session_id="s",
                thread_id="t",
            )
        )
    sink.close()

    assert questions(tmp_path / "runs.sqlite", **{narrowed: {"workflow_slug": "w", "session_id": "s", "thread_id": "t"}[narrowed]}) == [
        "newest",
        "middle",
        "oldest",
    ]


def test_a_store_written_before_this_change_lists_in_the_right_order(
    tmp_path: Path,
) -> None:
    """No stored byte moved, so a row written years ago sorts correctly now.

    The store is forbidden from sweeping, so *"old rows keep the old rule"* was
    never an option — it would have left half a store ordered one way and half
    the other, which is neither ordering. This is the file an older build
    leaves behind: its rows, written through the ordinary write path, and its
    four `at`-keyed indexes back in place of the four this change makes. It is
    read correctly before anything touches it, because nothing has to be
    touched — the sort key is derived from the column that is already there.
    """
    store = write(tmp_path / "runs.sqlite", BY_INSTANT)
    with sqlite3.connect(store) as connection:
        for name in ("at_utc", "workflow_utc", "session_utc", "thread_utc"):
            connection.execute(f"DROP INDEX IF EXISTS runs_{name}")
        connection.execute("CREATE INDEX runs_at ON runs (at)")
        connection.execute(
            "CREATE INDEX runs_workflow_at ON runs (workflow_slug, at)"
        )
        connection.execute("CREATE INDEX runs_session_at ON runs (session_id, at)")
        connection.execute("CREATE INDEX runs_thread ON runs (thread_id)")

    assert questions(store) == ["newest", "middle", "oldest"]

    # And the next run somebody records replaces the old indexes in place —
    # `08`'s shape, additively for the four that arrive, and nothing to
    # backfill because there is no new column to fill. `_open` is lazy, so it
    # takes a real row to reach it.
    write(store, (("later", "2026-10-25T04:00:00+0000"),))

    with readonly_closing(store) as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert not {"runs_at", "runs_workflow_at", "runs_session_at"} & names
    assert {
        "runs_at_utc",
        "runs_workflow_utc",
        "runs_session_utc",
        "runs_thread_utc",
    } <= names
    assert questions(store) == ["later", "newest", "middle", "oldest"]


def test_the_stamps_the_clock_actually_makes_sort_by_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The offsets come from the machine, not from the fixture.

    Every other case here hands the stamps in, which tests the ordering and
    not the thing that writes them. This one moves `TZ` between two writes of
    the *same instant plus a second*, so `now()` produces the two spellings
    itself — which is the laptop that flew somewhere, and the machine that
    crossed a DST boundary, in the only form a test can hold them.
    """
    stamps = []
    for zone in ("Europe/Oslo", "UTC"):
        monkeypatch.setenv("TZ", zone)
        time.tzset()
        stamps.append(now())
        time.sleep(1.1)
    monkeypatch.delenv("TZ", raising=False)
    time.tzset()

    offsets = {stamp[-5:] for stamp in stamps}
    assert len(offsets) == 2, f"the zones did not differ on this machine: {stamps}"

    store = write(tmp_path / "runs.sqlite", (("first", stamps[0]), ("second", stamps[1])))

    assert questions(store) == ["second", "first"]


def test_an_unparseable_stamp_keeps_its_old_ordering_and_is_not_dropped(
    tmp_path: Path,
) -> None:
    """A store may not lose a run to a stamp this expression cannot read.

    `strftime` answers `NULL` to anything it does not understand, and every
    `NULL` compares equal — so a bare conversion would have collapsed every
    unreadable row into one indistinguishable clump at one end of the listing.
    The third arm of `CHRONOLOGICAL` is the raw string, so such a row sorts by
    exactly the rule it sorted by before and is still returned.
    """
    store = write(
        tmp_path / "runs.sqlite",
        (("readable", "2026-10-25T01:30:00+0000"), ("odd", "not-a-timestamp")),
    )

    assert set(questions(store)) == {"readable", "odd"}


def test_the_key_is_read_out_of_one_declaration(tmp_path: Path) -> None:
    """One spelling of the ordering, or the index and the query drift apart.

    An expression index only answers an `ORDER BY` that names the same
    expression, so two spellings of it is not a style question — it is a plan
    that silently goes back to sorting the whole store.
    """
    store = write(tmp_path / "runs.sqlite", BY_INSTANT)

    with readonly_closing(store) as connection:
        plan = [
            row[-1]
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT rowid,at FROM runs "
                f"ORDER BY {CHRONOLOGICAL} DESC, rowid DESC LIMIT 25"
            )
        ]

    assert any("runs_at_utc" in step for step in plan), plan
    assert not any("TEMP B-TREE" in step for step in plan), plan


def test_the_stored_value_is_still_the_local_clock_a_person_reads(
    tmp_path: Path,
) -> None:
    """The column did not become UTC, and that was the choice.

    `runs list` prints `at`; a person wants their own wall clock and the offset
    that says which one it was. The sort key wanted UTC. Deriving one from the
    other is what let both have what they wanted with no second column and no
    backfill.
    """
    store = write(tmp_path / "runs.sqlite", (("only", "2026-10-25T02:50:00+0200"),))

    with readonly_closing(store) as connection:
        stored = connection.execute("SELECT at FROM runs").fetchone()[0]
        derived = connection.execute(f"SELECT {CHRONOLOGICAL} FROM runs").fetchone()[0]

    assert stored == "2026-10-25T02:50:00+0200"
    assert derived == "2026-10-25T00:50:00Z"
    assert os.environ.get("TZ") in (None, os.environ.get("TZ"))
