"""`openstategraph.load_workflow` — the one public seam for artifact mode.

The bug this module exists to prevent was found live, not hypothetically.
The snippet `docs/adoption.md` used to print —

    runtime = NodeRuntime(model=init_chat_model(...))
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

— compiles, runs, and answers. It also never wires the package's own
`tools/`: `UNRESOLVED_TOOL` findings came back with all three Chinook tools
and the agent replied "we need to call chinook_list_tables" instead of
querying anything. A workflow that looks like it works and answers nothing is
exactly the failure this codebase treats as the worst kind, and the correct
wiring (`WorkflowServices` + `runtime_for` + `store=`) is far too much
ceremony to ask of a consumer. So the ceremony moved behind one function, and
these tests pin the two things a consumer cannot verify by reading:
capabilities are actually resolved, and the ones that are not are *loud*.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openstategraph import CompiledWorkflow, load_workflow


TOOL_SOURCE = '''\
from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult


class EchoTool(BaseTool):
    name = "echo"
    description = "Returns a fixed string."
    node_type = "tool.demo-echo"
    # An echo reads nothing and changes nothing, and says so —
    # `launch-readiness` 121. Declared here because these fixtures stand in
    # for an adopter's `tools/*.py`, and this is the one line an adopter
    # writes to keep a correct graph quiet.
    side_effecting = False
    Args = NoArgs

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="echoed")
'''


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def write_package(
    root: Path,
    slug: str,
    document: dict[str, Any],
    *,
    tool_source: str | None = None,
) -> Path:
    """A real package on disk — envelope, and optionally a real `tools/` file."""
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    envelope = {"version": 1, "name": slug, "savedAt": "", "document": document}
    (directory / "workflow.json").write_text(json.dumps(envelope, indent=2))
    if tool_source is not None:
        (directory / "tools").mkdir(exist_ok=True)
        (directory / "tools" / "echo.py").write_text(tool_source)
    return directory


def agent_document(tool_type: str | None) -> dict[str, Any]:
    nodes = [
        node("in1", "input.text"),
        node("ag1", "agent.llm", systemPrompt="Answer."),
        node("out1", "output.formatted"),
    ]
    edges = [
        edge("in1", "text", "ag1", "prompt"),
        edge("ag1", "result", "out1", "result"),
    ]
    if tool_type is not None:
        nodes.append(node("t1", tool_type))
        edges.append(edge("t1", "tool", "ag1", "tools"))
    return {"version": 1, "name": "demo", "nodes": nodes, "edges": edges}


LINEAR_DOCUMENT = {
    "version": 1,
    "name": "linear",
    "nodes": [node("in1", "input.text"), node("out1", "output.formatted")],
    "edges": [edge("in1", "text", "out1", "result")],
}


@pytest.fixture
def fake_model() -> Any:
    from conftest import RespondingModel

    return RespondingModel(rules=[], default="fine")


class TestCapabilityWiring:
    """The verified finding, pinned: a package's own tools must resolve."""

    def test_a_packages_own_tools_module_is_wired(self, tmp_path: Path, fake_model) -> None:
        package = write_package(
            tmp_path, "demo-pkg", agent_document("tool.demo-echo"), tool_source=TOOL_SOURCE
        )

        loaded = load_workflow(package, model=fake_model)

        assert loaded.warnings == []

    def test_a_missing_tool_is_a_warning_not_an_exception(
        self, tmp_path: Path, fake_model
    ) -> None:
        package = write_package(tmp_path, "demo-pkg", agent_document("tool.nowhere"))

        loaded = load_workflow(package, model=fake_model)

        assert any("tool.nowhere" in w for w in loaded.warnings)

    def test_unresolved_capabilities_are_logged_once_at_warning(
        self, tmp_path: Path, fake_model, caplog
    ) -> None:
        package = write_package(tmp_path, "demo-pkg", agent_document("tool.nowhere"))

        with caplog.at_level("WARNING", logger="openstategraph.loader"):
            load_workflow(package, model=fake_model)

        assert any("tool.nowhere" in record.getMessage() for record in caplog.records)


