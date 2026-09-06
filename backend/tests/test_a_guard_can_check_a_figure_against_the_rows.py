"""`osg-agent-experience/86`: a guard saw the answer and never the rows.

`guard.check` gained a second argument in `osg-agent-experience/50` — a
`RunSummary`, which counted the run's tool calls and remembered the last
failure. That answered *"did any evidence arrive"* and could not answer the
question the live adopter run actually needed answered: *is this figure
a figure the run retrieved*.

Two findings in one published answer on 2026-09-06:

- a breakdown row read ``Naphtra`` where every other row of that product read
  ``Naphtha``. To a reader a misspelling and a second category are the same
  text.
- a departure count of ``0``, published as a finding, from a window the
  warehouse holds hundreds of rows for.

Both are settleable by string containment against results the run already
carries in `tool_use[node]["queries"]`, with no model and no cost. Neither is
settleable against the answer text, which was the whole of what a guard got.

So the summary carries what came back, in the same fixed shape the run record
publishes (`executed_statements.statements_executed`) — one owner for how a
query exchange is read, one owner for what a credential looks like — and the
convention does not widen: `fn(text)` is untouched, `fn(text, summary)` gets a
richer summary.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from openstategraph.abc.tool import BaseTool, ToolResult
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.run_summary import RunSummary, summarise_run

from conftest import RespondingModel

#: What the warehouse answered, near enough to the live shape.
ROWS = "product|port|vessels\nNaphtha|Stenungsund O [SE]|1\nNaphtha|Mongstad [NO]|4"

#: The answer the model wrote from those rows, with one letter changed.
MISSPELT = "Naphtra moved through Stenungsund O [SE] on 1 vessel."

#: The same paragraph, spelt the way the rows spell it.
GROUNDED = "Naphtha moved through Stenungsund O [SE] on 1 vessel."


class _Args(BaseModel):
    sql: str = ""


class _Warehouse(BaseTool):
    name = "warehouse"
    description = "Run a read-only statement against the warehouse."
    Args = _Args

    def _execute(self, args: _Args) -> ToolResult:
        return ToolResult(content=ROWS)


class _Analyst(RespondingModel):
    """Queries the warehouse once per lap, then writes its paragraph.

    One paragraph per lap, in order, so a lap sent back by the guard can
    answer differently from the one before it — which is what makes the round
    trip visible rather than assumed.
    """

    def __init__(self, answers: list[str]) -> None:
        super().__init__([], default=answers[-1])
        object.__setattr__(self, "answers", list(answers))
        object.__setattr__(self, "written", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        self.calls.append(content)
        if any(getattr(m, "type", "") == "tool" for m in messages):
            written = object.__getattribute__(self, "written")
            answers = object.__getattribute__(self, "answers")
            object.__setattr__(self, "written", written + 1)
            return self._reply(answers[min(written, len(answers) - 1)])
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "warehouse",
                                "args": {"sql": "SELECT product, port FROM voyages"},
                                "id": "call-1",
                            }
                        ],
                    )
                )
            ]
        )


class TestTheSummaryCarriesWhatCameBack:
    def _record(self) -> dict[str, Any]:
        return {
            "a1": {
                "ran": ["warehouse"],
                "calls": 1,
                "failed": 0,
                "queries": [
                    {
                        "sql": "SELECT product FROM voyages",
                        "tool": "warehouse",
                        "result": ROWS,
                    }
                ],
            }
        }

    def test_a_row_names_its_node_tool_statement_and_result(self) -> None:
        retrieved = summarise_run(self._record()).retrieved
        assert len(retrieved) == 1
        row = retrieved[0]
        assert row.node == "a1"
        assert row.tool == "warehouse"
        assert row.statement == "SELECT product FROM voyages"
        assert row.result == ROWS
        assert row.truncated is False

    def test_a_record_with_no_queries_carries_no_rows(self) -> None:
        assert summarise_run({"a1": {"calls": 1, "failed": 1}}).retrieved == ()

    def test_a_credential_in_a_statement_is_redacted(self) -> None:
        record = self._record()
        record["a1"]["queries"][0]["sql"] = "-- password=hunter2\nSELECT 1"
        assert "hunter2" not in summarise_run(record).retrieved[0].statement

    def test_containment_finds_a_value_a_row_carries(self) -> None:
        assert summarise_run(self._record()).contains("Naphtha") is True

    def test_containment_refuses_a_value_no_row_carries(self) -> None:
        assert summarise_run(self._record()).contains("Naphtra") is False

    def test_containment_is_blind_to_case_and_thousands_separators(self) -> None:
        record = self._record()
        record["a1"]["queries"][0]["result"] = "count\n1454449"
        summary = summarise_run(record)
        assert summary.contains("1,454,449") is True
        assert summary.contains("NAPHTHA") is False

    def test_containment_of_nothing_is_false(self) -> None:
        assert summarise_run(self._record()).contains("   ") is False

    def test_a_truncated_row_says_so(self) -> None:
        record = self._record()
        record["a1"]["queries"][0]["truncated"] = True
        summary = summarise_run(record)
        assert summary.retrieved[0].truncated is True
        assert summary.any_truncated is True

    def test_an_untruncated_run_says_so(self) -> None:
        assert summarise_run(self._record()).any_truncated is False


class TestTheGuardSendsBackAFigureNoRowCarries:
    """The live shape, driven through a real graph rather than seeded state.

    `_input` resets every per-run channel at the turn boundary, so a `tool_use`
    handed to `invoke` is erased before any node reads it — the reason
    `osg-agent-experience/50`'s own test drives an agent too.
    """

    def _document(self) -> dict[str, Any]:
        return {
            "version": 2,
            "name": "guard-rows",
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "t1", "type": "tool.web-search", "position": {"x": 0, "y": 120}, "data": {}},
                {"id": "a1", "type": "agent.llm", "position": {"x": 200, "y": 0}, "data": {}},
                {
                    "id": "g1",
                    "type": "guard.check",
                    "position": {"x": 400, "y": 0},
                    "data": {"check": "grounded", "maxAttempts": 2},
                },
                {"id": "out1", "type": "output.formatted", "position": {"x": 600, "y": 0}, "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"},
                 "target": {"nodeId": "a1", "portId": "prompt"}},
                {"source": {"nodeId": "t1", "portId": "tool"},
                 "target": {"nodeId": "a1", "portId": "tools"}},
                {"source": {"nodeId": "a1", "portId": "result"},
                 "target": {"nodeId": "g1", "portId": "candidate"}},
                {"source": {"nodeId": "g1", "portId": "pass"},
                 "target": {"nodeId": "out1", "portId": "result"}},
                {"source": {"nodeId": "g1", "portId": "revise"},
                 "target": {"nodeId": "a1", "portId": "feedback"}},
            ],
        }

    def _drive(self, answers: list[str], fn: Any) -> tuple[dict[str, Any], _Analyst]:
        model = _Analyst(answers)
        runtime = NodeRuntime(
            model=model,
            tools={"tool.web-search": _Warehouse()},
            functions={"function.grounded": fn},
        )
        graph = WorkflowCompiler().build(
            self._document(), RunState, runtime.factory(self._document())
        )
        final = graph.invoke(
            {"question": "which products moved", "attempts": 0, "decisions": {}, "outputs": {}},
            {"recursion_limit": 30},
        )
        return final, model

    @staticmethod
    def _grounded(text: str, summary: RunSummary) -> str:
        """A check nobody could write against the text alone."""
        for word in ("Naphtha", "Naphtra"):
            if word in text and not summary.contains(word):
                return f'"{word}" is in the answer and in no result this run retrieved.'
        return ""

    def test_the_answer_is_sent_back_with_the_value_named(self) -> None:
        final, model = self._drive([MISSPELT, GROUNDED], self._grounded)
        # The guard judged twice, so it sent the first candidate back.
        assert final["revisions"]["g1"] == 2
        # And what it sent back named the value, in the agent's own next turn.
        named = [seen for seen in model.calls if "in no result this run retrieved" in seen]
        assert named, model.calls
        assert '"Naphtra"' in named[0]

    def test_the_grounded_answer_is_what_gets_published(self) -> None:
        final, _ = self._drive([MISSPELT, GROUNDED], self._grounded)
        assert final["decisions"]["g1"] == "pass"
        assert final["answer"] == GROUNDED

    def test_a_grounded_answer_is_never_sent_back(self) -> None:
        final, _ = self._drive([GROUNDED], self._grounded)
        assert final["revisions"]["g1"] == 1
        assert final["decisions"]["g1"] == "pass"
        assert "g1" not in (final.get("forced") or {})

    def test_a_one_argument_check_is_still_called_with_one_argument(self) -> None:
        """The convention is extended, never widened (`osg-agent-experience/59`)."""
        seen: list[str] = []

        def spelling(text: str) -> str:
            seen.append(text)
            return ""

        final, _ = self._drive([MISSPELT], spelling)
        assert seen == [MISSPELT]
        assert final["decisions"]["g1"] == "pass"
