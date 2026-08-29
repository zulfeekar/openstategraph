"""`one-chinook-honest/30` — a run records the statements it executed.

## The gap

Neither `/api/runs` nor the SSE `done` frame exposed the statement an agent
sent. Two correctness diagnoses in one day (`launch-readiness/116` and the
Persian Gulf triple) had to reconstruct the queries **from the model's own
prose about what it did** — which is exactly the artifact that cannot be
trusted when the model got it wrong. The instrument agreed with the thing it
was there to check.

## What `165` already gave, and what it did not

`tool_report` records the exchange under `tool_use[node]["queries"]` — added
because `_agent` returns no `messages`, so every gate reading
`state["messages"]` was blind on the agent rail. That record is **graph
state**: `counted_rows`, `grounded_numbers` and `table_coverage` read it, and
nothing publishes it. A run could be *judged* by what it executed and could
not be *asked*.

So this ticket is a transport, plus the two things the record was missing for a
reader rather than for a gate:

- **which tool ran it.** A gate asks "was this query answered"; a person asks
  "what did this tool actually do", and one exchange with no tool on it cannot
  answer the second.
- **whether the result is whole.** `155` caps a recorded result at 2 000
  characters, so a long payload is stored as text cut mid-string. A cut result
  and a short result rendered identically, which is this map's own failure
  shape. The **statement is never capped** — it is the evidence.

## The general case, argued rather than narrowed

"What did this tool actually do" is not a SQL question, so the published row is
`{node, tool, statement, result}` and says `statement`, not `sql`. What stays
narrow is what may *enter* it: only an argument a recogniser accepted as a
statement — today `looks_like_sql_query`, by shape and never by tool name. A
second recogniser joins by naming itself, with no change to this channel, the
schema, or any client.

That narrowness is also the credential answer. The record carries **one
argument**, the one recognised as a statement, and never the argument map — so
an MCP tool's `connection_string`, `headers` or `token` argument is not
recorded at all, rather than recorded and then scrubbed. Scrubbing runs on top
of that, for a credential embedded inside a statement.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openstategraph.api.main import create_app
from openstategraph.compile.node_runtime import QUERY_RESULT_RECORD_CAP, tool_report
from openstategraph.executed_statements import scrubbed, statements_executed

from conftest import RespondingModel

SQL = "SELECT Name FROM Artist WHERE ArtistId = 1"


def _messages(result: str = '{"rows": [{"Name": "AC/DC"}]}') -> list[Any]:
    return [
        AIMessage(content="", tool_calls=[{"name": "run_query", "args": {"sql": SQL}, "id": "c1"}]),
        ToolMessage(content=result, tool_call_id="c1", name="run_query"),
    ]


class TestTheRecordNamesItsTool:
    """`165`'s row said *what* ran and not *who* ran it."""

    def test_the_exchange_carries_the_tool_that_answered(self) -> None:
        row = tool_report("agent1", _messages(), ["run_query"])["tool_use"]["agent1"]
        assert row["queries"][0]["tool"] == "run_query"

    def test_the_statement_and_its_answer_are_still_there(self) -> None:
        row = tool_report("agent1", _messages(), ["run_query"])["tool_use"]["agent1"]
        assert row["queries"][0]["sql"] == SQL
        assert row["queries"][0]["result"] == '{"rows": [{"Name": "AC/DC"}]}'


class TestACutResultSaysSo:
    """A result that ended and a result the cap took must not look the same."""

    def test_a_short_result_is_not_marked(self) -> None:
        row = tool_report("agent1", _messages(), ["run_query"])["tool_use"]["agent1"]
        assert "truncated" not in row["queries"][0]

    def test_a_long_result_is_marked_and_cut(self) -> None:
        long = "x" * (QUERY_RESULT_RECORD_CAP + 500)
        row = tool_report("agent1", _messages(long), ["run_query"])["tool_use"]["agent1"]
        exchange = row["queries"][0]
        assert exchange["truncated"] is True
        assert len(exchange["result"]) == QUERY_RESULT_RECORD_CAP

    def test_the_statement_itself_is_never_cut(self) -> None:
        """The cap is on the answer. The statement is the evidence."""
        long_sql = "SELECT c FROM t WHERE c IN (" + ", ".join(str(i) for i in range(900)) + ")"
        messages = [
            AIMessage(
                content="", tool_calls=[{"name": "run_query", "args": {"sql": long_sql}, "id": "c1"}]
            ),
            ToolMessage(content="ok", tool_call_id="c1", name="run_query"),
        ]
        row = tool_report("agent1", messages, ["run_query"])["tool_use"]["agent1"]
        assert row["queries"][0]["sql"] == long_sql