class TestPackageDerivation:
    def test_slug_and_root_come_from_the_directory_the_consumer_passes(
        self, tmp_path: Path, fake_model
    ) -> None:
        package = write_package(tmp_path, "demo-pkg", agent_document(None))

        loaded = load_workflow(package, model=fake_model)

        assert loaded.slug == "demo-pkg"
        assert loaded.package_dir == package.resolve()

    def test_a_string_path_is_accepted(self, tmp_path: Path, fake_model) -> None:
        package = write_package(tmp_path, "demo-pkg", agent_document(None))

        assert load_workflow(str(package), model=fake_model).slug == "demo-pkg"

    def test_a_directory_without_workflow_json_says_so(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()

        with pytest.raises(FileNotFoundError) as excinfo:
            load_workflow(tmp_path / "empty")

        assert "workflow.json" in str(excinfo.value)

    def test_a_directory_name_that_cannot_be_a_slug_is_refused_loudly(
        self, tmp_path: Path
    ) -> None:
        directory = tmp_path / "My Package"
        directory.mkdir()
        (directory / "workflow.json").write_text(json.dumps({"document": LINEAR_DOCUMENT}))

        with pytest.raises(ValueError) as excinfo:
            load_workflow(directory)

        assert "my-package" in str(excinfo.value)


class TestRunning:
    def test_ask_returns_the_answer_for_a_model_free_document(self, tmp_path: Path) -> None:
        package = write_package(tmp_path, "linear-pkg", LINEAR_DOCUMENT)

        loaded = load_workflow(package)

        assert loaded.ask("the input text") == "the input text"

    def test_mermaid_is_text_and_needs_no_network(self, tmp_path: Path) -> None:
        package = write_package(tmp_path, "linear-pkg", LINEAR_DOCUMENT)

        mermaid = load_workflow(package).mermaid()

        assert "graph" in mermaid or "flowchart" in mermaid

    def test_graph_is_the_escape_hatch(self, tmp_path: Path) -> None:
        package = write_package(tmp_path, "linear-pkg", LINEAR_DOCUMENT)

        loaded = load_workflow(package)

        assert isinstance(loaded, CompiledWorkflow)
        assert hasattr(loaded.graph, "invoke")


class TestImportCost:
    def test_importing_the_package_does_not_import_langgraph(self) -> None:
        """A consumer's `import openstategraph` must stay cheap and side-effect
        free — the heavy runtime arrives when they call `load_workflow`, not
        when they import the name."""
        source = (
            "import sys; import openstategraph; "
            "print(any(m == 'langgraph' or m.startswith('langgraph.') "
            "or m == 'langchain' or m.startswith('langchain.') for m in sys.modules))"
        )
        result = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            # A hung child hangs the whole run; CI has no one to notice.
            timeout=120,
            cwd=str(Path(__file__).resolve().parents[1]),
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"

    def test_load_workflow_does_not_pull_in_a_web_framework(self, tmp_path: Path) -> None:
        """A consumer runs a graph in-process; they must not have to install
        FastAPI to do it. Documented in `docs/adoption.md`, verified here."""
        package = write_package(tmp_path, "linear-pkg", LINEAR_DOCUMENT)
        source = (
            "import sys; from openstategraph import load_workflow; "
            f"load_workflow({str(package)!r}); "
            "print('fastapi' in sys.modules or 'uvicorn' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            # A hung child hangs the whole run; CI has no one to notice.
            timeout=120,
            cwd=str(Path(__file__).resolve().parents[1]),
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"

    def test_load_workflow_touches_no_extra_it_did_not_need(self, tmp_path: Path) -> None:
        """Every package behind an extra, pinned absent on the consumer path.

        This is the runtime half of `test_distribution_metadata.py`: metadata
        proves we do not *declare* them, this proves we do not *import* them.
        Both are needed — a lazy import that some module-scope line already
        triggered costs the adopter the install anyway, and only this test
        would notice.
        """
        package = write_package(tmp_path, "linear-pkg", LINEAR_DOCUMENT)
        extras = ["fastapi", "uvicorn", "deepagents", "mcp"]
        source = (
            "import sys; from openstategraph import load_workflow; "
            f"load_workflow({str(package)!r}); "
            f"print(sorted(m for m in {extras!r} if m in sys.modules))"
        )
        result = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            # A hung child hangs the whole run; CI has no one to notice.
            timeout=120,
            cwd=str(Path(__file__).resolve().parents[1]),
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "[]"
