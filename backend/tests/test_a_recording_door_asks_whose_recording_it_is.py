"""The door onto the stored recordings, and the refusal it inherits.

`memory-and-replay` 71 and 72.

## The gap this closes, and the one it found on the way

`47` stored every chunk of every run's output with the offset it arrived at,
and `52` built a playhead that can only honestly move over offsets somebody
measured. Between the two there was no door: `read_runs` and
`read_run_bursts` are Python, `openstategraph runs list` is a terminal, and
`burst` appeared nowhere in `docs/openapi.json` — which is `RunDock`'s own
recorded reason for leaving the recorded cadence out of the port (`60`).

The finding is the second one. `read_run_bursts` takes **`audience` as a
required keyword** and says exactly why: *"a developer run's bursts carry
developer content, and `38` already found what happens when a replay door
forgets to ask."* `read_runs(with_bursts=True)` reaches the same table through
`_attach_bursts` and had no such parameter — so the *other* reader of the
cadence had the gate the first one was given, and the first door built on it
would have inherited a refusal nothing told it about. Nothing leaked: the one
caller is `openstategraph runs export`, which is a local operator exporting
their own machine. The next caller was this route.

So `with_bursts` now costs an `audience` at the call site, and asking for the
cadence without saying whose is an error rather than a default.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.run_sinks import (  # noqa: E402
    RunBurst,
    RunRecord,
    SqliteRunSink,
    read_runs,
)


def _store(tmp_path: Path) -> Path:
    """Two runs, one recorded on each audience's stream."""
    path = tmp_path / "runs.sqlite"
    sink = SqliteRunSink(path)
    sink.record(
        RunRecord(
            at="2026-08-30T09:00:00+0000",
            workflow_slug="chinook-assistant",
            thread_id="t-dev",
            session_id="s-1",
            question="Which genre earned most?",
            answer="Rock — $826.65",
            bursts=[RunBurst(node="agent", kind="model", text="Rock", audience="developer")],
        )
    )
    sink.record(
        RunRecord(
            at="2026-08-30T09:01:00+0000",
            workflow_slug="chinook-assistant",
            thread_id="t-cus",
            session_id="s-1",
            question="And the runner-up?",
            answer="Latin",
            bursts=[RunBurst(node="agent", kind="model", text="Latin", audience="customer")],
        )
    )
    sink.close()
    return path


class TestTheCadenceReaderAsksWhoIsReading:
    def test_asking_for_bursts_without_an_audience_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="audience"):
            read_runs(_store(tmp_path), with_bursts=True)

    def test_the_listing_itself_still_needs_no_audience(self, tmp_path: Path) -> None:
        """A row's own columns are not the customer's text — only the cadence is."""
        rows = read_runs(_store(tmp_path))
        assert [row.thread_id for row in rows] == ["t-cus", "t-dev"]
        assert all(row.bursts == [] for row in rows)

    def test_a_developer_reads_every_recording(self, tmp_path: Path) -> None:
        rows = read_runs(_store(tmp_path), with_bursts=True, audience="developer")
        assert sorted(len(row.bursts) for row in rows) == [1, 1]

    def test_a_customer_reads_only_a_customers_own_stream(self, tmp_path: Path) -> None:
        rows = {
            row.thread_id: row
            for row in read_runs(_store(tmp_path), with_bursts=True, audience="customer")
        }
        assert [burst.text for burst in rows["t-cus"].bursts] == ["Latin"]
        # The run is still listed. It is the *recording* that is refused, and a
        # row with no cadence is the same absence an old store already answers
        # with — never a run invented to have taken no time.
        assert rows["t-dev"].bursts == []