class TestTheFlattenedRecord:
    def test_every_node_reports_its_own_statements(self) -> None:
        tool_use = {
            "agent-a": {"bound": [], "ran": [], "queries": [{"sql": SQL, "tool": "run_query", "result": "1"}]},
            "agent-b": {"bound": [], "ran": [], "queries": [{"sql": "SELECT 2 FROM t", "tool": "warehouse", "result": "2"}]},
        }
        rows = statements_executed(tool_use)
        assert [(r["node"], r["tool"], r["statement"]) for r in rows] == [
            ("agent-a", "run_query", SQL),
            ("agent-b", "warehouse", "SELECT 2 FROM t"),
        ]

    def test_a_run_that_executed_nothing_reports_nothing(self) -> None:
        assert statements_executed({"agent-a": {"bound": ["x"], "ran": ["x"]}}) == []

    def test_a_shape_it_has_never_seen_is_refused_quietly(self) -> None:
        """Read from a checkpoint a mounted child or an older release wrote."""
        assert statements_executed(None) == []
        assert statements_executed({"a": "not a row"}) == []
        assert statements_executed({"a": {"queries": ["not an exchange"]}}) == []

    def test_a_cut_result_is_published_as_cut(self) -> None:
        rows = statements_executed(
            {"a": {"queries": [{"sql": SQL, "tool": "t", "result": "x", "truncated": True}]}}
        )
        assert rows[0]["truncated"] is True

    def test_an_uncut_result_says_so_rather_than_staying_silent(self) -> None:
        """Present on every row: a reader deciding whether to trust a payload
        must not have to know that absence means whole."""
        rows = statements_executed({"a": {"queries": [{"sql": SQL, "tool": "t", "result": "x"}]}})
        assert rows[0]["truncated"] is False


class TestNoCredentialCanAppear:
    """A statement may embed values. It may never publish a credential."""

    def test_a_dsn_password_is_removed(self) -> None:
        text = "SELECT 1 FROM t -- postgresql://admin:hunter2@db.internal:5432/warehouse"
        assert "hunter2" not in scrubbed(text)

    def test_a_keyword_dsn_password_is_removed(self) -> None:
        assert "hunter2" not in scrubbed("host=db password=hunter2 dbname=w")

    def test_an_odbc_pwd_is_removed(self) -> None:
        assert "hunter2" not in scrubbed("Driver={ODBC};Server=x;UID=me;PWD=hunter2;")

    def test_a_bearer_token_is_removed(self) -> None:
        assert "abc.def.ghi" not in scrubbed("Authorization: Bearer abc.def.ghi")

    def test_a_key_shaped_value_is_removed(self) -> None:
        for secret in ("sk-livekey123456", "ghp_abcdefghijklmno", "AKIAIOSFODNN7EXAMPLE"):
            assert secret not in scrubbed(f"SELECT 1 FROM t WHERE k = '{secret}'")

    def test_the_scrub_says_where_it_acted(self) -> None:
        """Silent removal is the failure this map is named after."""
        assert "[redacted]" in scrubbed("host=db password=hunter2")

    def test_an_ordinary_statement_is_left_exactly_alone(self) -> None:
        """The narrowness is the safety, and it is the part that regresses."""
        for statement in (
            SQL,
            "SELECT COUNT(*) FROM area_counts WHERE day >= '2026-01-01'",
            "SELECT port, SUM(barrels) FROM cargoflow_latest "
            "WHERE shipping_region_v2 = 'Middle East Gulf (MEG)' GROUP BY port",
            "SELECT secret_ingredient FROM recipes WHERE token_count > 3",
        ):
            assert scrubbed(statement) == statement

    def test_the_flattened_record_is_scrubbed(self) -> None:
        rows = statements_executed(
            {"a": {"queries": [{"sql": "SELECT 1 FROM t -- PWD=hunter2", "tool": "t", "result": "PWD=hunter2"}]}}
        )
        assert "hunter2" not in rows[0]["statement"]
        assert "hunter2" not in rows[0]["result"]


# ------------------------------------------------------------------ #
# The composition, over the real doors
# ------------------------------------------------------------------ #
#
# Not a unit test on the flattener. This week's lesson, six times over, is that
# a test one layer up passes while the composition is wrong — so this drives a
# real agent, calling a real tool, against a real SQLite file, through both
# endpoints a client can reach.


ROWS = [("AC/DC",), ("Accept",)]


@pytest.fixture()
def workflows_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workflows"
    (root / "pkg" / "data").mkdir(parents=True)
    db = root / "pkg" / "data" / "music.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE Artist (ArtistId INTEGER, Name TEXT)")
        conn.executemany("INSERT INTO Artist VALUES (?, ?)", [(1, "AC/DC"), (2, "Accept")])
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    return root


