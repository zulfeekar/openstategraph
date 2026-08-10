"""The adoption interface (ticket 08) end of `load_workflow`.

Three additions, each purely additive and each defaulting to today's behaviour:

- `.ask()` now returns a `RunResult` — a `str` subclass, so nothing that
  consumed the old return value can notice, while `.decisions` / `.outputs` /
  `.warnings` / `.attempts` stop requiring a drop to `.graph.invoke()` with
  hand-seeded state.
- `knowledge_dir=` / `trace_file=`, the explicit overrides for the two things
  that were convention-only. Convention stays the default, which is what the
  first test of each pair pins.
- `.as_tool()`, so a team's *existing* `create_agent` can call a workflow.

`test_run_result.py` owns the string-ness proof; this module owns the wiring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph import RunResult, load_workflow


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


LINEAR = {
    "version": 2,
    "name": "Billing Analyst",
    "nodes": [node("in1", "input.text"), node("out1", "output.formatted")],
    "edges": [edge("in1", "text", "out1", "result")],
}


def write(root: Path, slug: str, document: dict[str, Any] = LINEAR) -> Path:
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": slug, "savedAt": "", "document": document})
    )
    return directory


class TestAskReturnsARunResult:
    def test_it_is_still_the_answer_string(self, tmp_path: Path) -> None:
        answer = load_workflow(write(tmp_path, "linear-pkg")).ask("hello")

        assert answer == "hello"
        assert isinstance(answer, str)

    def test_and_it_is_a_run_result(self, tmp_path: Path) -> None:
        answer = load_workflow(write(tmp_path, "linear-pkg")).ask("hello")

        assert isinstance(answer, RunResult)
        assert answer.decisions == {}
        assert answer.outputs == {"in1": "hello", "out1": "hello"}
        assert answer.attempts == 0

    def test_the_workflows_warnings_ride_along(self, tmp_path: Path) -> None:
        """A caller checking one run should not have to keep the workflow
        object around to find out the run was degraded."""
        document = {
            **LINEAR,
            "nodes": [*LINEAR["nodes"], node("t1", "tool.nowhere")],
        }
        workflow = load_workflow(write(tmp_path, "warned-pkg", document))

        answer = workflow.ask("hello")

        assert answer.warnings == workflow.warnings


class TestTheTraceFile:
    def test_no_trace_by_default(self, tmp_path: Path) -> None:
        workflow = load_workflow(write(tmp_path, "linear-pkg"))

        assert workflow.trace_file is None

    def test_one_json_line_per_run(self, tmp_path: Path) -> None:
        trace = tmp_path / "runs.jsonl"
        workflow = load_workflow(write(tmp_path, "linear-pkg"), trace_file=trace)

        workflow.ask("first")
        workflow.ask("second")

        lines = [json.loads(line) for line in trace.read_text().splitlines()]
        assert [entry["question"] for entry in lines] == ["first", "second"]
        assert lines[0]["slug"] == "linear-pkg"
        assert lines[0]["attempts"] == 0 and lines[0]["decisions"] == {}
        assert isinstance(lines[0]["seconds"], float)

    def test_the_answer_text_is_never_written_only_its_length(self, tmp_path: Path) -> None:
        """A trace gets committed, emailed and pasted into issues. The answer
        is the one field of a run that reliably carries a customer's data, so
        the line records how long it was and never what it said."""
        trace = tmp_path / "runs.jsonl"

        load_workflow(write(tmp_path, "linear-pkg"), trace_file=trace).ask("swordfish")

        entry = json.loads(trace.read_text().splitlines()[0])
        assert "answer" not in entry
        assert entry["answer_chars"] == len("swordfish")

    def test_it_creates_the_parent_directory(self, tmp_path: Path) -> None:
        trace = tmp_path / "nested" / "deeper" / "runs.jsonl"

        load_workflow(write(tmp_path, "linear-pkg"), trace_file=trace).ask("hi")

        assert trace.is_file()

    def test_an_unwritable_path_warns_and_the_run_still_answers(
        self, tmp_path: Path, caplog
    ) -> None:
        """Losing the diagnostics must never lose the run that produced them."""
        blocked = tmp_path / "linear-pkg" / "workflow.json" / "runs.jsonl"
        workflow = load_workflow(write(tmp_path, "linear-pkg"), trace_file=blocked)

        with caplog.at_level("WARNING", logger="openstategraph.loader"):
            answer = workflow.ask("still fine")

        assert answer == "still fine"
        assert any("trace" in record.getMessage() for record in caplog.records)


KNOWLEDGE_DOCUMENT = {
    "version": 2,
    "name": "knows-things",
    "nodes": [
        node("in1", "input.text"),
        node("ag1", "agent.llm", systemPrompt="Answer."),
        node("k1", "tool.knowledge-lookup"),
        node("out1", "output.formatted"),
    ],
    "edges": [
        edge("in1", "text", "ag1", "prompt"),
        edge("k1", "tool", "ag1", "tools"),
        edge("ag1", "result", "out1", "result"),
    ],
}


def bound_knowledge_topics(package: Path, slug: str, knowledge_dir: Path | None = None) -> list[str]:
    """The topics the lookup tool would actually serve for this run."""
    from openstategraph.api.registries import build_tool_registry
    from openstategraph.api.workflow_store import WorkflowStore
    from openstategraph.prebuilt_knowledge import KnowledgeLookupTool

    registry = build_tool_registry(
        WorkflowStore(root=package.parent), slug, knowledge_dir=knowledge_dir
    )
    tool = registry[KnowledgeLookupTool.node_type]
    return [entry.name for entry in tool._knowledge.topics()]


class TestTheKnowledgeDirOverride:
    """Convention is the default; the override is for what convention cannot
    say — knowledge shared between packages, or outside the repository."""

    @pytest.fixture
    def fake_model(self) -> Any:
        from conftest import RespondingModel

        return RespondingModel(rules=[], default="fine")

    def test_by_default_it_is_the_packages_own_knowledge(
        self, tmp_path: Path, fake_model
    ) -> None:
        package = write(tmp_path, "knows-pkg", KNOWLEDGE_DOCUMENT)
        (package / "knowledge").mkdir()
        (package / "knowledge" / "own-topic.md").write_text("# mine")

        workflow = load_workflow(package, model=fake_model)

        assert workflow.warnings == []
        assert bound_knowledge_topics(package, workflow.slug) == ["own-topic"]

    def test_an_explicit_directory_replaces_it(self, tmp_path: Path, fake_model) -> None:
        package = write(tmp_path, "knows-pkg", KNOWLEDGE_DOCUMENT)
        (package / "knowledge").mkdir()
        (package / "knowledge" / "own-topic.md").write_text("# mine")
        shared = tmp_path / "shared-brain"
        shared.mkdir()
        (shared / "shared-topic.md").write_text("# shared, one sentence")

        workflow = load_workflow(package, model=fake_model, knowledge_dir=shared)

        assert workflow.warnings == []
        assert bound_knowledge_topics(package, workflow.slug, shared) == ["shared-topic"]

    def test_the_ambient_rule_follows_the_override(self, tmp_path: Path) -> None:
        """A non-empty knowledge directory auto-binds the lookup tool. The
        override has to move *that* too, or half the feature reads one place
        and half reads another."""
        from openstategraph.prebuilt_knowledge import ambient_knowledge_tool

        package = tmp_path / "pkg"
        (package / "knowledge").mkdir(parents=True)
        shared = tmp_path / "shared"
        shared.mkdir()

        assert ambient_knowledge_tool(package) is None
        assert ambient_knowledge_tool(package, knowledge_dir=shared) is None

        (shared / "topic.md").write_text("# there")
        assert ambient_knowledge_tool(package, knowledge_dir=shared) is not None


class TestAsTool:
    """The team already on `create_agent`, who does not want to restructure."""

    def test_it_is_a_langchain_structured_tool(self, tmp_path: Path) -> None:
        from langchain_core.tools import StructuredTool

        tool = load_workflow(write(tmp_path, "billing")).as_tool()

        assert isinstance(tool, StructuredTool)

    def test_one_string_argument_named_question(self, tmp_path: Path) -> None:
        tool = load_workflow(write(tmp_path, "billing")).as_tool()

        schema = tool.args_schema.model_json_schema()
        assert list(schema["properties"]) == ["question"]
        assert schema["properties"]["question"]["type"] == "string"

    def test_invoking_it_runs_the_workflow_and_returns_the_answer(self, tmp_path: Path) -> None:
        tool = load_workflow(write(tmp_path, "billing")).as_tool()

        assert tool.invoke({"question": "how many invoices"}) == "how many invoices"

    def test_the_name_and_description_are_the_callers(self, tmp_path: Path) -> None:
        tool = load_workflow(write(tmp_path, "billing")).as_tool(
            name="billing_analyst", description="Invoices and revenue."
        )

        assert tool.name == "billing_analyst"
        assert tool.description == "Invoices and revenue."

    def test_unnamed_it_still_describes_itself(self, tmp_path: Path) -> None:
        """A tool the calling model cannot tell apart from any other is a tool
        it will not call — so the document's own name is the fallback."""
        tool = load_workflow(write(tmp_path, "billing")).as_tool()

        assert tool.name == "billing"
        assert "Billing Analyst" in tool.description

    def test_a_slug_with_hyphens_becomes_a_legal_tool_name(self, tmp_path: Path) -> None:
        tool = load_workflow(write(tmp_path, "billing-analyst")).as_tool()

        assert tool.name == "billing_analyst"

    def test_each_call_is_its_own_conversation(self, tmp_path: Path) -> None:
        """Subagent isolation, pinned: the workflow sees the question and
        nothing else, and two calls never continue each other."""
        workflow = load_workflow(write(tmp_path, "billing"))
        tool = workflow.as_tool()

        first = tool.invoke({"question": "one"})
        second = tool.invoke({"question": "two"})

        assert (first, second) == ("one", "two")

    def test_we_wrap_langchain_rather_than_subclassing_it(self, tmp_path: Path) -> None:
        """CLAUDE.md's rule, and `abc/tool.py`'s existing pattern: adaptation
        happens at the seam so an upstream change cannot reach into us."""
        from langchain_core.tools import BaseTool as LangChainBaseTool

        from openstategraph.loader import CompiledWorkflow

        assert not issubclass(CompiledWorkflow, LangChainBaseTool)
