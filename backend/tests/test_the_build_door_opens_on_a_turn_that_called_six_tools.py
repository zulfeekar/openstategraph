"""`every-workflow-green` 51 — the build door opened on a turn that used tools.

A live `chinook-assistant` turn that called six tools and answered correctly
(*Rock*, *$826.65*, the two-join `GROUP BY` beside it) also rendered:

> **Nothing here did this.** Describe what you need.  `[ Build one for this
> workflow ]`

An offer to *build* a capability that already exists and was just used is the
most expensive false positive this surface has, and `doorHeadline`'s own
docstring names the cost: *"A headline that over-claims is how a card teaches a
developer to distrust every card."*

## What actually opens the door, established before any wording was touched

`capability_door` -> `used_no_tools(tool_use)`, and it is **per turn**: it
returns `False` on the first row carrying a `ran` entry, so any tool anywhere
in the run closes the door. The ticket's leading hypothesis — that the door is
scoped to a node the router never reached, `agent-web` — is therefore wrong,
and `TestItIsPerTurnAndNotPerNode` pins that it stays wrong. A node that never
ran cannot open the door on its own, and never could.

The predicate agreed with its docstring. **What it was handed did not agree
with the run.**

## The cause

`api/streaming.py` folds the `update` frames itself — it has no finished state
to read — and folded `tool_use` with `dict.update`. That replaces a node's
whole row. A node re-entered by a grader's revise loop writes a fresh row each
lap, so a second lap that answered from what it already had wrote
`{"bound": [...], "ran": []}` over the first lap's record of the tool that
genuinely ran.

That is `production-ready` 106 exactly, at the one door its fix never reached:
106 changed the *state channel's* reducer to `MERGE_ROWS`, and this door does
not read state. `tool_use` is the only channel in `RunState` declaring
`MERGE_ROWS`; every other map this fold touches declares `MERGE`, which
`dict.update` is. So the rule the fold has to keep is *apply the reducer the
channel declares*, and `TestTheFoldKeepsTheChannelsOwnReducer` is what fails
when a second `MERGE_ROWS` channel arrives.

Two symptoms, one cause: the same overwrite emptied `developer.statements`,
so the run's evidence rail lost the query it had just published. `/api/runs`,
which reads final state, reported both correctly on the identical run — which
is what made the two doors visibly disagree.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from openstategraph.api.main import create_app
from openstategraph.compile.workflow_compiler import DOOR_SHAPE_RULE, used_no_tools

from conftest import RespondingModel

ROOT = Path(__file__).resolve().parents[2]
DOOR_HEADLINE_TS = ROOT / "src" / "view" / "ask" / "doorHeadline.ts"

SQL = "SELECT Name FROM Artist ORDER BY ArtistId LIMIT 1"


@pytest.fixture()
def workflows_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workflows"
    (root / "pkg" / "data").mkdir(parents=True)
    with sqlite3.connect(root / "pkg" / "data" / "music.sqlite") as conn:
        conn.execute("CREATE TABLE Artist (ArtistId INTEGER, Name TEXT)")
        conn.executemany("INSERT INTO Artist VALUES (?, ?)", [(1, "AC/DC"), (2, "Accept")])
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    return root


class _ToolOnTheFirstLapOnly(RespondingModel):
    """The live shape, minimised: lap 1 queries and answers, the grader sends
    it back once, lap 2 answers from what it already has.

    The second lap calling no tool is not an edge case — it is what a revise
    loop is *for* when the criticism is about the wording rather than the
    facts, and it is the shape `chinook-assistant`'s retried `agent-sql` left
    behind.
    """

    lap: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        if "You are a grader" in content:
            seen = object.__getattribute__(self, "lap")
            object.__setattr__(self, "lap", seen + 1)
            return self._reply("PASS" if seen >= 1 else "FAIL: say it more plainly")
        if any(getattr(m, "type", "") == "tool" for m in messages):
            return self._reply("The first artist is AC/DC.")
        if "say it more plainly" in content:
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
        """The streaming door takes a different path through LangGraph, and it
        is the door under test — a fake that can only be invoked would leave
        the half this ticket is about untested while looking tested."""
        settled = self._generate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ).generations[0].message
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


def _node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _document() -> dict[str, Any]:
    return {
        "version": 1,
        "name": "asks the database and is graded",
        "nodes": [
            _node("in1", "input.text"),
            _node("agent1", "agent.llm", systemPrompt="Answer from the database."),
            _node("sql1", "tool.sql-query", database="pkg/data/music.sqlite"),
            _node("grader1", "route.grader", criteria="Is it plain?", maxAttempts=3),
            _node("out1", "output.formatted"),
        ],
        "edges": [
            _edge("in1", "text", "agent1", "prompt"),
            _edge("sql1", "tool", "agent1", "tools"),
            _edge("agent1", "result", "grader1", "candidate"),
            _edge("grader1", "pass", "out1", "result"),
            _edge("grader1", "revise", "agent1", "feedback"),
        ],
    }


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from openstategraph import chat_model as chat_model_module

    model = _ToolOnTheFirstLapOnly([], default="The first artist is AC/DC.")
    monkeypatch.setattr(chat_model_module, "build_chat_model", lambda *a, **k: model)
    return TestClient(create_app())


def _body() -> dict[str, Any]:
    return {
        "workflow": {"document": _document()},
        "question": "who is the first artist?",
        "thread_id": None,
        "session_id": "s1",
        "audience": "developer",
    }


def _done(text: str) -> dict[str, Any]:
    name: str | None = None
    for line in text.splitlines():
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: ") and name == "done":
            return json.loads(line[len("data: ") :])
    raise AssertionError("no done frame in the stream")


@pytest.mark.usefixtures("workflows_root")
class TestATurnThatCalledAToolIsNotOfferedOneToBuild:
    def test_the_premise_holds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the grader did not send `agent1` around a second time, this file
        is testing the wrong situation."""
        done = _done(_client(monkeypatch).post("/api/runs/stream", json=_body()).text)

        assert done["attempts"] >= 2
        assert done["answer"].startswith("The first artist is AC/DC.")

    def test_the_streaming_door_offers_nothing_to_build(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ticket's first "done when": a turn in which any bound tool was
        called does not offer to build one."""
        done = _done(_client(monkeypatch).post("/api/runs/stream", json=_body()).text)

        assert done["developer"]["capabilityGap"] is None

    def test_the_blocking_door_always_agreed_and_still_does(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/api/runs` reads finished state, where `MERGE_ROWS` had already
        fixed this. It is the control that named the cause: two doors, one
        run, different answers."""
        body = _client(monkeypatch).post("/api/runs", json=_body()).json()

        assert (body.get("developer") or {}).get("capabilityGap") is None

    def test_the_statement_rail_survives_the_second_lap_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same overwrite, the second symptom. `statements_executed` reads
        the same `tool_use`, so the run's evidence disappeared with its tool
        record — on the door two shipped UIs read."""
        done = _done(_client(monkeypatch).post("/api/runs/stream", json=_body()).text)

        assert [row["tool"] for row in done["developer"]["statements"]] == ["sql_query"]

    def test_the_tool_that_ran_is_still_on_the_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stated at the level of the thing that was lost, so a future change
        that closes the door some other way does not pass this file."""
        done = _done(_client(monkeypatch).post("/api/runs/stream", json=_body()).text)

        assert done["developer"]["statements"], done["developer"]


@pytest.mark.usefixtures("workflows_root")
class TestTheDoorStillOpensWhenItShould:
    """The other half, at the same door, or the fix is a deletion.

    Ticket 35's whole point is that the shape opens the door with no
    cooperation from the model. A run with the same tool bound that never
    reaches for it is still offered one to build.
    """

    def test_a_run_that_touched_nothing_is_still_offered_the_door(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph import chat_model as chat_model_module

        never = RespondingModel([], default="I do not have live sales figures.")
        monkeypatch.setattr(chat_model_module, "build_chat_model", lambda *a, **k: never)
        done = _done(TestClient(create_app()).post("/api/runs/stream", json=_body()).text)

        assert done["developer"]["capabilityGap"] == ""


class TestItIsPerTurnAndNotPerNode:
    """The ticket's second "done when", and the answer to its own question.

    `used_no_tools` returns `False` on the first row carrying `ran`, so a node
    that never ran cannot open the door on its own. A router that chose another
    branch is not a gap, and never was — the hypothesis in the ticket was
    wrong, and this is what keeps it wrong.
    """

    def test_a_node_the_router_never_reached_does_not_open_the_door(self) -> None:
        never_ran = {
            "agent-sql": {"bound": ["chinook_query"], "ran": ["chinook_query"]},
            "agent-web": {"bound": ["web_search", "web_fetch"], "ran": []},
        }

        assert used_no_tools(never_ran) is False

    def test_a_node_that_never_ran_alone_still_opens_it(self) -> None:
        """The other half, or the clause above is a deletion: a run where the
        *only* tool-bearing node called nothing is the shape the door exists
        for."""
        assert used_no_tools({"agent-web": {"bound": ["web_search"], "ran": []}}) is True


class TestTheRuleAndTheHeadlineSayTheSameThing:
    """The ticket's third "done when", and the durable half.

    `doorHeadline`'s docstring was the only statement of the rule, in a
    different language from the predicate, with nothing between them. So the
    sentence is published once, by the predicate's own module, and both sides
    quote it.
    """

    @staticmethod
    def _flat(text: str) -> str:
        """Whitespace-normalised, because both statements are wrapped prose.

        A pin that fails when a sentence moves across a line break is a pin
        somebody deletes the next time they reflow a comment — and a jsdoc
        block breaks every line with a `*`, so that goes too.
        """
        import re

        return " ".join(re.sub(r"(?m)^\s*\*", " ", text).split())

    def test_the_predicate_states_the_rule_it_implements(self) -> None:
        assert DOOR_SHAPE_RULE in self._flat(used_no_tools.__doc__ or "")

    def test_the_card_quotes_the_same_sentence(self) -> None:
        assert DOOR_SHAPE_RULE in self._flat(DOOR_HEADLINE_TS.read_text(encoding="utf-8"))

    def test_the_rule_says_which_scope_it_is(self) -> None:
        """The word that was missing, and the whole of what this ticket had to
        establish before any wording could be changed."""
        assert "turn" in DOOR_SHAPE_RULE


class TestTheFoldKeepsTheChannelsOwnReducer:
    """What fails when a second row-shaped channel arrives at this door.

    The door folds `update` frames by hand because it has no finished state to
    read, so every channel it folds is a second implementation of that
    channel's reducer. `dict.update` *is* `MERGE`; it is not `MERGE_ROWS`, and
    `tool_use` is the one channel that declares the latter. A derived census
    rather than a list, for the reason the class censuses learned: a
    hand-picked list covers what somebody already worried about.
    """

    @staticmethod
    def _row_merged_channels() -> set[str]:
        import typing

        from openstategraph.compile.reducers import Reducer, reducer_for
        from openstategraph.compile.state import RunState

        wanted = reducer_for(Reducer.MERGE_ROWS)
        found: set[str] = set()
        for name, annotation in typing.get_type_hints(
            RunState, include_extras=True
        ).items():
            if wanted in getattr(annotation, "__metadata__", ()):
                found.add(name)
        return found

    def test_the_census_finds_the_channel_this_ticket_is_about(self) -> None:
        assert "tool_use" in self._row_merged_channels()

    def test_no_row_merged_channel_is_folded_with_a_plain_update(self) -> None:
        """Read as a tree rather than as text: `tool_use.update(...)` is the
        right call to make and the wrong one to make with a comprehension, so
        the thing to check is the argument."""
        import ast
        import inspect

        from openstategraph.api import streaming

        channels = self._row_merged_channels()
        offenders: list[str] = []
        for call in ast.walk(ast.parse(inspect.getsource(streaming))):
            if not isinstance(call, ast.Call):
                continue
            target = call.func
            if not isinstance(target, ast.Attribute) or target.attr != "update":
                continue
            if not isinstance(target.value, ast.Name) or target.value.id not in channels:
                continue
            merged = call.args and isinstance(call.args[0], ast.Call) and (
                getattr(call.args[0].func, "id", None) == "merge_rows"
            )
            if not merged:
                offenders.append(f"{target.value.id}:{call.lineno}")

        assert offenders == [], offenders