class _CallsTheQueryTool(RespondingModel):
    """One tool call, then an answer — the shape a live agent produces."""

    called: bool = False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        if any(getattr(m, "type", "") == "tool" for m in messages):
            return self._reply("The first artist is AC/DC.")
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[{"name": "sql_query", "args": {"query": SQL}, "id": "c1"}],
                    )
                )
            ]
        )

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        """The inherited one replays a queue and this model answers by content.

        Needed because the two doors take different paths through LangGraph —
        `/api/runs` invokes and `/api/runs/stream` streams — and this test is
        about both of them agreeing. A fake that can only be invoked would have
        left the streaming half untested while looking tested.
        """
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        message = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        settled = message.generations[0].message
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content=settled.content,
                tool_call_chunks=[
                    {
                        "name": call["name"],
                        "args": json.dumps(call["args"]),
                        "id": call["id"],
                        "index": index,
                    }
                    for index, call in enumerate(settled.tool_calls or [])
                ],
            )
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


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from openstategraph import chat_model as chat_model_module

    model = _CallsTheQueryTool([], default="The first artist is AC/DC.")
    monkeypatch.setattr(chat_model_module, "build_chat_model", lambda _name: model)
    return TestClient(create_app())


def _body(audience: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "workflow": {"document": _document()},
        "question": "who is the first artist?",
        "thread_id": None,
        "session_id": "s1",
    }
    if audience:
        body["audience"] = audience
    return body


def _done(text: str) -> dict[str, Any]:
    name: str | None = None
    for line in text.splitlines():
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: ") and name == "done":
            return json.loads(line[len("data: ") :])
        elif line.startswith("data: "):
            name = None
    raise AssertionError("no done frame")


@pytest.mark.usefixtures("workflows_root")
class TestBothDoorsAnswerTheQuestion:
    """"What did this run execute?" — asked of a finished run, answered."""

    def test_the_blocking_door_carries_the_statement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = _client(monkeypatch).post("/api/runs", json=_body("developer")).json()
        statements = body["developer"]["statements"]
        assert [s["statement"] for s in statements] == [SQL]
        assert statements[0]["node"] == "agent1"
        assert "AC/DC" in statements[0]["result"]

    def test_the_streaming_door_agrees(self, monkeypatch: pytest.MonkeyPatch) -> None:
        done = _done(_client(monkeypatch).post("/api/runs/stream", json=_body("developer")).text)
        assert [s["statement"] for s in done["developer"]["statements"]] == [SQL]

    def test_a_customer_is_told_nothing_about_the_statement(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The negative half — `163`'s pattern, on the same seam."""
        client = _client(monkeypatch)
        blocking = client.post("/api/runs", json=_body(None))
        assert blocking.json()["developer"] is None
        assert "SELECT" not in blocking.text

        streamed = client.post("/api/runs/stream", json=_body(None))
        assert "developer" not in _done(streamed.text)
        assert "SELECT" not in streamed.text

    def test_the_run_still_answers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = _client(monkeypatch).post("/api/runs", json=_body("developer")).json()
        assert "AC/DC" in body["answer"]


class TestTheLibraryDoorAgrees:
    """The third door, and the one the last two diagnoses actually used.

    Yesterday's live sessions ran a package **in-process** — no server, no
    wheel, `load_workflow(pkg).ask(q)` under the demo's own interpreter. That
    is the path the next correctness question will take too, and a `RunResult`
    that cannot be asked what it executed sends the asker back to the model's
    prose, which is the whole of `30`.

    `RunResult` has no audience: a caller holding the process holds the run.
    """

    def test_a_result_carries_what_the_run_executed(self) -> None:
        from openstategraph.results import RunResult

        result = RunResult(
            "AC/DC",
            statements=[{"node": "agent1", "tool": "sql_query", "statement": SQL, "result": "1", "truncated": False}],
        )
        assert result.statements[0]["statement"] == SQL

    def test_a_run_that_executed_nothing_reports_an_empty_list(self) -> None:
        from openstategraph.results import RunResult

        assert RunResult("hello").statements == []

    def test_a_pickled_result_keeps_them(self) -> None:
        """`str.__reduce_ex__` round-trips the text and drops the rest — an
        object that still looks right and has quietly lost the diagnostics."""
        import pickle

        from openstategraph.results import RunResult

        rows = [{"node": "a", "tool": "t", "statement": SQL, "result": "1", "truncated": False}]
        assert pickle.loads(pickle.dumps(RunResult("x", statements=rows))).statements == rows

    def test_an_older_pickle_still_unpickles(self) -> None:
        """Appended, never inserted — `_rebuild`'s standing rule."""
        from openstategraph.results import _rebuild

        assert _rebuild("x", {}, {}, [], 0).statements == []
