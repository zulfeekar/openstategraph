"""`the-boundary-nobody-checked/02` — the history door takes an audience.

## The finding

`GET /api/threads/{thread_id}` took no audience and applied none, while
`api/threads.py` called itself *"a customer surface"* in as many words. Driven
against a real run — an agent, a real SQL tool, a real SQLite file — the
customer read came back carrying the tool's **name**, the **statement** it was
sent and the **rows** it returned, the per-superstep **usage**, and the whole
`tool_use` state channel that `api/audience.py` declares developer-only.

`memory-and-replay/38` had already found this door publishing machinery and
fixed one field — the ```suggestion fence. This is the second instance of the
same defect, which is why the fix here is a declaration rather than another
field.

## The mechanism, and why it is not a third spelling

The audience of a state channel was written down in two places already
(`api/audience.py`'s table, and the comments in `compile/state.py`), so a key
list in `api/threads.py` beside `_PRIVATE_PREFIXES` would have been a third.

**The channel carries its own audience instead.** `CUSTOMER_VISIBLE` is a
marker in the channel's own `Annotated[...]` metadata in `compile/state.py`,
and `customer_visible_channels()` reads it back off `RunState`. Unmarked means
developer-only, so a channel added tomorrow is refused to a customer by
default rather than published by default — the same direction
`audience.Audience` already takes for a request.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openstategraph.api.main import create_app

from conftest import RespondingModel

SQL = "SELECT Name FROM Artist WHERE ArtistId = 1"


class _CallsTheQueryTool(RespondingModel):
    """One tool call, then an answer — and it reports usage, like a provider."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        if any(getattr(m, "type", "") == "tool" for m in messages):
            reply = self._reply("The first artist is AC/DC.")
            reply.generations[0].message.usage_metadata = {
                "input_tokens": 11,
                "output_tokens": 7,
                "total_tokens": 18,
            }
            return reply
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "sql_query", "args": {"query": SQL}, "id": "c1"}
                        ],
                        usage_metadata={
                            "input_tokens": 9,
                            "output_tokens": 3,
                            "total_tokens": 12,
                        },
                    )
                )
            ]
        )


def _document() -> dict[str, Any]:
    def node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
        return {"id": node_id, "type": node_type, "data": data, "position": {"x": 0, "y": 0}}

    def edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
        return {
            "source": {"nodeId": src, "portId": src_port},
            "target": {"nodeId": dst, "portId": dst_port},
        }

    return {
        "version": 1,
        "name": "asks the database",
        "nodes": [
            node("in1", "input.text"),
            node("agent1", "agent.llm", systemPrompt="Answer from the database."),
            node("sql1", "tool.sql-query", database="pkg/data/music.sqlite"),
            node("out1", "output.formatted"),
        ],
        "edges": [
            edge("in1", "text", "agent1", "prompt"),
            edge("sql1", "tool", "agent1", "tools"),
            edge("agent1", "result", "out1", "result"),
        ],
    }


@pytest.fixture()
def workflows_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workflows"
    (root / "pkg" / "data").mkdir(parents=True)
    db = root / "pkg" / "data" / "music.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE Artist (ArtistId INTEGER, Name TEXT)")
        conn.executemany("INSERT INTO Artist VALUES (?, ?)", [(1, "AC/DC"), (2, "Accept")])
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    monkeypatch.setenv("OPENSTATEGRAPH_STATE_DIR", str(tmp_path / "state"))
    return root


@pytest.fixture()
def stored_run(monkeypatch: pytest.MonkeyPatch, workflows_root: Path) -> tuple[TestClient, str]:
    """A real finished run, read back through the door that stored it.

    Not a hand-built `ThreadStep`: the leak is in what the **checkpoint**
    holds, so a fixture that never ran a graph would be green on the broken
    behaviour (this ticket's own Done-when).
    """
    from openstategraph import chat_model as chat_model_module

    model = _CallsTheQueryTool([], default="The first artist is AC/DC.")
    monkeypatch.setattr(chat_model_module, "build_chat_model", lambda _name: model)
    client = TestClient(create_app())
    run = client.post(
        "/api/runs",
        json={
            "workflow": {"document": _document()},
            "question": "who is the first artist?",
            "session_id": "s1",
            "audience": "customer",
        },
    ).json()
    assert run["answer"].startswith("The first artist")
    return client, run["thread_id"]


def _history(client: TestClient, thread_id: str, audience: str | None = None) -> dict[str, Any]:
    query = f"?audience={audience}" if audience else ""
    response = client.get(f"/api/threads/{thread_id}{query}")
    assert response.status_code == 200, response.text
    return response.json()


