"""`production-ready` 106 — a node's second lap erased its first lap's record.

Filed off `production-ready` 105's live runs: `chinook-assistant` on
`ollama:gpt-oss:120b-cloud`, reading `tool_use` at every `unrun_query_claim`
call in one run, showed `agent-sql`'s row losing `chinook_execute_sql` from
`ran` and losing `queried` entirely between two calls of the same run.

`tool_use` is `Annotated[dict, reducer_for(Reducer.MERGE)]`, and
`merge_decisions` is `{**left, **right}` — a merge one level deep. The key is
the node id, so a grader's revise loop, which re-invokes the same node with a
fresh set of messages each lap, has its second lap's row **replace** the
first's rather than add to it. `ran` is not a set that grows over a run; it
was the last lap's list.

That reducer is right for `decisions`, where a node's newest decision is the
one that counts. It is wrong for `tool_use`, a record of what happened — and
what happened does not un-happen.

The layer this is tested at is the compiled graph, not the reducer function in
isolation: a test that only calls the reducer would pass against the current
code by construction, because it would just be re-describing the merge it is
supposed to be checking. `web-research-digest` has a real agent (`digest1`)
bound to two tools with a grader (`grader1`) wired to send it back for
revision — exactly the shape the live run hit — so driving that document with
a scripted model that calls a different tool on each lap is what actually
exercises the reducer LangGraph applies between supersteps.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from openstategraph.abc.tool import BaseTool, ToolResult
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from conftest import RespondingModel

PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "openstategraph/examples/web-research-digest/workflow.json"
)


class _SearchArgs(BaseModel):
    query: str = ""


class _FetchArgs(BaseModel):
    url: str = ""


class _FakeWebSearch(BaseTool):
    name = "web_search"
    description = "Search the open web for candidate pages."
    Args = _SearchArgs

    def _execute(self, args: _SearchArgs) -> ToolResult:
        return ToolResult(content="1. Example Page - https://example.com/page")


class _FakeWebFetch(BaseTool):
    name = "web_fetch"
    description = "Fetch a page and return its readable text."
    Args = _FetchArgs

    def _execute(self, args: _FetchArgs) -> ToolResult:
        return ToolResult(content="The page says the sky is blue.")


web_search = _FakeWebSearch()
web_fetch = _FakeWebFetch()


#: One tool call per lap of `digest1`, in the order the model is expected to
#: reach for them: `web_search` while the grader is still unsatisfied,
#: `web_fetch` on the revision. The final text in each pair is the answer
#: `digest1` hands the grader for that lap.
_DIGEST_TURNS: list[dict[str, Any]] = [
    {"tool": ("web_search", {"query": "the sky"})},
    {"text": "Some field notes, no link yet."},
    {"tool": ("web_fetch", {"url": "https://example.com/page"})},
    {"text": "The sky is blue.\n\nSources: https://example.com/page"},
]


class _Researcher(RespondingModel):
    """`digest1` runs its scripted turns in order; the grader passes lap 2."""

    lap: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        if "You are a grader" in content:
            # The grader's own criteria text names the string "Sources:" —
            # so match the *filled-in* line the candidate actually wrote,
            # never the bare word, or the criteria alone would always pass.
            return self._reply(
                "PASS" if "Sources: https://example.com/page" in content else
                "FAIL: no Sources line yet"
            )
        index = object.__getattribute__(self, "lap")
        object.__setattr__(self, "lap", index + 1)
        turn = _DIGEST_TURNS[index % len(_DIGEST_TURNS)]
        if "tool" in turn:
            name, args = turn["tool"]
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="", tool_calls=[{"name": name, "args": args, "id": f"c{index}"}]
                        )
                    )
                ]
            )
        return self._reply(turn["text"])


def _run() -> dict[str, Any]:
    document = json.loads(PACKAGE.read_text())["document"]
    runtime = NodeRuntime(
        model=_Researcher([], default="Some field notes, no link yet."),
        tools={"tool.web-search": web_search, "tool.web-fetch": web_fetch},
    )
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {
            "question": "what colour is the sky",
            "attempts": 0,
            "decisions": {},
            "outputs": {},
        },
        {"recursion_limit": 40},
    )


class TestASecondLapDoesNotErodeTheFirst:
    def test_the_premise_holds(self) -> None:
        """If the grader did not actually send `digest1` around twice, the
        rest of this file is testing the wrong situation."""
        state = _run()
        assert state["revisions"].get("grader1", 0) >= 1

    def test_both_laps_tools_are_remembered(self) -> None:
        """`web_search` (lap 1) must survive `web_fetch` (lap 2) replacing
        the row — this is the exact loss `production-ready/106` reported."""
        row = _run()["tool_use"]["digest1"]
        assert "web_search" in row["ran"]
        assert "web_fetch" in row["ran"]

    def test_bound_is_not_narrowed_by_a_later_lap(self) -> None:
        row = _run()["tool_use"]["digest1"]
        assert set(row["bound"]) == {"web_search", "web_fetch"}


class TestATurnBoundaryStillClearsIt:
    """The ticket's own warning: accumulating across laps must not start
    accumulating across *turns* too. A second run on the same thread is a
    different run, and `_input`'s turn-reset block is where that boundary is
    drawn for every other per-run channel — `tool_use` needs the same entry
    now that a repeat key merges instead of replacing."""

    def test_a_second_turn_does_not_inherit_the_firsts_tools(self) -> None:
        from langgraph.checkpoint.memory import InMemorySaver

        document = json.loads(PACKAGE.read_text())["document"]

        class _OneShot(RespondingModel):
            """No grader loop needed here — one lap per turn, PASS every time,
            a different tool each turn."""

            turn: int = 0

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
                content = "\n".join(str(m.content) for m in messages)
                if "You are a grader" in content:
                    return self._reply("PASS")
                turn = object.__getattribute__(self, "turn")
                if not any(
                    getattr(m, "type", "") == "tool" for m in messages
                ):
                    name = "web_search" if turn == 0 else "web_fetch"
                    args = {"query": "x"} if turn == 0 else {"url": "https://x"}
                    return ChatResult(
                        generations=[
                            ChatGeneration(
                                message=AIMessage(
                                    content="",
                                    tool_calls=[{"name": name, "args": args, "id": f"t{turn}"}],
                                )
                            )
                        ]
                    )
                object.__setattr__(self, "turn", turn + 1)
                return self._reply(f"An answer with a Sources: line, turn {turn}.")

        runtime = NodeRuntime(
            model=_OneShot([], default="An answer with a Sources: line."),
            tools={"tool.web-search": web_search, "tool.web-fetch": web_fetch},
        )
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        config = {"configurable": {"thread_id": "one-thread"}}

        first = graph.invoke(
            {
                "question": "turn one",
                "attempts": 0,
                "decisions": {},
                "outputs": {},
            },
            {**config, "recursion_limit": 40},
        )
        assert first["tool_use"]["digest1"]["ran"] == ["web_search"]

        second = graph.invoke(
            {"question": "turn two"},
            {**config, "recursion_limit": 40},
        )
        # The bug this reset guards against: `tool_use` now accumulates
        # within a run, and without the turn-boundary reset that same
        # accumulation would silently span turns too, so turn two would still
        # be carrying turn one's `web_search`.
        assert second["tool_use"]["digest1"]["ran"] == ["web_fetch"]
