"""`launch-readiness/159` — a reused tool result must answer the call that asked.

The defect, found in the owner's own logs three times before any of today's
changes and in two of four live re-runs afterwards:

```
OpenAIInvalidRequestError 400: Invalid parameter: 'tool_call_id' of
 'call_J9ED1xJVbQiGCI1li3P6zmso' not found in 'tool_calls' of previous
 message.  param: 'messages.[22].tool_call_id'
```

**It is the read-through cache in `NarrationMiddleware`, not summarization.**
`launch-readiness/105` stores the `ToolMessage` a tool returned and, on a
later identical call in the same thread, returns *that same object*. Its
`tool_call_id` is the **first** call's id — so the second lap appends a
`ToolMessage` answering a call the preceding `AIMessage` never made, and the
provider refuses the whole request. Its `.id` is the first message's id too,
which `add_messages` dedupes on, so the pair can be broken twice over.

LangGraph's own `ToolNode` docstring writes the correct shape for exactly this
hook (`langgraph 1.2.10`, `prebuilt/tool_node.py`):

    if cached := get_cache(request):
        return ToolMessage(content=cached, tool_call_id=request.tool_call["id"])

And the installed `SummarizationMiddleware` (`langchain 1.3.14`) is **not** the
culprit: `_find_safe_cutoff_point` walks back to the requesting `AIMessage`
before cutting. The installed version is what is asserted here, not the docs.

Driven through a real compiled graph, per the standing rule (`async-first/16`):
a test over the middleware alone cannot see what the provider was handed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openstategraph import load_workflow, prebuilt_mcp

THREAD = "159-thread"
ANSWER = "Four vessels, all to Rotterdam."

#: On `NarrationMiddleware`'s cache allowlist — a STRUCTURE tool, so a second
#: identical call is a hit. That is the whole precondition for the bug.
CACHED_TOOL = "mcp_list_lenses"


class FakeRemoteTool:
    """What `load_mcp_tools` hands back: a coroutine, and no `func`."""

    def __init__(self) -> None:
        self.name = CACHED_TOOL
        self.description = "List the lenses available."
        self.args_schema = {"type": "object", "properties": {"domain": {"type": "string"}}}
        self.func = None
        self.response_format = "content"
        self.metadata: dict[str, Any] = {}
        self.calls = 0

    async def coroutine(self, **kwargs: Any) -> Any:
        self.calls += 1
        return json.dumps({"lenses": ["catalog", "playlists"]})


def discovery(tool: FakeRemoteTool):
    async def _discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
        return [tool]

    return _discover


class RepeatingModel(GenericFakeChatModel):
    """Asks for the *same* allowlisted call twice, with two different ids.

    Which is not a contrived model: a long tool-using run re-checks the lens
    list, a table's schema or a canonical spelling constantly, and each ask
    carries a fresh `call_…` id from the provider.
    """

    calls: list[list[Any]] = []
    laps: int = 0

    def __init__(self) -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "laps", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
        self.calls.append(list(messages))
        object.__setattr__(self, "laps", self.laps + 1)
        if self.laps <= 2:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": CACHED_TOOL,
                        "args": {"domain": "sm"},
                        "id": f"call-{self.laps}",
                    }
                ],
            )
        else:
            message = AIMessage(content=ANSWER)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001, ANN202
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)


DOCUMENT: dict[str, Any] = {
    "version": 1,
    "name": "reused call id",
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
    directory = tmp_path / "reused-call-id"
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "reused call id",
                "savedAt": "2026-08-28T00:00:00Z",
                "document": DOCUMENT,
                "published": True,
            }
        )
    )
    return directory


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> FakeRemoteTool:
    tool = FakeRemoteTool()
    monkeypatch.setattr(prebuilt_mcp, "_discover_tools", discovery(tool))
    return tool


def _run(tmp_path: Path) -> tuple[str, RepeatingModel]:
    model = RepeatingModel()
    compiled = load_workflow(_package(tmp_path), model=model)
    result = compiled.graph.invoke(
        {"messages": [], "question": "Which lenses are available?"},
        config={"configurable": {"thread_id": THREAD}},
    )
    return str(result.get("answer") or ""), model


def unpaired(messages: list[Any]) -> tuple[list[str], list[str]]:
    """The two halves of the provider's rule, both of which this cache broke.

    `orphaned` — a `ToolMessage` whose `tool_call_id` is in no preceding
    `AIMessage`. That is the 400 the owner sees, and it is what a re-used
    result produces once the offload's `model_copy` has given it a fresh
    message id so `add_messages` no longer dedupes it away.

    `unanswered` — a tool call with no `ToolMessage` at all. That is the same
    defect's *other* face: the re-used object still carries the first message's
    `.id`, and `add_messages` dedupes on it, so the second lap's answer
    overwrites the first in place instead of being appended.
    """
    offered: dict[str, None] = {}
    answered: set[str] = set()
    orphaned: list[str] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call.get("id"):
                    offered[call["id"]] = None
        elif isinstance(message, ToolMessage):
            if message.tool_call_id in offered:
                answered.add(message.tool_call_id)
            else:
                orphaned.append(message.tool_call_id)
    return orphaned, [c for c in offered if c not in answered]


class TestAReusedResultAnswersTheCallThatAsked:
    def test_no_tool_message_is_orphaned_on_any_turn(self, tmp_path: Path, remote) -> None:
        """The 400, at the layer it is actually produced."""
        answer, model = _run(tmp_path)

        assert ANSWER in answer
        for lap, messages in enumerate(model.calls, start=1):
            orphaned, unanswered = unpaired(messages)
            assert orphaned == [], f"orphaned tool_call_id on model call {lap}"
            assert unanswered == [], f"tool call with no answer on model call {lap}"

    def test_the_reuse_still_happens(self, tmp_path: Path, remote) -> None:
        """Re-keying is not a licence to stop caching — `105` still holds."""
        _run(tmp_path)
        assert remote.calls == 1

    def test_every_tool_message_has_its_own_message_id(self, tmp_path: Path, remote) -> None:
        """`add_messages` dedupes on `.id`; a reused object shares one, and
        the earlier `ToolMessage` is then overwritten rather than kept."""
        _, model = _run(tmp_path)
        final = model.calls[-1]
        ids = [m.id for m in final if isinstance(m, ToolMessage)]
        assert len(ids) == 2
        assert len(set(ids)) == 2