class TestACustomerReadsTheirOwnRunAndNoMachinery:
    """The four things the sweep found riding this door."""

    def test_no_tool_name_arguments_or_result(self, stored_run) -> None:
        client, thread_id = stored_run
        history = _history(client, thread_id)
        assert [call for step in history["steps"] for call in step["tool_calls"]] == []

    def test_the_statement_and_its_rows_are_nowhere_in_the_body(self, stored_run) -> None:
        """Asserted over the whole payload, not per field: the same text rode
        `toolCalls`, `values["tool_use"]` and `values["messages"]` at once."""
        client, thread_id = stored_run
        body = json.dumps(_history(client, thread_id))
        assert SQL not in body
        assert "sql_query" not in body

    def test_no_usage(self, stored_run) -> None:
        """`docs/api.md` promises a customer run always reads `null`."""
        client, thread_id = stored_run
        assert all(step["tokens"] is None for step in _history(client, thread_id)["steps"])

    def test_no_developer_only_state_channel(self, stored_run) -> None:
        client, thread_id = stored_run
        seen = {key for step in _history(client, thread_id)["steps"] for key in step["values"]}
        assert "tool_use" not in seen
        assert "messages" not in seen
        assert seen <= {"answer", "question", "decisions", "routes", "outputs",
                        "nested_outputs", "attempts"}

    def test_the_channels_a_customer_run_publishes_are_still_here(self, stored_run) -> None:
        """A customer's history is the same *shape* as a customer's live run —
        refusing it wholesale was the other coherent answer and is not this
        one."""
        client, thread_id = stored_run
        seen = {key for step in _history(client, thread_id)["steps"] for key in step["values"]}
        assert {"answer", "question", "outputs"} <= seen
        assert _history(client, thread_id)["thread"]["question"] == "who is the first artist?"

    def test_the_channels_it_wrote_are_filtered_too(self, stored_run) -> None:
        """`wrote` names channels, and a name is the disclosure here."""
        client, thread_id = stored_run
        wrote = {name for step in _history(client, thread_id)["steps"] for name in step["wrote"]}
        assert "tool_use" not in wrote
        assert "messages" not in wrote


class TestADeveloperStillGetsTheWholeRun:
    """The door is not being made useless — it is being made honest."""

    def test_the_tool_call_is_reported_whole(self, stored_run) -> None:
        client, thread_id = stored_run
        calls = [call for step in _history(client, thread_id, "developer")["steps"]
                 for call in step["tool_calls"]]
        assert [call["name"] for call in calls] == ["sql_query"]
        assert SQL in calls[0]["arguments"]
        assert "AC/DC" in calls[0]["result"]

    def test_usage_is_reported(self, stored_run) -> None:
        client, thread_id = stored_run
        steps = _history(client, thread_id, "developer")["steps"]
        assert any(step["tokens"] for step in steps)

    def test_the_developer_only_channels_are_there(self, stored_run) -> None:
        client, thread_id = stored_run
        seen = {key for step in _history(client, thread_id, "developer")["steps"]
                for key in step["values"]}
        assert {"tool_use", "messages"} <= seen


