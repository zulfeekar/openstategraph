"""`launch-readiness/158` — the app works whichever model is driving.

## The correction this file starts from

`156` was filed on the belief that `mcp_resolve_lens` and `mcp_prepare` were
*uncallable* because their schema nests its arguments under `inp`. **They are
not.** Verified live against a running MCP server: the nested form answers
`ok: true, lens: catalog, confidence 0.81`, the flat form is refused, the
schema reaches the model intact through `langchain-mcp-adapters`, and GitHub
Copilot calls both tools without trouble. **`gpt-4o-mini` flattened the
`$ref`.** Nothing is wrong with that service and nothing there is changed.

## Why that is still ours

> *"It doesn't matter which model. The app should work. Reasoning is
> subjective — it shouldn't fail, it should be handled."*

`CLAUDE.md`'s standing rule is *read a model's answer tolerantly; trust it
strictly*, and its own worked examples are this shape: `validate_workflow`
typed its argument `str`, the agent sent an object because that is the obvious
move for a field named `document`, and the run died re-appending it
(`every-workflow-green/13`). **`156` makes the refusal readable so a model can
retry; this removes the dependency on the retry being right.**

## The strict half is the subject

Tolerance here is a *rewrite of what the model asked for*, which is the most
dangerous kind, so the adaptation happens only where the schema **forces** it —
one required top-level property, that property an object, every key sent one of
its own, and nothing sent matching a top-level name. Where more than one
wrapping is legal, nothing is adapted and `156`'s readable error stands.

The refusals below are the load-bearing half of this file. An adapter that
silently rewrites a wrong call into a different wrong call is worse than the
failure it replaced.
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

THREAD = "158-thread"

#: `mcp_resolve_lens`'s real schema, as the owner read it off
#: `MultiServerMCPClient.get_tools()` on 2026-08-28.
WRAPPER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"inp": {"$ref": "#/$defs/ResolveLensInput"}},
    "required": ["inp"],
    "$defs": {
        "ResolveLensInput": {
            "type": "object",
            "properties": {"question": {"type": "string"}, "lens": {"type": "string"}},
            "required": ["question"],
        }
    },
}

#: The same shape written out rather than referenced. A model flattens both.
INLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "inp": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        }
    },
    "required": ["inp"],
}

FLAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
}

#: Two required properties, so no single wrapping is forced.
TWO_REQUIRED: dict[str, Any] = {
    "type": "object",
    "properties": {
        "inp": {"type": "object", "properties": {"question": {"type": "string"}}},
        "other": {"type": "object", "properties": {"question": {"type": "string"}}},
    },
    "required": ["inp", "other"],
}

#: The wrapper is required, but `question` is *also* a top-level property. A
#: flat `{"question": …}` is a legal top-level call that happens to be missing
#: `inp`; rewriting it would be inventing an intention.
SHADOWED: dict[str, Any] = {
    "type": "object",
    "properties": {
        "inp": {"type": "object", "properties": {"question": {"type": "string"}}},
        "question": {"type": "string"},
    },
    "required": ["inp"],
}


class FakeSession:
    def __init__(self, ok: str) -> None:
        self.ok = ok
        self.calls: list[dict[str, Any]] = []

    async def call_tool(self, name: str, arguments: Any, **kwargs: Any) -> CallToolResult:
        """That server's own contract: nested is accepted, flat is refused."""
        args = dict(arguments or {})
        self.calls.append(args)
        if set(args) == {"inp"} and isinstance(args["inp"], dict):
            inner = args["inp"]
            if "question" not in inner:
                return _error("1 validation error for ResolveLensInput\nquestion\n  Field required")
            if set(inner) - {"question", "lens"}:
                return _error("unexpected field for ResolveLensInput")
            return CallToolResult(content=[TextContent(type="text", text=self.ok)], isError=False)
        return _error(
            "1 validation error for mcp_resolve_lensArguments\ninp\n  Field required"
        )


def _error(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)


