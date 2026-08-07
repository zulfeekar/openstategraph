"""Function nodes (ticket 35) and the subgraph node (ticket 34).

A *function* is a deterministic graph step with no model — the counterpart of
a model-callable tool. Discovery could already list them; these tests pin the
half that was missing: a listed function becoming an executable node.

A *subgraph* is another workflow compiled and invoked as one node — the
mechanism that makes "workflow composition = subgraphs" true. State mapping
is explicit: the child receives the parent's upstream text as its question,
and only its final answer flows back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dyflow.api.capability_discovery import discover_function_callables
from dyflow.compile.node_runtime import NodeRuntime, RunState
from dyflow.compile.workflow_compiler import WorkflowCompiler

REPO = Path(__file__).resolve().parent.parent.parent


def _make_functions_workflow(tmp_path: Path) -> Path:
    workflow = tmp_path / "fn-flow"
    (workflow / "functions").mkdir(parents=True)
    (workflow / "functions" / "shout.py").write_text(
        'def shout(text: str) -> str:\n    """Uppercases its input."""\n    return text.upper()\n'
        "\n\ndef _private(text: str) -> str:\n    return text\n"
    )
    return workflow


class TestFunctionDiscovery:
    def test_callables_are_keyed_by_their_node_type(self, tmp_path: Path) -> None:
        registry = discover_function_callables(_make_functions_workflow(tmp_path), slug="fn-flow")
        assert set(registry) == {"function.shout"}
        assert registry["function.shout"]("hi") == "HI"

    def test_a_workflow_without_functions_is_empty(self, tmp_path: Path) -> None:
        (tmp_path / "bare").mkdir()
        assert discover_function_callables(tmp_path / "bare", slug="bare") == {}


class TestFunctionNode:
    @staticmethod
    def _document(fn_type: str) -> dict:
        return {
            "version": 2,
            "name": "fn-test",
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "f1", "type": fn_type, "position": {"x": 200, "y": 0}, "data": {}},
                {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "f1", "portId": "candidate"}},
                {"source": {"nodeId": "f1", "portId": "report"}, "target": {"nodeId": "out1", "portId": "result"}},
            ],
        }

    def test_a_discovered_function_executes_as_a_graph_step(self) -> None:
        document = self._document("function.shout")
        runtime = NodeRuntime(functions={"function.shout": lambda text: text.upper()})
        compiler = WorkflowCompiler()
        graph = compiler.build(document, RunState, runtime.factory(document))
        final = graph.invoke({"question": "hello world", "attempts": 0, "decisions": {}, "outputs": {}})
        assert final["answer"] == "HELLO WORLD"

    def test_a_function_that_raises_becomes_readable_output_not_a_crash(self) -> None:
        def boom(text: str) -> str:
            raise ValueError("nope")

        document = self._document("function.boom")
        runtime = NodeRuntime(functions={"function.boom": boom})
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke({"question": "x", "attempts": 0, "decisions": {}, "outputs": {}})
        # set_node_defaults' error handler formats the failure into outputs.
        assert "boom" in " ".join(final.get("outputs", {}).keys()) or any(
            "ValueError" in v for v in final.get("outputs", {}).values()
        )

    def test_an_unregistered_function_type_is_a_loud_warning(self) -> None:
        document = self._document("function.ghost")
        runtime = NodeRuntime(functions={})
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke({"question": "x", "attempts": 0, "decisions": {}, "outputs": {}})
        assert "function.ghost" in runtime.unresolved_functions
        # The step degrades to passthrough rather than killing the run.
        assert final["answer"] == "x"


class TestSubgraphNode:
    CHILD = {
        "version": 2,
        "name": "child",
        "nodes": [
            {"id": "cin", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "cout", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "cin", "portId": "text"}, "target": {"nodeId": "cout", "portId": "result"}}
        ],
    }

    @staticmethod
    def _parent() -> dict:
        return {
            "version": 2,
            "name": "parent",
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
                {
                    "id": "sub1",
                    "type": "workflow.subgraph",
                    "position": {"x": 200, "y": 0},
                    "data": {"workflow": "child-flow"},
                },
                {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "sub1", "portId": "candidate"}},
                {"source": {"nodeId": "sub1", "portId": "report"}, "target": {"nodeId": "out1", "portId": "result"}},
            ],
        }

    def test_a_child_workflow_runs_as_one_node(self) -> None:
        loader = {"child-flow": self.CHILD}
        runtime = NodeRuntime(document_loader=loader.__getitem__)
        document = self._parent()
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke({"question": "flows through", "attempts": 0, "decisions": {}, "outputs": {}})
        assert final["answer"] == "flows through"

    def test_a_workflow_that_includes_itself_is_refused_at_build_time(self) -> None:
        recursive_child = json.loads(json.dumps(self.CHILD))
        recursive_child["nodes"].append(
            {
                "id": "csub",
                "type": "workflow.subgraph",
                "position": {"x": 100, "y": 100},
                "data": {"workflow": "child-flow"},
            }
        )
        recursive_child["edges"] = [
            {"source": {"nodeId": "cin", "portId": "text"}, "target": {"nodeId": "csub", "portId": "candidate"}},
            {"source": {"nodeId": "csub", "portId": "report"}, "target": {"nodeId": "cout", "portId": "result"}},
        ]
        loader = {"child-flow": recursive_child}
        runtime = NodeRuntime(document_loader=loader.__getitem__)
        document = self._parent()
        with pytest.raises(ValueError, match="child-flow"):
            WorkflowCompiler().build(document, RunState, runtime.factory(document))

    def test_a_missing_loader_degrades_loudly_not_silently(self) -> None:
        runtime = NodeRuntime()  # no document_loader
        document = self._parent()
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke({"question": "q", "attempts": 0, "decisions": {}, "outputs": {}})
        assert "child-flow" in " ".join(runtime.unresolved_subgraphs)
        assert final.get("outputs", {}).get("sub1", "") == ""