class TestTheDeploymentCeilingCapsThisDoorToo:
    """`resolve()`, the same call the run doors make — not a second gate."""

    def test_a_developer_request_is_capped_to_customer(
        self, stored_run, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_AUDIENCE", "customer")
        client, thread_id = stored_run
        body = json.dumps(_history(client, thread_id, "developer"))
        assert SQL not in body

    def test_an_unrecognised_ceiling_fails_closed(
        self, stored_run, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_AUDIENCE", "custmoer")
        client, thread_id = stored_run
        body = json.dumps(_history(client, thread_id, "developer"))
        assert SQL not in body


class TestTheChannelCarriesItsOwnAudience:
    """One declaration, on the channel — `compile/state.py`, read back."""

    def test_the_customer_channels_are_the_ones_a_customer_run_publishes(self) -> None:
        from openstategraph.compile.state import customer_visible_channels

        assert customer_visible_channels() == frozenset(
            {"question", "answer", "decisions", "routes", "outputs", "nested_outputs",
             "attempts"}
        )

    def test_an_unmarked_channel_is_developer_only(self) -> None:
        """Fail closed: a channel added tomorrow is refused, not published."""
        from openstategraph.compile.state import RunState, customer_visible_channels

        visible = customer_visible_channels()
        for channel in ("tool_use", "redactions", "messages", "unmet_tools", "feedback",
                        "verdicts", "forced", "agent_files", "async_tasks",
                        "worker_results", "subtasks", "published"):
            assert channel in RunState.__annotations__
            assert channel not in visible

    def test_the_marker_never_displaces_a_reducer(self) -> None:
        """The one hazard of putting it in the metadata, pinned.

        LangGraph reads the reducer from `__metadata__[-1]`
        (`langgraph/graph/state.py::_is_field_binop`, checked against the
        installed version), so a marker appended *after* a reducer would
        silently turn a merged channel into a last-value one — the
        `InvalidUpdateError` class of bug, arriving through a security fix.
        """
        from langgraph.channels.binop import BinaryOperatorAggregate
        from langgraph.graph import StateGraph

        from openstategraph.compile.state import RunState

        channels = StateGraph(RunState).channels
        for name in ("outputs", "decisions", "tool_use", "redactions", "messages",
                     "worker_results", "nested_outputs", "routes"):
            assert isinstance(channels[name], BinaryOperatorAggregate), name


class TestTheDoorIsTheOnlyDoor:
    """The precedent for this fix's shape is this repo's own: one seam, plus a
    census that parses every module for anyone who bypassed it."""

    def test_only_the_thread_reader_builds_a_thread_step(self) -> None:
        root = Path(__file__).resolve().parents[1] / "openstategraph"
        offenders = [
            path.relative_to(root)
            for path in root.rglob("*.py")
            if path.name != "schemas.py"
            and path != root / "api" / "threads.py"
            and ("ThreadStep(" in path.read_text() or "ThreadHistoryResponse(" in path.read_text())
        ]
        assert offenders == [], f"a second history door: {offenders}"

    def test_reading_a_thread_asks_who_is_reading(self) -> None:
        """The signature carries the question, so a new caller has to answer
        it — and its default is the closed one."""
        import inspect

        from openstategraph.api.audience import Audience
        from openstategraph.api.threads import read_thread

        parameter = inspect.signature(read_thread).parameters["audience"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is Audience.CUSTOMER


class TestTheFenceIsStillStripped:
    """`memory-and-replay/38`'s fix is not undone by this one."""

    def test_a_suggestion_fence_never_survives_into_a_value(self) -> None:
        from openstategraph.api.threads import _text

        raw = 'here you go\n\n```suggestion\n{"nodeType": "tool.x", "attachTo": "a1"}\n```'
        assert "nodeType" not in _text(raw)


class TestTheBurstReaderHonoursTheColumnItStores:
    """`run_sinks.RunBurst.audience` is written *"so a reader can refuse"*, and
    `read_run_bursts` had no parameter to refuse with and no caller to notice.

    A required keyword rather than a default, because the whole finding is that
    the next replay door would inherit the refusal silently."""

    def _store(self, tmp_path: Path) -> Path:
        from openstategraph.api.burst_recorder import BurstRecorder
        from openstategraph.run_sinks import RunRecord, SqliteRunSink

        path = tmp_path / "runs.sqlite"
        sink = SqliteRunSink(path)
        for audience, thread in (("developer", "t-dev"), ("customer", "t-cus")):
            recorder = BurstRecorder(audience=audience)
            recorder.chunk(
                {"node": "agent1", "namespace": [], "block": "text", "kind": "model",
                 "seq": 1, "elapsedMs": 5, "content": f"{audience} text", "withheld": False}
            )
            sink.record(RunRecord(kind="run", thread_id=thread, bursts=recorder.bursts()))
        sink.close()
        return path

    def test_a_customer_reader_is_refused_a_developer_runs_bursts(self, tmp_path: Path) -> None:
        from openstategraph.run_sinks import read_run_bursts

        assert read_run_bursts(self._store(tmp_path), thread_id="t-dev", audience="customer") == []

    def test_a_customer_reader_still_gets_a_customer_run(self, tmp_path: Path) -> None:
        from openstategraph.run_sinks import read_run_bursts

        bursts = read_run_bursts(self._store(tmp_path), thread_id="t-cus", audience="customer")
        assert [burst.text for burst in bursts] == ["customer text"]

    def test_a_developer_reader_gets_both(self, tmp_path: Path) -> None:
        from openstategraph.run_sinks import read_run_bursts

        path = self._store(tmp_path)
        for thread in ("t-dev", "t-cus"):
            assert read_run_bursts(path, thread_id=thread, audience="developer")

    def test_the_reader_cannot_decline_to_answer_the_question(self) -> None:
        import inspect

        from openstategraph.run_sinks import read_run_bursts

        parameter = inspect.signature(read_run_bursts).parameters["audience"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty
