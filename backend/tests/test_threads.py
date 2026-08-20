"""Past runs: listing the checkpointer's threads and reading one back.

The gap this closes: identity (`thread_id`, `session_id`, `user_email`) has
ridden in `configurable` and been persisted into checkpoint metadata all
along, and every superstep of every run was already on disk — but nothing
could enumerate a thread or read one back, so "continue where we left off"
lived only in a browser's localStorage.

These tests write real checkpoints through a real compiled graph, because the
whole claim under test is *that the runtime's own storage already holds this*.
A hand-built fake saver would prove only that the module can read a fake.
"""

from __future__ import annotations

from typing import Any, TypedDict

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from openstategraph.api.main import create_app
from openstategraph.api.threads import list_threads, read_thread, savers_for


class _State(TypedDict, total=False):
    question: str
    answer: str
    outputs: dict[str, str]


def _graph() -> Any:
    builder: StateGraph = StateGraph(_State)
    builder.add_node("answer", lambda state: {"answer": f"re: {state['question']}"})
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder


def _failed_graph() -> Any:
    """One node writes the failure sentinel `node_failure_warnings` matches."""
    from openstategraph.compile.workflow_compiler import failure_marker

    def fail(state: _State) -> dict[str, Any]:
        return {
            "answer": "",
            "outputs": {"agent1": failure_marker("agent1", 'no credential — set X')},
        }

    builder: StateGraph = StateGraph(_State)
    builder.add_node("fail", fail)
    builder.add_edge(START, "fail")
    builder.add_edge("fail", END)
    return builder


def _paused_graph() -> Any:
    def wait(state: _State) -> dict[str, str]:
        decision = interrupt({"ask": "ok?"})
        return {"answer": str(decision)}

    builder: StateGraph = StateGraph(_State)
    builder.add_node("wait", wait)
    builder.add_edge(START, "wait")
    builder.add_edge("wait", END)
    return builder


def _run(
    saver: Any,
    thread_id: str,
    question: str = "how many tracks?",
    *,
    session_id: str = "s-1",
    user_email: str = "ada@example.com",
    workflow_slug: str = "chinook-assistant",
    builder: Any = None,
) -> None:
    graph = (builder or _graph()).compile(checkpointer=saver)
    graph.invoke(
        {"question": question, "answer": ""},
        {
            "configurable": {
                "thread_id": thread_id,
                "session_id": session_id,
                "user_email": user_email,
                "workflow_slug": workflow_slug,
            }
        },
    )


@pytest.fixture()
def saver() -> InMemorySaver:
    return InMemorySaver()


class TestListing:
    def test_a_finished_run_is_listed_with_the_identity_it_ran_under(
        self, saver: InMemorySaver
    ) -> None:
        _run(saver, "t-1")
        rows = list_threads([saver])
        assert len(rows) == 1
        row = rows[0]
        assert row.thread_id == "t-1"
        assert row.session_id == "s-1"
        assert row.user_email == "ada@example.com"
        assert row.workflow_slug == "chinook-assistant"
        assert row.question == "how many tracks?"
        assert row.answer == "re: how many tracks?"
        assert row.status == "finished"
        assert row.steps >= 2

    def test_a_run_whose_node_failed_is_marked_failed_not_just_finished(
        self, saver: InMemorySaver
    ) -> None:
        """production-ready/78: `outputs` carries the failure sentinel — history
        must say so, without repurposing `status`, which stays `finished`
        (this run is not paused at an interrupt)."""
        _run(saver, "t-failed", builder=_failed_graph())
        rows = list_threads([saver])
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "finished"
        assert row.failed is True

    def test_a_run_that_legitimately_answered_with_nothing_is_not_failed(
        self, saver: InMemorySaver
    ) -> None:
        """The trap named in the ticket: emptiness is not failure."""
        _run(saver, "t-empty")
        rows = list_threads([saver])
        assert rows[0].failed is False

    def test_nothing_run_means_nothing_listed(self, saver: InMemorySaver) -> None:
        assert list_threads([saver]) == []

    def test_threads_come_back_newest_first(self, saver: InMemorySaver) -> None:
        _run(saver, "t-old", "first")
        _run(saver, "t-new", "second")
        assert [row.thread_id for row in list_threads([saver])] == ["t-new", "t-old"]

    def test_one_row_per_thread_however_many_checkpoints_it_has(
        self, saver: InMemorySaver
    ) -> None:
        _run(saver, "t-1", "one")
        _run(saver, "t-1", "two")  # same thread, run again
        rows = list_threads([saver])
        assert len(rows) == 1
        # The latest checkpoint wins — a list showing the first answer of a
        # continued conversation would be actively misleading.
        assert rows[0].answer == "re: two"

    def test_the_limit_is_a_limit(self, saver: InMemorySaver) -> None:
        for index in range(5):
            _run(saver, f"t-{index}")
        assert len(list_threads([saver], limit=2)) == 2

    def test_it_reads_across_several_savers(self) -> None:
        # A workflow with `settings.checkpointer: "sqlite"` gets a file of its
        # own, so "the checkpointer" is plural and a listing must say so.
        first, second = InMemorySaver(), InMemorySaver()
        _run(first, "t-shared")
        _run(second, "t-own", workflow_slug="private")
        assert {row.thread_id for row in list_threads([first, second])} == {
            "t-shared",
            "t-own",
        }

    def test_the_same_saver_twice_is_read_once(self, saver: InMemorySaver) -> None:
        _run(saver, "t-1")
        assert len(list_threads([saver, saver])) == 1


