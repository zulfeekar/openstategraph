"""`osg-agent-experience/50`: nothing that judged the run could see the failures.

The owner's Mongstad question, live on 2026-09-05. The lens ran three T-SQL
statements and every one came back *Login timeout expired*. The honesty check
judged the answer **text** — refused it twice for carrying no figure, then
published on exhaustion — and the grader, judging the same text, said `pass`.
The published answer was a paragraph explaining it could not connect, stamped
as having cleared the workflow's own review.

**Both judges were right by their own rules, which is what makes this a
defect rather than a bug.** `BaseGrader.PROMPT`'s refusal clause says an
honest decline is a PASS, and `web-research-digest`'s own criteria say so in
as many words: *"A reported tool failure is an acceptable answer and passes."*
That clause is not changed here and must not be — it was added on evidence,
after a grader rejected a correct refusal and the retries destroyed the only
good answer in the run. What was missing is not a rule. It is a **fact**: the
run's own record of how many tool calls it made and how many of them returned
anything.

`tool_use` already held most of it — `bound`, `ran`, `queried`, `queries` —
and recorded a failure nowhere at all. `queries` keeps an exchange only for a
tool message that is *not* an error, and `ran` counts an errored call as a use
(errors are data, and the tool is wired) without saying that is what happened.
So a node whose every call failed and a node whose every call succeeded left
records that differed only in what was absent from them.

**No new state key, and no new reducer.** `tool_use` is the record of what a
node did, it is already `MERGE_ROWS`, and every tool-binding factory already
writes it through one seam. A second key carrying the same knowledge is the
duplication `CLAUDE.md` forbids by name. The counters are scalars on the
existing row, which is what makes them per-lap: `merge_rows` unions lists and
**overwrites** scalars, so a later lap's `failed: 0` replaces an earlier lap's
count rather than accumulating with it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from openstategraph.abc.tool import BaseTool, ToolResult
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.reporting import tool_report
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.run_summary import (
    RunSummary,
    every_tool_call_failed,
    evidence_for_grader,
    summarise_run,
)

from conftest import RespondingModel

PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "openstategraph/examples/web-research-digest/workflow.json"
)

#: The warehouse's own words, near enough verbatim from the live run.
TIMEOUT = "Login timeout expired"


class _SearchArgs(BaseModel):
    query: str = ""


class _FetchArgs(BaseModel):
    url: str = ""


class _TimingOutSearch(BaseTool):
    """Answers every call the way the warehouse did: not at all."""

    name = "web_search"
    description = "Search the open web for candidate pages."
    Args = _SearchArgs

    def _execute(self, args: _SearchArgs) -> ToolResult:
        return ToolResult.failure(TIMEOUT)


class _WorkingSearch(BaseTool):
    """The control. Same tool, same calls, an answer at the end of them."""

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


#: What the agent says once its tool has failed: the honest decline, which is
#: the answer the live run published with a `pass` beside it.
DECLINE = (
    "I could not reach the source. The search tool reported a login timeout, "
    "so I have no fetched page to attribute anything to."
)


class _Researcher(RespondingModel):
    """Calls the search tool once per lap, then hands over its text."""

    lap: int = 0

    def __init__(self, answer: str) -> None:
        super().__init__([], default=answer)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        self.calls.append(content)
        if "You are a grader" in content:
            # The model grader would pass this text on the package's own
            # criteria — a quoted tool failure is an acceptable answer there.
            # Nothing in this test relies on it saying so; the point is that
            # its judgement is never reached.
            return self._reply("PASS")
        if any(getattr(m, "type", "") == "tool" for m in messages):
            return self._reply(self.default)
        index = object.__getattribute__(self, "lap")
        object.__setattr__(self, "lap", index + 1)
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "web_search", "args": {"query": "mongstad"}, "id": f"c{index}"}
                        ],
                    )
                )
            ]
        )


def _run(search: BaseTool, answer: str) -> dict[str, Any]:
    document = json.loads(PACKAGE.read_text())["document"]
    runtime = NodeRuntime(
        model=_Researcher(answer),
        tools={"tool.web-search": search, "tool.web-fetch": _FakeWebFetch()},
    )
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": "how many vessels departed mongstad last week",
         "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 40},
    )


class TestTheRunRecordsThatTheCallFailed:
    """`tool_report` is the seam every tool-binding factory shares."""

    def test_our_own_failure_shape_is_counted(self) -> None:
        """A `ToolResult.failure` reaches the loop as `Error: …` prose.

        Not `status="error"` — that is LangChain's own marker for a tool whose
        body *raised*, and this platform's rule is that errors are data. So a
        record that watched only the status field saw three clean calls.
        """
        messages = [
            AIMessage(content="", tool_calls=[{"name": "warehouse", "args": {}, "id": "c1"}]),
            ToolMessage(content=f"Error: {TIMEOUT}", tool_call_id="c1", name="warehouse"),
        ]
        row = tool_report("a1", messages, ["warehouse"])["tool_use"]["a1"]
        assert row["calls"] == 1
        assert row["failed"] == 1
        assert row["last_error_tool"] == "warehouse"
        assert TIMEOUT in row["last_error"]

    def test_a_raised_body_is_counted_too(self) -> None:
        messages = [
            AIMessage(content="", tool_calls=[{"name": "warehouse", "args": {}, "id": "c1"}]),
            ToolMessage(
                content="boom", tool_call_id="c1", name="warehouse", status="error"
            ),
        ]
        row = tool_report("a1", messages, ["warehouse"])["tool_use"]["a1"]
        assert row["failed"] == 1

    def test_a_working_call_is_a_success(self) -> None:
        messages = [
            AIMessage(content="", tool_calls=[{"name": "warehouse", "args": {}, "id": "c1"}]),
            ToolMessage(content="42", tool_call_id="c1", name="warehouse"),
        ]
        row = tool_report("a1", messages, ["warehouse"])["tool_use"]["a1"]
        assert (row["calls"], row["failed"]) == (1, 0)
        assert row["last_error"] == ""

    def test_a_node_that_called_nothing_says_nothing(self) -> None:
        """Absent rather than zero — the rule the rest of this row obeys."""
        row = tool_report("a1", [AIMessage(content="hi")], ["warehouse"])["tool_use"]["a1"]
        assert "calls" not in row and "failed" not in row


class TestTheSummary:
    def test_it_reads_the_run_rather_than_the_text(self) -> None:
        tool_use = {
            "a1": {"bound": ["warehouse"], "ran": ["warehouse"], "calls": 3,
                   "failed": 3, "last_error": TIMEOUT, "last_error_tool": "warehouse"}
        }
        summary = summarise_run(tool_use)
        assert isinstance(summary, RunSummary)
        assert (summary.calls, summary.succeeded, summary.failed) == (3, 0, 3)
        assert summary.every_call_failed
        assert summary.last_error_tool == "warehouse"
        assert "warehouse" in summary.tools

    def test_one_success_anywhere_clears_the_run(self) -> None:
        tool_use = {
            "a1": {"ran": ["warehouse"], "calls": 3, "failed": 3,
                   "last_error": TIMEOUT, "last_error_tool": "warehouse"},
            "a2": {"ran": ["notes"], "calls": 1, "failed": 0},
        }
        assert every_tool_call_failed(tool_use) is None
        assert not summarise_run(tool_use).every_call_failed

    def test_a_run_that_called_nothing_is_never_accused(self) -> None:
        """A writer agent has no tools by design and must not be blamed."""
        assert every_tool_call_failed({"a1": {"bound": [], "ran": []}}) is None

    def test_the_claim_names_the_tool_and_the_error(self) -> None:
        claim = every_tool_call_failed(
            {"a1": {"ran": ["warehouse"], "calls": 3, "failed": 3,
                    "last_error": TIMEOUT, "last_error_tool": "warehouse"}}
        )
        assert claim is not None
        assert "warehouse" in claim and TIMEOUT in claim

    def test_the_evidence_block_is_silent_when_nothing_failed(self) -> None:
        assert evidence_for_grader(summarise_run({"a1": {"calls": 2, "failed": 0}})) == ""


class TestTheGraderCannotPassIt:
    def test_the_verdict_is_revise_and_names_the_tool_and_the_error(self) -> None:
        final = _run(_TimingOutSearch(), DECLINE)
        verdict = final["verdicts"]["grader1"]
        assert verdict["verdict"] == "revise"
        assert verdict["check"] == "tools_all_failed"
        assert "web_search" in verdict["reason"]
        assert TIMEOUT in verdict["reason"]

    def test_the_exhausted_run_says_the_answer_is_unverified(self) -> None:
        """The existing exhaustion path, not a new one (`launch-readiness/167`)."""
        final = _run(_TimingOutSearch(), DECLINE)
        assert final["decisions"]["grader1"] == "pass"
        assert "grader1" in (final.get("forced") or {})
        assert TIMEOUT in str((final.get("forced") or {}).get("grader1", ""))

    def test_a_working_lap_is_untouched(self) -> None:
        answer = "The sky is blue.\n\nSources: https://example.com/page"
        final = _run(_WorkingSearch(), answer)
        assert final["verdicts"]["grader1"]["verdict"] == "pass"
        assert final["verdicts"]["grader1"]["check"] == ""
        assert final["answer"].startswith("The sky is blue.")


class TestTheGuardsSecondArgument:
    """Backwards compatible: `fn(text)` still works, `fn(text, summary)` is fed.

    Driven through a real agent rather than by seeding `tool_use` into the
    invocation, because `_input` resets every per-run channel at the turn
    boundary — a seeded record is erased before any node reads it, and a test
    that passed on one would be proving nothing about a run.
    """

    def _document(self) -> dict:
        return {
            "version": 2,
            "name": "guard-summary",
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "t-search", "type": "tool.web-search", "position": {"x": 0, "y": 120}, "data": {}},
                {"id": "a1", "type": "agent.llm", "position": {"x": 200, "y": 0}, "data": {}},
                {"id": "g1", "type": "guard.check", "position": {"x": 400, "y": 0},
                 "data": {"check": "look", "maxAttempts": 1}},
                {"id": "out1", "type": "output.formatted", "position": {"x": 600, "y": 0}, "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"},
                 "target": {"nodeId": "a1", "portId": "prompt"}},
                {"source": {"nodeId": "t-search", "portId": "tool"},
                 "target": {"nodeId": "a1", "portId": "tools"}},
                {"source": {"nodeId": "a1", "portId": "result"},
                 "target": {"nodeId": "g1", "portId": "candidate"}},
                {"source": {"nodeId": "g1", "portId": "pass"},
                 "target": {"nodeId": "out1", "portId": "result"}},
            ],
        }

    def _drive(self, fn: Any) -> dict[str, Any]:
        document = self._document()
        runtime = NodeRuntime(
            model=_Researcher(DECLINE),
            tools={"tool.web-search": _TimingOutSearch()},
            functions={"function.look": fn},
        )
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        return graph.invoke(
            {"question": "anything", "attempts": 0, "decisions": {}, "outputs": {}},
            {"recursion_limit": 20},
        )

    def test_a_one_argument_function_still_runs(self) -> None:
        seen: list[str] = []

        def look(text: str) -> str:
            seen.append(text)
            return ""

        final = self._drive(look)
        assert seen == [DECLINE]
        assert final["decisions"]["g1"] == "pass"

    def test_a_two_argument_function_receives_the_summary(self) -> None:
        seen: list[RunSummary] = []

        def look(text: str, summary: RunSummary) -> str:
            seen.append(summary)
            return "no evidence arrived" if summary.every_call_failed else ""

        final = self._drive(look)
        assert len(seen) == 1
        assert seen[0].every_call_failed
        assert seen[0].last_error_tool == "web_search"
        assert TIMEOUT in seen[0].last_error
        assert final["verdicts"]["g1"]["reason"] == "no evidence arrived"
