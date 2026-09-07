"""`GET /api/runs/recorded` — the recordings, over HTTP at last.

`memory-and-replay` 72. `47` stored the cadence, `52` built the playhead, and
`RunDock` recorded in its own docstring why the two never met: *"the store
keeps the cadence and the reader is Python-level — no HTTP route, and `burst`
appears nowhere in `docs/openapi.json`."* This is that route.

## Two doors, and the identity that already existed

A listing that carried every run's cadence would pay 5–8 KiB per row to render
a table, which is the argument `read_runs(with_bursts=False)` already makes. So
the listing is rows, and a **thread** is what opens. That needs no new
identity: `(workflow_slug, thread_id)` is the store's own key, the pair the
editor already treats as conversation identity, and a thread holds every turn
of one conversation — which is exactly the grain a reader picks a recording
from.

**No run id is minted, and that is deliberate.** The store's own name for a row
is a sqlite `rowid`, which is storage rather than a fact about the run and
means nothing to the `JsonlRunSink` writing the same record; `at` is second
precision and two turns can share it. A turn is identified by *the thread it is
in and its position in that thread*, which is what a conversation is.

## The order is the index's, never the reader's

`the-cost-of-one-more/11` made *newest first* a derived indexed sort key
(`CHRONOLOGICAL`) because `at` is local wall clock with an offset and sorting
it as text is not sorting it by time. This route does not re-sort: it hands
back the order `read_runs` produced, and the grouping a client does over it
preserves that order rather than replacing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.api.main import create_app  # noqa: E402
from openstategraph.run_sinks import (  # noqa: E402
    RUN_STORE_PATH_ENV,
    RunBurst,
    RunRecord,
    SqliteRunSink,
)


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Five turns: two workflows, two sittings, three conversations."""
    path = tmp_path / "runs.sqlite"
    sink = SqliteRunSink(path)
    turns = (
        ("chinook-assistant", "s-1", "t-a", "09:00:00", "Which genre earned most?", "Rock"),
        ("chinook-assistant", "s-1", "t-a", "09:00:30", "And the runner-up?", "Latin"),
        ("chinook-assistant", "s-1", "t-b", "09:02:00", "How many tracks?", "3503"),
        ("stress-review", "s-2", "t-c", "09:05:00", "Review this", "Looks fine"),
        # No sitting at all — the MCP door mints none, and an empty cell means
        # *this run had no sitting*, never *nobody wrote one down*.
        ("stress-review", "", "t-d", "09:06:00", "Review that", "Also fine"),
    )
    for slug, session, thread, clock, question, answer in turns:
        sink.record(
            RunRecord(
                at=f"2026-08-30T{clock}+0000",
                workflow_slug=slug,
                thread_id=thread,
                session_id=session,
                question=question,
                answer=answer,
                seconds=1.5,
                usage={"gpt-oss:120b-cloud": {"total_tokens": 40}},
                bursts=[
                    RunBurst(
                        node="agent",
                        kind="model",
                        block="text",
                        first_ms=100,
                        last_ms=900,
                        chunks=4,
                        chars=len(answer),
                        text=answer,
                        audience="developer",
                    ),
                ],
            )
        )
    sink.close()
    monkeypatch.setenv(RUN_STORE_PATH_ENV, str(path))
    return path


@pytest.fixture()
def client(store: Path, tmp_path: Path) -> TestClient:
    return TestClient(create_app(workflows_root=tmp_path / "workflows"))


class TestTheListing:
    def test_it_lists_every_recorded_run_newest_first(self, client: TestClient) -> None:
        body = client.get("/api/runs/recorded").json()
        assert [run["question"] for run in body["runs"]] == [
            "Review that",
            "Review this",
            "How many tracks?",
            "And the runner-up?",
            "Which genre earned most?",
        ]

    def test_a_row_carries_the_levels_that_exist(self, client: TestClient) -> None:
        newest = client.get("/api/runs/recorded").json()["runs"][0]
        assert newest["workflowSlug"] == "stress-review"
        assert newest["threadId"] == "t-d"
        # Empty, and it stays empty: an absent sitting is a fact about the door
        # the run came through, not a hole to fill with the thread's name.
        assert newest["sessionId"] == ""
        # `null`, because this listing was read as a customer. `[]` would mean
        # *no model was called*, and the two are different claims.
        assert newest["usage"] is None

    def test_a_developer_is_told_what_each_model_cost(self, client: TestClient) -> None:
        """Per model, never one summed integer: *which node cost what* is only
        answerable while they are apart."""
        newest = client.get("/api/runs/recorded?audience=developer").json()["runs"][0]
        assert newest["usage"] == [
            {
                "model": "gpt-oss:120b-cloud",
                "inputTokens": 0,
                "outputTokens": 0,
                "totalTokens": 40,
            }
        ]

    def test_the_listing_costs_no_cadence(self, client: TestClient) -> None:
        """A table of runs pays for a table of runs. `read_runs`' own argument."""
        assert all(run["bursts"] == [] for run in client.get("/api/runs/recorded").json()["runs"])

    def test_it_narrows_to_one_workflow(self, client: TestClient) -> None:
        body = client.get("/api/runs/recorded?workflow_slug=stress-review").json()
        assert {run["workflowSlug"] for run in body["runs"]} == {"stress-review"}

    def test_a_store_that_was_never_written_is_not_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(RUN_STORE_PATH_ENV, str(tmp_path / "nothing.sqlite"))
        with TestClient(create_app(workflows_root=tmp_path / "workflows")) as fresh:
            assert fresh.get("/api/runs/recorded").json() == {"runs": []}


class TestOneThreadsRecordings:
    def test_a_thread_opens_with_its_turns_in_the_order_they_happened(
        self, client: TestClient
    ) -> None:
        """Oldest first here, and newest first in the listing, on purpose: a
        list is browsed from the newest and a conversation is read from its
        beginning."""
        body = client.get("/api/runs/recorded/t-a?audience=developer").json()
        assert [run["question"] for run in body["runs"]] == [
            "Which genre earned most?",
            "And the runner-up?",
        ]

    def test_each_turn_carries_its_own_recording(self, client: TestClient) -> None:
        runs = client.get("/api/runs/recorded/t-a?audience=developer").json()["runs"]
        assert [[burst["text"] for burst in run["bursts"]] for runs_ in [runs] for run in runs_] == [
            ["Rock"],
            ["Latin"],
        ]

    def test_a_burst_says_when_it_started_and_when_it_stopped(
        self, client: TestClient
    ) -> None:
        burst = client.get("/api/runs/recorded/t-a?audience=developer").json()["runs"][0][
            "bursts"
        ][0]
        assert (burst["firstMs"], burst["lastMs"]) == (100, 900)
        assert (burst["node"], burst["kind"], burst["block"]) == ("agent", "model", "text")
        assert burst["chunks"] == 4

    def test_a_customer_is_refused_a_developer_runs_recording(
        self, client: TestClient
    ) -> None:
        """The default, and `the-boundary-nobody-checked/02`'s rule reaching
        the door built on it. The turn is still listed; its recording is not."""
        runs = client.get("/api/runs/recorded/t-a").json()["runs"]
        assert [run["question"] for run in runs] == [
            "Which genre earned most?",
            "And the runner-up?",
        ]
        assert all(run["bursts"] == [] for run in runs)

    def test_a_thread_nothing_recorded_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/runs/recorded/t-nothing").status_code == 404
