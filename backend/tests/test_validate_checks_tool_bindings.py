"""`validate` passed a document whose tools have no implementation here (79).

Copy a package's `workflow.json` into a project that does not carry that
package's `tools/` folder — a copy, an export, a colleague's file, which is the
normal way a document travels — and the four surfaces disagreed:

| Surface | What it said |
| --- | --- |
| `openstategraph validate` | `VALID`, exit 0, **and** `Tool bindings: {...}` |
| `GET .../capabilities` | `"tools": []` |
| `openstategraph run` | three `No implementation for tool "..."` warnings |

The runtime is the honest one: the agent ran without its tools and refused to
invent an answer. The defect is that the one command whose whole job is to
answer *before a run costs anything* did not look — and printed a
`Tool bindings:` line that reads as confirmation the bindings are real.

**Binding is a registry lookup, not a model call**, so the same question the
run answers is answerable at validate time for free. The check mirrors
`NodeRuntime._bound_tool` exactly — the same registry, keyed by the same node
type — because a check that resolves by a *different* rule than the runtime is
a second validator, and two validators is how a document passes one gate and
fails the other.

Note what is deliberately **not** here: a package-scoped discovered type is
legitimate when its package is present (CLAUDE.md, the `code → canvas`
channel). It is reported when it does not resolve for the same reason a
built-in is — from a user's seat both end the same way, with an agent running
without the tool it was drawn with — and never by refusing the document.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph import cli
from openstategraph.validation import unresolved_tool_bindings

#: A type no installation registers. Deliberately not `tool.chinook-*`: inside
#: this checkout `pytest.ini` puts `workflows/chinook-assistant/tools` on the
#: path, so the bundled Chinook tools ARE built-in here and a test written with
#: them would assert the opposite of what it means.
ABSENT_TOOL = "tool.no-such-tool-anywhere"


def _document(*, tool_type: str | None = ABSENT_TOOL, bind: bool = True) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
        {"id": "agent1", "type": "agent.llm", "data": {}, "position": {"x": 4, "y": 0}},
        {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 9, "y": 0}},
    ]
    edges: list[dict[str, Any]] = [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "agent1", "portId": "prompt"},
        },
        {
            "source": {"nodeId": "agent1", "portId": "result"},
            "target": {"nodeId": "out1", "portId": "result"},
        },
    ]
    if tool_type is not None:
        nodes.append({"id": "tool1", "type": tool_type, "data": {}, "position": {"x": 4, "y": 6}})
        if bind:
            edges.append(
                {
                    "source": {"nodeId": "tool1", "portId": "tool"},
                    "target": {"nodeId": "agent1", "portId": "tools"},
                }
            )
    return {"version": 3, "name": "doc", "nodes": nodes, "edges": edges}


def _package(root: Path, slug: str, document: dict[str, Any]) -> Path:
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": slug, "savedAt": "", "document": document})
    )
    return directory


class TestTheCheckItself:
    def test_a_tool_with_no_implementation_here_is_named(self, tmp_path: Path) -> None:
        package = _package(tmp_path, "orphan", _document())

        findings = unresolved_tool_bindings(_document(), package)

        assert len(findings) == 1
        assert ABSENT_TOOL in findings[0]
        # The node id too: the type says what is missing, the id says which
        # card on the canvas to look at.
        assert "tool1" in findings[0]

    def test_a_tool_that_resolves_is_no_finding(self, tmp_path: Path) -> None:
        # `tool.web-search` is built in, so it resolves in every installation.
        package = _package(tmp_path, "webby", _document(tool_type="tool.web-search"))

        assert unresolved_tool_bindings(_document(tool_type="tool.web-search"), package) == []

    def test_a_document_with_no_tools_is_no_finding(self, tmp_path: Path) -> None:
        package = _package(tmp_path, "plain", _document(tool_type=None))

        assert unresolved_tool_bindings(_document(tool_type=None), package) == []

    def test_an_unbound_tool_node_is_not_reported(self, tmp_path: Path) -> None:
        # Mirroring the runtime is the whole design: `_bound_tool` is only
        # reached for a tool wired to something. A tool card parked on the
        # canvas gives no agent a capability, so losing it costs nothing and a
        # warning about it is noise a user learns to skip.
        package = _package(tmp_path, "parked", _document(bind=False))

        assert unresolved_tool_bindings(_document(bind=False), package) == []

    def test_a_tool_the_package_ships_resolves(self, tmp_path: Path) -> None:
        # The other half of the same rule, and the one that makes this safe
        # for the `code → canvas` channel: the same document is a finding
        # without the package's `tools/` and clean with it.
        package = _package(tmp_path, "shipper", _document(tool_type="tool.locally-defined"))
        tools = package / "tools"
        tools.mkdir()
        (tools / "__init__.py").write_text("")
        (tools / "mine.py").write_text(
            "from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult\n"
            "\n"
            "class LocalTool(BaseTool):\n"
            "    name = 'local_tool'\n"
            "    description = 'A tool this package ships.'\n"
            "    node_type = 'tool.locally-defined'\n"
            "    Args = NoArgs\n"
            "\n"
            "    def _execute(self, args):\n"
            "        return ToolResult(content='ok')\n"
        )

        assert unresolved_tool_bindings(_document(tool_type="tool.locally-defined"), package) == []

    def test_one_missing_type_is_one_finding(self, tmp_path: Path) -> None:
        document = _document()
        document["nodes"].append(
            {"id": "tool2", "type": ABSENT_TOOL, "data": {}, "position": {"x": 4, "y": 9}}
        )
        document["edges"].append(
            {
                "source": {"nodeId": "tool2", "portId": "tool"},
                "target": {"nodeId": "agent1", "portId": "tools"},
            }
        )
        package = _package(tmp_path, "twice", document)

        findings = unresolved_tool_bindings(document, package)

        # Two cards, one absent implementation, one thing to go and fix.
        assert len(findings) == 1


class TestTheCommand:
    def test_a_document_whose_tools_are_absent_is_not_valid(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        package = _package(tmp_path, "orphan", _document())

        code = cli.main(["validate", str(package)])

        out = capsys.readouterr().out
        assert code == cli.EXIT_FAILURE
        assert "VALID" not in out.splitlines()[0]
        assert ABSENT_TOOL in out

    def test_a_document_whose_tools_resolve_still_validates(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        package = _package(tmp_path, "webby", _document(tool_type="tool.web-search"))

        code = cli.main(["validate", str(package)])

        assert code == cli.EXIT_OK
        assert "VALID" in capsys.readouterr().out

    def test_a_bare_document_file_is_checked_too(self, tmp_path: Path, capsys: Any) -> None:
        # `validate path/to/workflow.json` is documented; the package is the
        # file's own parent, which is what scopes discovery of its `tools/`.
        package = _package(tmp_path, "orphan", _document())

        assert cli.main(["validate", str(package / "workflow.json")]) == cli.EXIT_FAILURE
        assert ABSENT_TOOL in capsys.readouterr().out


class TestTheWords:
    def test_the_finding_says_what_to_do_about_it(self, tmp_path: Path) -> None:
        package = _package(tmp_path, "orphan", _document())

        finding = unresolved_tool_bindings(_document(), package)[0]

        # A warning a user cannot act on is a warning they learn to skip.
        assert "tools/" in finding
        # Future tense: nothing has run yet. The runtime's own sentence says
        # "the agent ran without it", which would be a lie from a gate.
        assert " ran without" not in finding


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