class TestFilters:
    def test_by_workflow(self, saver: InMemorySaver) -> None:
        _run(saver, "t-a", workflow_slug="alpha")
        _run(saver, "t-b", workflow_slug="beta")
        rows = list_threads([saver], workflow_slug="beta")
        assert [row.thread_id for row in rows] == ["t-b"]

    def test_by_user_ignoring_case(self, saver: InMemorySaver) -> None:
        # Same rule as the memory namespace: `A@b.com` and `a@b.com` are one
        # person, and a history that disagrees with their memories is worse
        # than no history.
        _run(saver, "t-a", user_email="Ada@Example.com")
        _run(saver, "t-b", user_email="grace@example.com")
        rows = list_threads([saver], user_email="ada@EXAMPLE.com")
        assert [row.thread_id for row in rows] == ["t-a"]

    def test_by_session(self, saver: InMemorySaver) -> None:
        _run(saver, "t-a", session_id="morning")
        _run(saver, "t-b", session_id="evening")
        rows = list_threads([saver], session_id="evening")
        assert [row.thread_id for row in rows] == ["t-b"]


class TestPausedRuns:
    def test_a_run_waiting_at_an_interrupt_says_paused(self, saver: InMemorySaver) -> None:
        # The one status that means something actionable: a paused thread is
        # what `POST /api/runs/resume` can continue.
        _run(saver, "t-wait", builder=_paused_graph())
        assert list_threads([saver])[0].status == "paused"


class TestReadingOneBack:
    def test_the_steps_read_oldest_first(self, saver: InMemorySaver) -> None:
        _run(saver, "t-1")
        history = read_thread([saver], "t-1")
        assert history is not None
        assert history.thread.thread_id == "t-1"
        assert [step.step for step in history.steps] == sorted(
            step.step for step in history.steps
        )
        assert history.steps[0].source == "input"
        assert history.steps[-1].values["answer"] == "re: how many tracks?"

    def test_an_unknown_thread_is_absent_not_an_error(self, saver: InMemorySaver) -> None:
        assert read_thread([saver], "never-ran") is None

    def test_scheduler_bookkeeping_is_not_part_of_the_story(
        self, saver: InMemorySaver
    ) -> None:
        _run(saver, "t-1")
        history = read_thread([saver], "t-1")
        assert history is not None
        keys = {key for step in history.steps for key in step.values}
        assert not [key for key in keys if key.startswith(("__", "branch:"))]
        assert "question" in keys

    def test_a_huge_value_is_capped_rather_than_streamed_whole(
        self, saver: InMemorySaver
    ) -> None:
        _run(saver, "t-1", "x" * 20_000)
        history = read_thread([saver], "t-1")
        assert history is not None
        rendered = history.steps[-1].values["question"]
        assert len(rendered) < 20_000
        assert rendered.endswith("chars)")

    def test_reading_does_not_re_execute_the_run(self, saver: InMemorySaver) -> None:
        # The guarantee that makes this safe to expose at all: a past run that
        # sent an email must not send it again because someone looked at it.
        calls: list[str] = []

        def side_effect(state: _State) -> dict[str, str]:
            calls.append(state["question"])
            return {"answer": "sent"}

        builder: StateGraph = StateGraph(_State)
        builder.add_node("send", side_effect)
        builder.add_edge(START, "send")
        builder.add_edge("send", END)
        _run(saver, "t-1", builder=builder)
        assert len(calls) == 1

        read_thread([saver], "t-1")
        list_threads([saver])
        assert len(calls) == 1


class TestSaverSelection:
    def test_a_slug_nobody_saved_still_lists_the_shared_saver(self, tmp_path: Any) -> None:
        app = create_app(workflows_root=tmp_path)
        services = app.state.services
        assert savers_for(services, "no-such-workflow") == [services.checkpointer]


class TestTheEndpoints:
    @staticmethod
    def _client(tmp_path: Any) -> TestClient:
        return TestClient(create_app(workflows_root=tmp_path))

    def test_it_lists_the_threads_the_running_process_stored(self, tmp_path: Any) -> None:
        client = self._client(tmp_path)
        _run(client.app.state.services.checkpointer, "t-1")  # type: ignore[attr-defined]

        response = client.get("/api/threads")
        assert response.status_code == 200
        threads = response.json()["threads"]
        assert [row["thread_id"] for row in threads] == ["t-1"]
        assert threads[0]["user_email"] == "ada@example.com"

    def test_it_filters_by_query_string(self, tmp_path: Any) -> None:
        client = self._client(tmp_path)
        saver = client.app.state.services.checkpointer  # type: ignore[attr-defined]
        _run(saver, "t-a", user_email="ada@example.com")
        _run(saver, "t-b", user_email="grace@example.com")

        response = client.get("/api/threads", params={"user_email": "grace@example.com"})
        assert [row["thread_id"] for row in response.json()["threads"]] == ["t-b"]

    def test_one_thread_reads_back_as_its_steps(self, tmp_path: Any) -> None:
        client = self._client(tmp_path)
        _run(client.app.state.services.checkpointer, "t-1")  # type: ignore[attr-defined]

        response = client.get("/api/threads/t-1")
        assert response.status_code == 200
        body = response.json()
        assert body["thread"]["thread_id"] == "t-1"
        assert body["steps"][-1]["values"]["answer"] == "re: how many tracks?"

    def test_an_unknown_thread_is_a_404(self, tmp_path: Any) -> None:
        client = self._client(tmp_path)
        assert client.get("/api/threads/never-ran").status_code == 404