def _remote(session: FakeSession, schema: dict[str, Any]) -> Any:
    return convert_mcp_tool_to_langchain_tool(
        session=session,
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


class FlatteningModel(GenericFakeChatModel):
    """`gpt-4o-mini`'s actual behaviour: the `$ref` collapsed into its fields."""

    calls: list[list[Any]] = []
    args: dict[str, Any] = {}

    def __init__(self, args: dict[str, Any]) -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "args", args)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
        self.calls.append(list(messages))
        if any(m.__class__.__name__ == "ToolMessage" for m in messages):
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="Done looking."))]
            )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "mcp_resolve_lens", "args": dict(self.args), "id": "c1"}
                        ],
                    )
                )
            ]
        )

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001, ANN202
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)

    def tool_text(self) -> str:
        parts: list[str] = []
        for call in self.calls:
            for m in call:
                if m.__class__.__name__ != "ToolMessage":
                    continue
                content = m.content
                if isinstance(content, list):
                    parts.append(
                        "".join(
                            b.get("text", "") for b in content if isinstance(b, dict)
                        )
                    )
                else:
                    parts.append(str(content))
        return "\n".join(parts)


DOCUMENT: dict[str, Any] = {
    "version": 1,
    "name": "flattened ref",
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


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _run(
        schema: dict[str, Any] = WRAPPER_SCHEMA,
        args: dict[str, Any] | None = None,
        answer: str = '{"ok": true, "lens": "catalog"}',
    ) -> tuple[FakeSession, FlatteningModel]:
        session = FakeSession(answer)
        monkeypatch.setattr(
            prebuilt_mcp, "_discover_tools", discovery(_remote(session, schema))
        )
        model = FlatteningModel(args if args is not None else {"question": "vessels?"})
        directory = tmp_path / "flattened-ref"
        directory.mkdir(parents=True)
        (directory / "workflow.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": "flattened ref",
                    "savedAt": "2026-08-28T00:00:00Z",
                    "document": DOCUMENT,
                    "published": True,
                }
            )
        )
        compiled = load_workflow(directory, model=model)
        compiled.graph.invoke(
            {"messages": [], "question": "vessels from Mongstad?"},
            config={"configurable": {"thread_id": THREAD}},
        )
        return session, model

    return _run


class TestTheForcedWrappingIsPerformed:
    def test_a_flattened_ref_reaches_the_server_nested(self, run) -> None:
        """The owner's case. One legal wrapping, so it is not a guess."""
        session, model = run()

        assert session.calls == [{"inp": {"question": "vessels?"}}]
        assert "catalog" in model.tool_text()

    def test_an_inline_object_is_the_same_case(self, run) -> None:
        """A `$ref` is a spelling. The forcing condition is the shape."""
        session, _ = run(schema=INLINE_SCHEMA)

        assert session.calls == [{"inp": {"question": "vessels?"}}]

    def test_a_call_that_was_already_nested_is_untouched(self, run) -> None:
        session, _ = run(args={"inp": {"question": "vessels?"}})

        assert session.calls == [{"inp": {"question": "vessels?"}}]

    def test_a_flat_schema_is_never_wrapped(self, run) -> None:
        """The widening test. Every other MCP tool in this server takes flat
        arguments, and every one of them worked."""
        session, _ = run(schema=FLAT_SCHEMA)

        assert session.calls == [{"question": "vessels?"}]


class TestAmbiguityIsRefused:
    def test_two_required_properties_force_nothing(self, run) -> None:
        session, model = run(schema=TWO_REQUIRED)

        assert session.calls == [{"question": "vessels?"}]
        assert "Field required" in model.tool_text()

    def test_a_key_that_is_also_a_top_level_property_is_left_alone(self, run) -> None:
        """A flat call here is a legal top-level call missing its wrapper.
        Rewriting it would be inventing an intention the model may not have."""
        session, _ = run(schema=SHADOWED)

        assert session.calls == [{"question": "vessels?"}]

    def test_an_unknown_field_is_not_smuggled_inside_the_wrapper(self, run) -> None:
        """The test that matters most: an adapter that rewrites a wrong call
        into a different wrong call is worse than the failure it replaced. The
        model's mistake is a bad field name, and it must read that back."""
        session, model = run(args={"quesiton": "vessels?"})

        assert session.calls == [{"quesiton": "vessels?"}]
        assert "Field required" in model.tool_text()

    def test_an_empty_call_is_not_wrapped_into_an_empty_object(self, run) -> None:
        session, _ = run(args={})

        assert session.calls == [{}]


class TestThePriorFixStillStands:
    def test_a_refusal_this_cannot_adapt_is_still_readable(self, run) -> None:
        """`156`. Adaptation removes the dependency on a correct retry; it does
        not remove the need for a refusal the model can read."""
        _, model = run(schema=SHADOWED)

        assert "inp" in model.tool_text()
        assert "\n\nArgument shape:" in model.tool_text()
