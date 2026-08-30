"""`launch-readiness/162` — a result is offloaded *after* the model reads it.

The defect, measured live on an MCP package: at `tier: deep` the compiler wires
`OffloadMiddleware` over the whole wired surface, so
`mcp_describe_lens_tables` (14,101 chars) and `mcp_skill_read` (18,856) were
replaced with pointers **on arrival** while `mcp_resolve_lens` (3,037) was not.
The model therefore held the right lens and had never seen a column name, and
invented `loading_time` where the column is `load_date`.

**The platform does not classify the result, and must not.** `157` refused to
read meaning out of a stranger's payload shape, and nothing on the MCP wire
says "this is schema". What the platform *does* know, with no guessing at all,
is **whether the model has read the thing yet** — and that is the whole
distinction:

> A pointer is a fine way to see something *again*. It is never an acceptable
> way to see it for the *first* time.

So every tool result arrives in full, exactly once, and collapses to a pointer
only in later model calls, once the model has already had it in context and
answered on it. `102` is preserved — the transcript still cannot grow without
bound, and genuine data results still leave it — and an undeclared tool from a
stranger's server lands on the safe side without declaring anything.

Driven through a compiled workflow with a real deep-tier agent and a real MCP
tool, not the middleware alone: a test over the middleware stays green against
a compiler that wires it wrongly, and wiring is exactly what was wrong here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openstategraph import load_workflow, prebuilt_mcp

THREAD = "162-thread"

#: Over `DEFAULT_OFFLOAD_THRESHOLD_CHARS` (4,000) and shaped like the real
#: thing: the column the model needs is buried a long way down, exactly as
#: `load_date` was at line 211 of the offload file.
SCHEMA = (
    "catalog.tracks\n"
    + "".join(f"  filler_column_{i:03d}  text  a description of a column\n" for i in range(200))
    + "  load_date  date  the day the cargo was loaded\n"
    + "".join(f"  tail_column_{i:03d}  text  another description\n" for i in range(60))
)
ROWS = "vessel,product,port\n" + "".join(f"v{i},crude,Mongstad [NO]\n" for i in range(500))

POINTER = re.compile(r"\[offloaded: \d+ chars written to path='([^']+)'")


class FakeRemoteTool:
    """What `load_mcp_tools` hands back: a coroutine, and no `func`."""

    def __init__(self, name: str, payload: str) -> None:
        self.name = name
        self.description = f"{name} — a discovery call on this server."
        self.args_schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        self.func = None
        self.response_format = "content"
        self.metadata: dict[str, Any] = {}
        self._payload = payload

    async def coroutine(self, **kwargs: Any) -> str:
        return self._payload


def discovery(tools):
    async def _discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
        return list(tools)

    return _discover


class Analyst(GenericFakeChatModel):
    """Four turns: describe, query, re-read the pointer, answer.

    It reads what it was actually handed rather than following a script blind —
    the SQL turn writes whichever date column it can see, so a run that never
    saw one produces `loading_time`, which is the live symptom this file is
    about.
    """

    calls: list[list[Any]] = []
    column: str = ""

    def __init__(self) -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "column", "")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
        self.calls.append(list(messages))
        turn = len(self.calls)
        if turn == 1:
            return _call("mcp_describe_lens_tables", {"q": "catalog"}, "call-1")
        if turn == 2:
            seen = "\n".join(str(m.content) for m in messages if isinstance(m, ToolMessage))
            object.__setattr__(
                self, "column", "load_date" if "load_date" in seen else "loading_time"
            )
            return _call("mcp_execute_sql", {"q": f"select {self.column}"}, "call-2")
        if turn == 3:
            path = _pointer_path(messages, "call-1")
            # `offset` because `read_file` pages at 100 lines and the column
            # is at line 201 — which is the trace's six paged reads, and the
            # reason a pointer is not a substitute for arriving whole.
            return _call(
                "read_file",
                {"file_path": path or "/nowhere", "offset": 190},
                "call-3",
            )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001, ANN202
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)

    def content_for(self, turn: int, call_id: str) -> str:
        for message in self.calls[turn - 1]:
            if isinstance(message, ToolMessage) and message.tool_call_id == call_id:
                return str(message.content)
        return ""


def _call(name: str, args: dict[str, Any], call_id: str) -> ChatResult:
    message = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
    return ChatResult(generations=[ChatGeneration(message=message)])


def _pointer_path(messages, call_id: str) -> str | None:
    for message in messages:
        if isinstance(message, ToolMessage) and message.tool_call_id == call_id:
            found = POINTER.search(str(message.content))
            return found.group(1) if found else None
    return None


DOCUMENT: dict[str, Any] = {
    "version": 1,
    "name": "schema before offload",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "agent1",
            "type": "agent.llm",
            "position": {"x": 200, "y": 0},
            "data": {"tier": "deep", "summarize": False, "systemPrompt": "Answer it."},
        },
        {
            "id": "mcp1",
            "type": "tool.mcp",
            "position": {"x": 200, "y": 200},
            "data": {"servers": [{"id": "r0", "url": "http://127.0.0.1:9/mcp/"}]},
        },
        {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "agent1", "portId": "prompt"},
        },
        {
            "source": {"nodeId": "mcp1", "portId": "tool"},
            "target": {"nodeId": "agent1", "portId": "tools"},
        },
        {
            "source": {"nodeId": "agent1", "portId": "result"},
            "target": {"nodeId": "out1", "portId": "result"},
        },
    ],
}


def _package(tmp_path: Path) -> Path:
    directory = tmp_path / "schema-first"
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "schema before offload",
                "savedAt": "2026-08-28T00:00:00Z",
                "document": DOCUMENT,
                "published": True,
            }
        )
    )
    return directory


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _run() -> Analyst:
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            discovery(
                [
                    FakeRemoteTool("mcp_describe_lens_tables", SCHEMA),
                    FakeRemoteTool("mcp_execute_sql", ROWS),
                ]
            ),
        )
        model = Analyst()
        compiled = load_workflow(_package(tmp_path), model=model)
        compiled.graph.invoke(
            {"messages": [], "question": "How many vessels departed from Mongstad?"},
            config={"configurable": {"thread_id": THREAD}},
        )
        return model

    return _run


class TestTheFirstSightIsAlwaysInBand:
    def test_the_schema_reaches_the_model_whole_on_the_turn_it_arrives(self, run) -> None:
        model = run()

        arrived = model.content_for(2, "call-1")
        assert "load_date" in arrived
        assert len(arrived) > 4000
        assert "[offloaded:" not in arrived

    def test_and_so_the_next_query_names_the_real_column(self, run) -> None:
        model = run()

        assert model.column == "load_date"

    def test_a_data_result_gets_the_same_first_sight(self, run) -> None:
        """Not a schema/data distinction: the rule is *when*, not *what*."""
        model = run()

        assert "Mongstad [NO]" in model.content_for(3, "call-2")


class TestAndThenItLeavesTheTranscript:
    def test_a_result_the_model_has_answered_on_becomes_a_pointer(self, run) -> None:
        """`102` preserved: the transcript still cannot grow without bound."""
        model = run()

        assert "[offloaded:" in model.content_for(3, "call-1")
        assert "load_date" not in model.content_for(3, "call-1")

    def test_the_data_result_leaves_it_one_turn_later_too(self, run) -> None:
        model = run()

        assert "[offloaded:" in model.content_for(4, "call-2")

    def test_the_pointer_still_dereferences(self, run) -> None:
        """The file is written on arrival, so the path is live from the start."""
        model = run()

        assert "load_date" in model.content_for(4, "call-3")

    def test_the_harness_own_file_tools_are_never_offloaded(self, run) -> None:
        """A `read_file` result written to a file and pointed at is a loop."""
        model = run()

        assert "[offloaded:" not in model.content_for(4, "call-3")
