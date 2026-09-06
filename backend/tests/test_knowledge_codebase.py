"""CodebaseKnowledgeBuilder — agentic, openwiki-shaped, first-party, jailed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from openstategraph.knowledge_builders import GENERATED_MARKER, marker_source
from openstategraph.knowledge_explorer import (
    CodebaseKnowledgeBuilder,
    CodeGrepTool,
    CodeLsTool,
    CodeReadTool,
)


class ToolCallingScriptedModel(GenericFakeChatModel):
    def __init__(self, messages: list[AIMessage]):
        super().__init__(messages=iter(messages))

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return self


def _fake_package(tmp_path: Path, slug: str = "code-flow") -> Path:
    package = tmp_path / slug
    (package / "tools").mkdir(parents=True)
    (package / "functions").mkdir()
    (package / "tools" / "csv_probe.py").write_text(
        '"""Reads CSV headers."""\n\nclass CsvProbe:\n    pass\n'
    )
    (package / "tools" / "http_probe.py").write_text(
        '"""Fetches JSON endpoints."""\n\ndef fetch(url):\n    return url\n'
    )
    (package / "functions" / "shape.py").write_text(
        '"""Reshapes rows into a report."""\n\ndef shape(rows):\n    return rows\n'
    )
    (package / "workflow.json").write_text(
        json.dumps({"version": 1, "document": {"nodes": [], "edges": []}})
    )
    return package


class TestSourceRoots:
    def test_the_package_code_dirs_are_the_default_roots(self, tmp_path: Path) -> None:
        package = _fake_package(tmp_path)
        tools, _prov, warnings = CodebaseKnowledgeBuilder().study_tools(
            package, {"nodes": [], "edges": []}, tmp_path
        )
        assert warnings == []
        assert [t.name for t in tools] == ["code_ls", "code_read", "code_grep"]

    def test_no_code_means_no_exploration(self, tmp_path: Path) -> None:
        package = tmp_path / "empty-flow"
        package.mkdir()
        tools, _prov, _w = CodebaseKnowledgeBuilder().study_tools(
            package, {"nodes": [], "edges": []}, tmp_path
        )
        assert tools == []

    def test_an_extra_root_outside_the_repo_is_a_warning_never_a_read(
        self, tmp_path: Path
    ) -> None:
        package = _fake_package(tmp_path)
        document = {"nodes": [], "edges": [], "settings": {"knowledgeCodeRoot": "../../etc"}}
        tools, _prov, warnings = CodebaseKnowledgeBuilder().study_tools(
            package, document, tmp_path
        )
        assert warnings and "knowledgeCodeRoot" in warnings[0]
        assert [t.name for t in tools] == ["code_ls", "code_read", "code_grep"]

    def test_a_valid_extra_root_inside_the_repo_is_added(self, tmp_path: Path) -> None:
        package = _fake_package(tmp_path)
        shared = tmp_path.parent / "shared_lib"  # workflows_root.parent is the repo root
        shared.mkdir(exist_ok=True)
        (shared / "util.py").write_text('"""Shared util."""\n')
        document = {"nodes": [], "edges": [], "settings": {"knowledgeCodeRoot": "shared_lib"}}
        _tools, _prov, warnings = CodebaseKnowledgeBuilder().study_tools(
            package, document, tmp_path
        )
        assert warnings == []


class TestJailedCodeTools:
    def test_read_is_jailed_to_the_roots(self, tmp_path: Path) -> None:
        package = _fake_package(tmp_path)
        (tmp_path / "secret.txt").write_text("outside")
        read = CodeReadTool([package / "tools"], set())
        assert read.run(path="csv_probe.py").ok
        escape = read.run(path="../../secret.txt")
        assert not escape.ok
        dotted = read.run(path=".env")
        assert not dotted.ok

    def test_ls_and_grep_cover_only_the_roots(self, tmp_path: Path) -> None:
        package = _fake_package(tmp_path)
        roots = [package / "tools", package / "functions"]
        listing = CodeLsTool(roots, set()).run()
        assert "csv_probe.py" in listing.content and "shape.py" in listing.content
        assert "workflow.json" not in listing.content
        grep = CodeGrepTool(roots, set()).run(pattern="reshapes")
        assert "shape.py" in grep.content

    def test_reads_are_recorded_for_provenance(self, tmp_path: Path) -> None:
        package = _fake_package(tmp_path)
        files_read: set[str] = set()
        CodeReadTool([package / "tools"], files_read).run(path="csv_probe.py")
        assert files_read == {"csv_probe.py"}


class TestScriptedCodebaseBuild:
    def _model(self) -> ToolCallingScriptedModel:
        return ToolCallingScriptedModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "code_read", "args": {"path": "csv_probe.py"}, "id": "c1"}
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_topic",
                            "args": {
                                "topic": "csv-probe",
                                "content": (
                                    "csv-probe — reads CSV headers for the workflow.\n\n"
                                    "## Responsibilities\n- header probing\n\n"
                                    "## Key files\n- tools/csv_probe.py\n\n"
                                    "## Relationships\n- used by agents\n\n"
                                    "## Caveats\n- none"
                                ),
                            },
                            "id": "c2",
                        }
                    ],
                ),
                AIMessage(content="Did not cover functions/shape.py."),
            ]
        )

    def test_a_scripted_build_writes_an_openwiki_shaped_doc_with_provenance(
        self, tmp_path: Path
    ) -> None:
        package = _fake_package(tmp_path)
        report = CodebaseKnowledgeBuilder().explore(
            package, {"nodes": [], "edges": []}, tmp_path, self._model()
        )
        assert report.written == ["csv-probe"]
        assert report.uncovered == ["Did not cover functions/shape.py."]
        doc = (package / "knowledge" / "csv-probe.md").read_text()
        assert doc.startswith(GENERATED_MARKER)
        assert marker_source(doc) == "codebase"
        assert "## Responsibilities" in doc and "## Key files" in doc
        # provenance lists the files actually read before the write
        assert "Provenance" in doc and "csv_probe.py" in doc

    def test_a_topic_owned_by_sql_is_refused(self, tmp_path: Path) -> None:
        package = _fake_package(tmp_path)
        knowledge = package / "knowledge"
        knowledge.mkdir()
        (knowledge / "csv-probe.md").write_text(
            f"{GENERATED_MARKER} source=sql -->\nsql's table doc\n"
        )
        report = CodebaseKnowledgeBuilder().explore(
            package, {"nodes": [], "edges": []}, tmp_path, self._model()
        )
        assert report.written == []
        assert report.collisions and "'sql'" in report.collisions[0]
        assert "sql's table doc" in (knowledge / "csv-probe.md").read_text()

    def test_the_mission_demands_the_openwiki_shape(self) -> None:
        mission = CodebaseKnowledgeBuilder.MISSION
        for heading in ("Responsibilities", "Key files", "Relationships", "Caveats"):
            assert heading in mission
