"""A tool result reaches the model verbatim, and that is a decision.

`organisms-first-class` 46, spawned by 38. Ticket 38 locked
`UNTRUSTED_INPUT_IS_DATA` into the preambles of Router and Grader, and
deliberately did not touch Agent — because an agent's untrusted text does not
arrive in its human message at all. It arrives as `ToolMessage`s inside the
`create_agent` ReAct loop, a channel `SystemPrompt` never touches.

**This file pins what happens on that channel, and it pins a refusal.** The
measured answer is that a tool's `ToolResult.content` becomes the
`ToolMessage`'s content unchanged — `BaseTool.as_langchain_tool` returns
`result.content` and nothing wraps, prefixes or delimits it. That is not an
omission any more: `docs/decisions/tool-result-framing.md` records why a
framing sentence is the wrong instrument here and what carries the weight
instead.

So the assertions below are deliberately assertions of *absence*, driven
through a compiled graph with a scripted model rather than read off a
constant. A future session that adds a framing prefix in
`as_langchain_tool`, in a `wrap_tool_call` middleware, or per-tool, turns this
file red — which is the point. The decision is re-openable; it is not
quietly reversible.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import RespondingModel  # noqa: E402
from openstategraph import injection  # noqa: E402
from openstategraph.abc.agent import AbstractAgentNode  # noqa: E402
from openstategraph.abc.tool import BaseTool, ToolResult  # noqa: E402
from openstategraph.compile.node_runtime import (  # noqa: E402
    NodeRuntime,
    RunState,
    _final_text,
)
from openstategraph.compile.workflow_compiler import WorkflowCompiler  # noqa: E402
from openstategraph.prebuilt_web import WebFetchTool  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RECORD = REPO / "docs" / "decisions" / "tool-result-framing.md"

#: Obviously inert. This file must never carry a string that reads as an
#: instruction to whatever later reads the test suite.
PAGE_TEXT = "ACME quarterly figure is 42 units. LOREM-IPSUM-INERT-MARKER."
PAGE = f"<html><body><p>{PAGE_TEXT}</p></body></html>"

ROWS = "Genre|Revenue\nRock|826.65"


class _OwnDataTool(BaseTool):
    """A tool whose output is the *user's own* data — the inverse case.

    Whatever is decided about a fetched page must not be applied to a SQL row
    count by category, and this class is how that stays honest.
    """

    name = "rows"
    description = "Query the user's own database."
    node_type = "tool.web-fetch"

    class Args(__import__("pydantic").BaseModel):
        model_config = {"extra": "forbid"}

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content=ROWS)


def _document() -> dict[str, Any]:
    """One agent, one tool, one output — the smallest graph with the channel."""
    return {
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {"prompt": "What is the figure?"}},
            {
                "id": "a1",
                "type": "agent.llm",
                "data": {"tier": "react", "systemPrompt": "Answer from the page."},
            },
            {"id": "t1", "type": "tool.web-fetch", "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {"format": "markdown"}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "a1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "t1", "portId": "tool"},
                "target": {"nodeId": "a1", "portId": "tools"},
            },
            {
                "source": {"nodeId": "a1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


ANSWER = "The figure is 42 units."


class _Recorder(RespondingModel):
    """Calls the tool on its first turn, then answers — recording every message
    list it was handed, which is the only place a `ToolMessage` can be seen as
    the model sees it."""

    lap: int = 0
    seen: list = []
    tool_name: str = "web_fetch"

    def __init__(self, tool_name: str = "web_fetch") -> None:
        super().__init__([], default=ANSWER)
        object.__setattr__(self, "lap", 0)
        object.__setattr__(self, "seen", [])
        object.__setattr__(self, "tool_name", tool_name)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        self.seen.append(list(messages))
        lap = object.__getattribute__(self, "lap")
        object.__setattr__(self, "lap", lap + 1)
        if lap == 0:
            call = {
                "name": object.__getattribute__(self, "tool_name"),
                "args": {"url": "https://example.test/page"} if self.tool_name == "web_fetch" else {},
                "id": "call-1",
            }
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[call]))]
            )
        return self._reply(ANSWER)


def _run(tool: Any, *, tool_name: str = "web_fetch", settings: dict | None = None):
    document = _document()
    if settings is not None:
        document["settings"] = settings
    model = _Recorder(tool_name)
    runtime = NodeRuntime(model=model, tools={"tool.web-fetch": tool})
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    final = graph.invoke(
        {"question": "What is the figure?", "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 20},
    )
    return model, final, runtime


def _tool_messages(messages: list[Any]) -> list[Any]:
    return [m for m in messages if getattr(m, "type", "") == "tool"]


class TestWhatAToolResultLooksLikeWhenItReachesTheModel:
    """The measurement, through a compiled graph and a real tool."""

    def test_the_page_text_arrives_verbatim_with_nothing_wrapped_around_it(self) -> None:
        model, _final, _rt = _run(WebFetchTool(fetcher=lambda _url: PAGE))
        # The *second* model call is the one that carries the tool result.
        assert len(model.seen) == 2
        results = _tool_messages(model.seen[-1])
        assert len(results) == 1
        assert results[0].content == PAGE_TEXT

    def test_the_react_protocol_is_intact_the_result_answers_its_call_id(self) -> None:
        """The load-bearing inverse of any framing scheme: whatever a wrapper
        did, a `ToolMessage` must still answer the `tool_call_id` the model
        asked with, or the loop is malformed."""
        model, _final, _rt = _run(WebFetchTool(fetcher=lambda _url: PAGE))
        assert _tool_messages(model.seen[-1])[0].tool_call_id == "call-1"

    def test_a_tool_returning_the_users_own_data_is_equally_unframed(self) -> None:
        """The scoped-framing inverse. Third-party content and a user's own
        rows travel the same channel; nothing today distinguishes them, and a
        future scheme that frames one must leave the other alone."""
        model, _final, _rt = _run(_OwnDataTool(), tool_name="rows")
        assert _tool_messages(model.seen[-1])[0].content == ROWS

    def test_the_answer_is_the_models_prose_not_the_tool_result(self) -> None:
        """`_final_text` is unaffected by anything on this channel: a tool
        result is evidence, never the answer (`every-workflow-green` 32)."""
        _model, final, _rt = _run(WebFetchTool(fetcher=lambda _url: PAGE))
        assert final["answer"] == ANSWER
        assert PAGE_TEXT not in final["answer"]

    def test_final_text_still_walks_past_a_trailing_tool_result(self) -> None:
        messages = [
            AIMessage(content=ANSWER),
            AIMessage(content="", tool_calls=[{"name": "web_fetch", "args": {}, "id": "c"}]),
        ]
        assert _final_text(messages) == ANSWER


class TestTheControlThatIsActuallyOnThisChannel:
    """A refusal is only honest if it names what does carry the weight."""

    def test_screening_is_the_first_slot_an_agent_composes(self) -> None:
        assert AbstractAgentNode.SLOT_ORDER[0] == injection.SLOT

    def test_a_workflow_that_asks_for_it_and_lacks_it_runs_and_is_told(self) -> None:
        """Through the compiled graph, not through `contribution()`: the
        document setting has to reach an agent's middleware resolution, and the
        absence has to be a line rather than an outage."""
        _model, final, runtime = _run(
            WebFetchTool(fetcher=lambda _url: PAGE),
            settings={injection.SETTING: True},
        )
        assert final["answer"] == ANSWER
        said = " ".join(runtime.diagnostics.warnings())
        assert injection.DISTRIBUTION in said
        assert "ran without it" in said

    def test_a_workflow_that_never_asked_hears_nothing(self) -> None:
        _model, _final, runtime = _run(WebFetchTool(fetcher=lambda _url: PAGE))
        assert injection.DISTRIBUTION not in " ".join(runtime.diagnostics.warnings())


class TestTheDecisionIsRecorded:
    """`.scratch/` is gitignored; a decision that lives only in a ticket leaves
    no diff. The ticket requires `docs/decisions/`."""

    def test_the_record_exists(self) -> None:
        assert RECORD.is_file()

    def test_it_names_the_channel_and_the_three_candidates(self) -> None:
        text = RECORD.read_text(encoding="utf-8").lower()
        assert "toolmessage" in text
        assert "wrap_tool_call" in text
        assert "per-tool" in text

    def test_it_names_what_carries_the_weight_instead(self) -> None:
        text = RECORD.read_text(encoding="utf-8")
        assert injection.SETTING in text
        assert "injection-screening.md" in text

    def test_it_claims_no_more_than_it_does(self) -> None:
        # Whitespace-normalised: the sentence is the vendor's, and it wraps.
        text = " ".join(RECORD.read_text(encoding="utf-8").lower().split())
        assert "no prompt or delimiter strategy fully prevents" in text
