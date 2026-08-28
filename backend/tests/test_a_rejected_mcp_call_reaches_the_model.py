"""`launch-readiness/156` — a tool error is content, not the end of the run.

## What the owner saw

Asked `cpl-mcp` a real question, live, and read:

> *"I'm currently unable to retrieve the necessary data … due to an
> **authentication issue with the data source**."*

**There was no authentication issue.** Probed the same minute: every metadata
tool answered `ok: true`, and `mcp_execute_sql("SELECT 1", lens="cargoflow")`
returned a row. What actually happened is that `mcp_resolve_lens` and
`mcp_prepare` — the two tools that hand the agent real column names — nest
their arguments under a field called `inp`, the model sent them flat, and the
server refused. `_MCPToolExecutionError` then **raised out of our wrapper and
was caught nowhere**, `agent1` produced no result, and the agent composed a
cause for its own silence.

## Why the wrapper is the defect and not the schema

`langchain_mcp_adapters` already answers this correctly: the tool it builds
carries `handle_tool_error=_handle_mcp_tool_error`, so an `isError=True` result
reaches the model as a `ToolMessage` with `status="error"` that it can read and
correct. **`_wrap_async_tool` rebuilt the `StructuredTool` and did not carry
that across** — so a bare MCP client handled this bad call gracefully and we
did not. We were strictly worse than no wrapper.

The mismatch itself is the CPL service's and is not fixed here. What *is* ours
is that the tool's own JSON schema says which shape it wants, we hold it at
bind time, and nobody was telling the model.

## Tolerant is not silent

The other half, and the one a model cannot be trusted with. `127` established
that a model told to disclose discloses *most* of the time, and here the model
did worse than forget — it invented. So the run records the rejection itself
(`abc/tool_notes`, reachable for MCP tools since `157`) and
`compile/node_runtime._output` renders it, whatever the answer above claims.

Driven through a real compiled graph with the **real** adapter tool over a fake
session, because a test over the wrapper alone stays green against exactly this
defect: the error handler it drops lives one layer up, in `BaseTool.run`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool

from openstategraph import load_workflow, prebuilt_mcp
from openstategraph.abc.tool_notes import take_notes

THREAD = "156-thread"

#: The shrug the owner actually read, minus the apology. The model is scripted
#: to say it so the run's own record has something to contradict.
INVENTED = "I could not retrieve the data due to an authentication issue with the data source."

#: What the CPL server really answered, quoted from the live run.
REJECTION = "1 validation error for mcp_resolve_lensArguments\ninp\n  Field required"

#: `mcp_resolve_lens`'s real schema shape: one required property, an object.
NESTED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"inp": {"$ref": "#/$defs/ResolveLensInput"}},
    "required": ["inp"],
    "$defs": {
        "ResolveLensInput": {
            "type": "object",
            "properties": {"question": {"type": "string"}, "lens": {"type": "string"}},
        }
    },
}

FLAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
}


class FakeSession:
    """One MCP session that answers every call the same way."""

    def __init__(self, result: CallToolResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: Any, **kwargs: Any) -> CallToolResult:
        self.calls.append((name, dict(arguments or {})))
        return self.result


def _rejected(text: str = REJECTION) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)


def _accepted(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=False)


def _remote(result: CallToolResult, schema: dict[str, Any]) -> Any:
    """The tool exactly as `load_mcp_tools` builds it — error handler and all."""
    return convert_mcp_tool_to_langchain_tool(
        session=FakeSession(result),
        tool=MCPTool(
            name="mcp_resolve_lens",
            description="Resolve a question to a lens.",
            inputSchema=schema,
        ),
    )


def discovery(tool: Any):
    async def _discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
        return [tool]

    return _discover


class ShruggingModel(GenericFakeChatModel):
    """Calls the tool flat, then blames authentication — the live behaviour.

    Scripted rather than observed so the record's independence is provable:
    every assertion about what the reader learns has to survive a model that
    says the wrong thing.
    """

    calls: list[list[Any]] = []

    def __init__(self) -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "calls", [])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
        self.calls.append(list(messages))
        if any(m.__class__.__name__ == "ToolMessage" for m in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=INVENTED))])
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "mcp_resolve_lens",
                                "args": {"question": "vessels from Mongstad"},
                                "id": "call-1",
                            }
                        ],
                    )
                )
            ]
        )

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001, ANN202
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)

    def tool_messages(self) -> list[Any]:
        return [
            m for call in self.calls for m in call if m.__class__.__name__ == "ToolMessage"
        ]

    def tool_text(self) -> str:
        """What the model actually reads, blocks flattened as a provider does."""
        parts: list[str] = []
        for message in self.tool_messages():
            content = message.content
            if isinstance(content, list):
                parts.append(
                    "".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict)
                    )
                )
            else:
                parts.append(str(content))
        return "\n".join(parts)


DOCUMENT: dict[str, Any] = {
    "version": 1,
    "name": "rejected call",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "agent1",
            "type": "agent.llm",
            "position": {"x": 200, "y": 0},
            "data": {"role": "Analyst", "systemPrompt": "Answer the question."},
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
    directory = tmp_path / "rejected-call"
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "rejected call",
                "savedAt": "2026-08-28T00:00:00Z",
                "document": DOCUMENT,
                "published": True,
            }
        )
    )
    return directory


@pytest.fixture(autouse=True)
def _a_clean_bucket():
    take_notes(THREAD)
    yield
    take_notes(THREAD)


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _run(
        result: CallToolResult = None,  # type: ignore[assignment]
        schema: dict[str, Any] = NESTED_SCHEMA,
    ) -> tuple[dict[str, Any], ShruggingModel]:
        monkeypatch.setattr(
            prebuilt_mcp,
            "_discover_tools",
            discovery(_remote(result if result is not None else _rejected(), schema)),
        )
        model = ShruggingModel()
        compiled = load_workflow(_package(tmp_path), model=model)
        state = compiled.graph.invoke(
            {"messages": [], "question": "How many vessels departed from Mongstad?"},
            config={"configurable": {"thread_id": THREAD}},
        )
        return state, model

    return _run


class TestTheRunSurvives:
    def test_a_rejected_call_no_longer_kills_the_node(self, run) -> None:
        """The whole of `156`. `agent1` produced no result at all before this."""
        state, model = run()

        assert state.get("outputs", {}).get("agent1"), "agent1 produced nothing"
        assert "failed and produced no result" not in str(state.get("answer", ""))
        # The property `outputs` alone cannot prove: before this, the failure
        # marker was itself a non-empty output. The agent has to get a second
        # turn — a chance to read the refusal and fix its own arguments.
        assert len(model.calls) == 2, "the agent never got to correct itself"


class TestTheModelIsToldWhatWentWrong:
    def test_the_service_s_own_words_reach_the_model(self, run) -> None:
        """A bare MCP client does this. Ours did not, which is why it was
        strictly worse than no wrapper."""
        _, model = run()

        assert "inp" in model.tool_text()
        assert "Field required" in model.tool_text()

    def test_the_message_is_marked_as_a_failure_not_a_result(self, run) -> None:
        """Otherwise a rejection reads to the model as data it may cite."""
        _, model = run()

        assert [m.status for m in model.tool_messages()] == ["error"]

    def test_the_shape_the_tool_actually_wants_is_named(self, run) -> None:
        """The information was in the tool's own JSON schema, which we hold at
        bind time, and nobody was telling the model — so it guessed
        `departure_port` for three turns instead."""
        _, model = run()

        assert "inp" in model.tool_text()
        assert "nested" in model.tool_text().lower()
        # It begins on its own line. The live re-run read
        # `…/v/missingArgument shape: this tool takes…` — a provider that
        # concatenates content blocks bare, and one word running into the next.
        assert "\n\nArgument shape:" in model.tool_text()

    def test_a_tool_whose_schema_is_already_flat_gets_no_such_hint(self, run) -> None:
        """Strict in trusting. A hint is derived from a schema that says so,
        never offered because a call failed."""
        _, model = run(schema=FLAT_SCHEMA)

        assert "nested" not in model.tool_text().lower()


class TestTheRunRecordsItWhateverTheModelSays:
    def test_the_reader_learns_a_call_was_rejected(self, run) -> None:
        """`127`'s argument, applied to a failure: the model's account of its
        own silence is exactly what may not be relied on."""
        state, _ = run()

        answer = str(state.get("answer", ""))
        assert INVENTED in answer
        assert "rejected" in answer.lower()

    def test_it_says_the_service_reported_nothing_about_access(self, run) -> None:
        """The sentence the owner needed. It cost an hour of checking a
        credential that was never wrong."""
        state, _ = run()

        assert "access" in str(state.get("answer", "")).lower()

    def test_a_refusal_that_really_was_authorisation_is_not_contradicted(self, run) -> None:
        """The inverse, and the reason the claim is measured rather than
        asserted: two situations must not render identically in *either*
        direction."""
        state, _ = run(result=_rejected("401 Unauthorized: token rejected"))

        answer = str(state.get("answer", "")).lower()
        assert "unauthorised" in answer or "authorisation" in answer

    def test_the_service_s_own_words_never_reach_the_reader(self, run) -> None:
        """A result payload is the richest leak surface there is — a driver
        message, a request id, a user's own search term. The reader is told
        that a call was rejected, never in whose words."""
        state, _ = run()

        assert "Field required" not in str(state.get("answer", ""))

    def test_a_call_that_worked_records_nothing(self, run) -> None:
        """Silence by default. A disclosure on every answer trains a reader to
        skip disclosures."""
        state, _ = run(result=_accepted(json.dumps({"ok": True, "lens": "cargoflow"})))

        assert "rejected" not in str(state.get("answer", "")).lower()


class TestTheLibraryBoundaryIsUnchanged:
    def test_a_transport_failure_still_propagates(self, monkeypatch) -> None:
        """Parity with a bare client, deliberately, in both directions. Only an
        `isError=True` result is a recoverable answer the model can act on; a
        session that broke is not something a model can correct, and swallowing
        it would hide a dead server behind a model's prose."""

        class Broken:
            name = "mcp_resolve_lens"
            description = ""
            args_schema = FLAT_SCHEMA
            func = None
            response_format = "content_and_artifact"
            metadata: dict[str, Any] = {}

            async def coroutine(self, **kwargs: Any) -> Any:
                raise ConnectionResetError("the session died")

        wrapped = prebuilt_mcp._wrap_async_tool(Broken(), "a-server")
        with pytest.raises(ConnectionResetError):
            wrapped.func(question="x")
