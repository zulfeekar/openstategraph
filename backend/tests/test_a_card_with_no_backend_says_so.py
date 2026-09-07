"""A palette card whose type the backend cannot run says so before a run does.

`osg-agent-experience/72`. `tool.reddit-search` is a card like any other: the
editor's TypeScript half executes it, with labelled sample rows when Reddit
refuses a browser origin. The backend has no implementation at all, so a
*backend* run answers `No implementation for tool "tool.reddit-search"` on the
developer channel — after the model was paid — while `validate` said VALID,
`get_node_vocabulary` offered the type to a composing agent with no mark, and
`docs/modules.md` listed it beside the twenty that are real.

That is `CLAUDE.md`'s fourth-channel rule ("an id nothing resolves is reported
by name") honoured at the last possible moment instead of the first.

**Two instruments, and the split is deliberate.** The census here is derived
from the `*_TOOLS` registries `api/registries.py` assembles — never a literal
list — so the day a twenty-first card ships without a Python implementation
this file reddens. The *check* that `validate` runs reads the mark off the
catalogue instead: `validate` answers for documents posted to the stateless
MCP door, which holds no workflow library and must not walk every installed
distribution's entry points to answer a question about a document. The pin is
what keeps the mark honest; the mark is what keeps `validate` cheap.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.api.registries import build_tool_registry
from openstategraph.compile.node_catalogue import ARTIFACT_PATH, CATALOGUE
from openstategraph.document_checks import FindingClass, document_findings

#: The families this runtime executes by looking a node type up in a registry.
#: Every other category compiles to something the runtime builds itself.
_EXECUTED_CATEGORY = "tools"


def _tool_types() -> list[dict]:
    return [n for n in CATALOGUE.nodes if n["category"] == _EXECUTED_CATEGORY]


def _implemented() -> set[str]:
    """Every tool node type the backend can actually bind, from the registry."""
    return set(build_tool_registry(None, None))


class TestEveryExecutedTypeIsImplementedOrMarked:
    def test_the_census_is_derived_from_the_registries(self) -> None:
        implemented = _implemented()
        # Not an assertion about the number — a census that resolves to nothing
        # would pass every case below in silence.
        assert len(implemented) > 10

    def test_no_tool_card_is_both_unimplemented_and_unmarked(self) -> None:
        implemented = _implemented()
        unaccounted = [
            n["type"]
            for n in _tool_types()
            if n["type"] not in implemented and not n.get("editor_only")
        ]
        assert not unaccounted, (
            f"these tool types have no Python implementation in any `*_TOOLS` registry "
            f"and no `editorOnly` mark on their descriptor: {unaccounted}. A run finds "
            f"out last. Implement it, or declare `editorOnly: true` in `src/nodes/**` "
            f"and regenerate (`npm run generate:ports`)."
        )

    def test_the_mark_is_not_worn_by_a_type_that_does_have_one(self) -> None:
        implemented = _implemented()
        lying = [n["type"] for n in _tool_types() if n.get("editor_only") and n["type"] in implemented]
        assert not lying, (
            f"these types carry the editor-only mark and are implemented after all: {lying}"
        )

    def test_reddit_search_is_the_marked_one(self) -> None:
        marked = {n["type"] for n in CATALOGUE.nodes if n.get("editor_only")}
        assert "tool.reddit-search" in marked


class TestTheCatalogueSurfacesTheMark:
    def test_editor_only_is_a_derived_set(self) -> None:
        assert "tool.reddit-search" in CATALOGUE.editor_only
        assert "tool.email-send" not in CATALOGUE.editor_only


def _document(node_type: str) -> dict:
    return {
        "nodes": [
            {"id": "a", "type": "agent.llm", "data": {}},
            {"id": "t", "type": node_type, "data": {}},
        ],
        "edges": [
            {
                "id": "e1",
                "source": {"nodeId": "t", "portId": "tool"},
                "target": {"nodeId": "a", "portId": "tools"},
            }
        ],
    }


class TestValidateNamesThePlacedTypeBeforeARun:
    def test_a_placed_editor_only_type_is_a_finding(self) -> None:
        findings = document_findings(_document("tool.reddit-search"))
        no_backend = [f for f in findings if f.kind == FindingClass.NO_BACKEND]
        assert len(no_backend) == 1
        assert no_backend[0].subject == "t"
        assert "tool.reddit-search" in no_backend[0].message

    def test_an_implemented_type_is_not(self) -> None:
        findings = document_findings(_document("tool.email-send"))
        assert not [f for f in findings if f.kind == FindingClass.NO_BACKEND]


class TestTheWrongRemedyIsNotAlsoPrinted:
    """`unresolved_tool_bindings` already fired here, with a remedy that cannot work.

    It said *"Copy the package's tools/ folder next to workflow.json, or install
    the plugin that provides it"* — and there is no folder to copy and no plugin
    to install, because the implementation is TypeScript and was never on this
    side. One node now produces one finding, and it is the true one.
    """

    def test_an_editor_only_type_is_left_to_the_document_check(self, tmp_path: Path) -> None:
        from openstategraph.validation import unresolved_tool_bindings

        package = tmp_path / "sample"
        package.mkdir()
        findings = unresolved_tool_bindings(_document("tool.reddit-search"), package)
        assert findings == []

    def test_a_genuinely_absent_package_tool_is_still_named(self, tmp_path: Path) -> None:
        from openstategraph.validation import unresolved_tool_bindings

        package = tmp_path / "sample"
        package.mkdir()
        findings = unresolved_tool_bindings(_document("sample/tools.QueryTool"), package)
        assert len(findings) == 1
        assert "sample/tools.QueryTool" in findings[0]


class TestEveryDoorCarriesTheMark:
    def test_the_vocabulary_publishes_it(self) -> None:
        pytest.importorskip("mcp")
        from openstategraph.mcp_server import NodeVocabulary

        vocabulary = NodeVocabulary().describe()
        by_type = {n["type"]: n for n in vocabulary["node_types"]}
        assert by_type["tool.reddit-search"]["editor_only"] is True
        assert by_type["tool.email-send"]["editor_only"] is False

    def test_the_cli_detail_says_so(self) -> None:
        from openstategraph.node_report import node_detail_lines

        vocabulary = {
            "node_types": [
                {
                    "type": "tool.reddit-search",
                    "label": "Search Reddit",
                    "description": "Finds trending posts in a subreddit.",
                    "editor_only": True,
                    "fields": [],
                    "ports": [],
                }
            ]
        }
        lines = node_detail_lines(vocabulary, "tool.reddit-search")
        assert lines is not None
        assert any("editor" in line.lower() and "sample" in line.lower() for line in lines)

    def test_the_generated_module_index_marks_the_row(self) -> None:
        page = (Path(__file__).resolve().parents[2] / "docs" / "modules.md").read_text(
            encoding="utf-8"
        )
        row = next(line for line in page.splitlines() if line.startswith("| `tool.reddit-search`"))
        assert "‡" in row, row
        assert "‡ **Editor-only" in page


class TestTheArtifactCarriesTheField:
    def test_every_node_record_declares_it(self) -> None:
        artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        assert all("editor_only" in node for node in artifact["node_types"])
