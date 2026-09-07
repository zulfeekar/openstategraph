"""`osg-agent-experience/88`: the SQL a mount ran was recorded nowhere.

`runs.sqlite` carries a `statements` column — for each tool call, the node, the
tool, the statement and its result — and it is the only record of what a run
actually asked the warehouse. Five runs measured in one adopter's analyst workflow on
2026-09-06: the one flat workflow recorded its statement and its error; the
four that route through mounts recorded `[]`, including a 212,253-token run
that reached the warehouse and published a breakdown.

The seam is this compiler's own. A mount is a **closure** over the child's
`ainvoke`, not a LangGraph subgraph, so the child's state never merges into the
parent's — the mount decides key by key what crosses. `outputs`,
`nested_outputs`, `forced`, `unrouted`, `budget_stops` and `attempts` each
crossed, on the same argument every time (`every-workflow-green` 16: two doors
must not disagree about what happened inside a mount). `tool_use` did not, and
it is the one that carries the evidence — so `statements_executed`,
`summarise_run` and every grounding gate read a parent whose child had
apparently called nothing at all.

The cost is on the record: a card was filed saying a mounted run's zero came
from an unchecked literal, and closed on a rule rather than on a diagnosis,
because the statement that produced it could not be read.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from openstategraph.abc.tool import BaseTool, ToolResult
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.executed_statements import statements_executed
from openstategraph.run_summary import summarise_run

from conftest import RespondingModel

STATEMENT = "SELECT COUNT(*) FROM departures WHERE load_port = 'Mongstad'"
ROWS = "count\n771"
ANSWER = "771 departures left Mongstad in the window."


class _Args(BaseModel):
    sql: str = ""


class _Warehouse(BaseTool):
    name = "warehouse"
    description = "Run a read-only statement against the warehouse."
    Args = _Args

    def _execute(self, args: _Args) -> ToolResult:
        return ToolResult(content=ROWS)


class _Lens(RespondingModel):
    """Sends one statement, then reports what came back."""

    def __init__(self) -> None:
        super().__init__([], default=ANSWER)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        self.calls.append("\n".join(str(m.content) for m in messages))
        if any(getattr(m, "type", "") == "tool" for m in messages):
            return self._reply(self.default)
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "warehouse", "args": {"sql": STATEMENT}, "id": "c1"}
                        ],
                    )
                )
            ]
        )


#: The mounted lens: one agent, one warehouse tool, one statement.
CHILD: dict[str, Any] = {
    "version": 2,
    "name": "cargo-lens",
    "nodes": [
        {"id": "c-in", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "c-tool", "type": "tool.web-search", "position": {"x": 0, "y": 120}, "data": {}},
        {"id": "lens-sql", "type": "agent.llm", "position": {"x": 200, "y": 0}, "data": {}},
        {"id": "c-out", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {"source": {"nodeId": "c-in", "portId": "text"},
         "target": {"nodeId": "lens-sql", "portId": "prompt"}},
        {"source": {"nodeId": "c-tool", "portId": "tool"},
         "target": {"nodeId": "lens-sql", "portId": "tools"}},
        {"source": {"nodeId": "lens-sql", "portId": "result"},
         "target": {"nodeId": "c-out", "portId": "result"}},
    ],
}

PARENT: dict[str, Any] = {
    "version": 2,
    "name": "analyst",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "mount-cargo", "type": "workflow.subgraph", "position": {"x": 200, "y": 0},
         "data": {"workflow": "cargo-lens"}},
        {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {"source": {"nodeId": "in1", "portId": "text"},
         "target": {"nodeId": "mount-cargo", "portId": "candidate"}},
        {"source": {"nodeId": "mount-cargo", "portId": "report"},
         "target": {"nodeId": "out1", "portId": "result"}},
    ],
}

#: A second level, so the mount path is a path rather than one segment.
MIDDLE: dict[str, Any] = {
    "version": 2,
    "name": "middle",
    "nodes": [
        {"id": "m-in", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "mount-inner", "type": "workflow.subgraph", "position": {"x": 200, "y": 0},
         "data": {"workflow": "cargo-lens"}},
        {"id": "m-out", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {"source": {"nodeId": "m-in", "portId": "text"},
         "target": {"nodeId": "mount-inner", "portId": "candidate"}},
        {"source": {"nodeId": "mount-inner", "portId": "report"},
         "target": {"nodeId": "m-out", "portId": "result"}},
    ],
}


def _run(parent: dict[str, Any], library: dict[str, Any]) -> dict[str, Any]:
    runtime = NodeRuntime(
        model=_Lens(),
        tools={"tool.web-search": _Warehouse()},
        document_loader=library.__getitem__,
    )
    graph = WorkflowCompiler().build(parent, RunState, runtime.factory(parent))
    return graph.invoke(
        {"question": "how many departures", "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 30},
    )


class TestTheParentRecordsWhatItsMountRan:
    def test_the_statement_is_in_the_run_record(self) -> None:
        final = _run(PARENT, {"cargo-lens": CHILD})
        statements = statements_executed(final.get("tool_use"))
        assert [row["statement"] for row in statements] == [STATEMENT]
        assert statements[0]["result"] == ROWS
        assert statements[0]["tool"] == "warehouse"

    def test_the_statement_is_attributed_to_the_mount(self) -> None:
        final = _run(PARENT, {"cargo-lens": CHILD})
        assert statements_executed(final.get("tool_use"))[0]["node"] == "mount-cargo/lens-sql"

    def test_the_row_names_the_tool_the_child_reached(self) -> None:
        final = _run(PARENT, {"cargo-lens": CHILD})
        row = (final.get("tool_use") or {})["mount-cargo/lens-sql"]
        assert row["ran"] == ["warehouse"]
        assert row["calls"] == 1
        assert row["failed"] == 0

    def test_a_guard_at_the_parent_can_read_the_rows(self) -> None:
        """`osg-agent-experience/86`'s summary, over a composition."""
        summary = summarise_run(_run(PARENT, {"cargo-lens": CHILD}).get("tool_use"))
        assert summary.calls == 1
        assert summary.tools == ("warehouse",)
        assert summary.contains("771") is True

    def test_the_parents_own_record_is_untouched(self) -> None:
        """The mount writes no row of its own — it did not call a tool."""
        final = _run(PARENT, {"cargo-lens": CHILD})
        assert "mount-cargo" not in (final.get("tool_use") or {})

    def test_two_levels_deep_the_path_names_both_mounts(self) -> None:
        final = _run(
            {**PARENT, "nodes": [
                node if node["id"] != "mount-cargo"
                else {**node, "data": {"workflow": "middle"}}
                for node in PARENT["nodes"]
            ]},
            {"middle": MIDDLE, "cargo-lens": CHILD},
        )
        node = statements_executed(final.get("tool_use"))[0]["node"]
        assert node == "mount-cargo/mount-inner/lens-sql"


class TestTheFlatRunIsUnchanged:
    def test_a_workflow_that_mounts_nothing_records_its_own_statement(self) -> None:
        final = _run(CHILD, {})
        assert statements_executed(final.get("tool_use"))[0]["node"] == "lens-sql"
