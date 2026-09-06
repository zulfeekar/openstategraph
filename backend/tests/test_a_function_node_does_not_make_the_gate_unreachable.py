"""A closing gate that no package with a function node can pass —
`osg-agent-experience/89`.

The entry sheet's §10 gate says: run `openstategraph validate
workflows/<slug>` and there must be no `PROBLEMS FOUND:` **and** no `Notes:`.
The wording is deliberate and `osg-agent-experience/81` is why — an agent said
"completed" over red diagnostics it never looked at.

But a document holding any workflow-scoped `function.*` node printed a `Notes:`
line on every run, by design: this build mints no static field schema for a
type a package's own `functions/` supplies, and the skip *speaks* rather than
passing in silence. Two shipped packages use a function node, so neither could
ever satisfy the gate, and an agent following it honestly had to either report
`Not clean yet:` forever or learn to discount a `Notes:` line. Both endings are
the one `81` was filed to prevent.

**Settled by separating the two classes rather than by weakening the gate**,
which is the second shape the ticket offered. The two sentences were riding one
list and they are not the same kind of thing:

- *"nothing is wired into this node, so it never runs"* is advice about the
  **document**. A developer acts on it. It is a note.
- *"this build has no generated field schema for that type"* is a statement
  about the **validator's own coverage**. There is nothing to act on, and a
  reader who deletes the node to silence it has been misled by the heading.

So the second class is `CompiledPlan.unchecked` and prints under `Not checked:`.
The gate's sentence is unchanged, and no agent is asked to judge which notes
count — the headings do it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph import cli
from openstategraph.bundled_skills import BUNDLED_SKILLS

SHEET = BUNDLED_SKILLS["openstategraph"] / "SKILL.md"

FUNCTION_SOURCE = '''def ask_back(text: str) -> str:
    return "Which one did you mean, " + text + "?"
'''


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _document(*, stranded: bool = False) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "askfn1", "type": "function.ask_back", "position": {"x": 200, "y": 0}, "data": {}},
        {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ]
    edges = [
        _edge("in1", "text", "askfn1", "candidate"),
        _edge("askfn1", "report", "out1", "result"),
    ]
    if stranded:
        # An Output with nothing wired into it — the class `81` put on this
        # channel, and the one a developer can act on.
        nodes.append(
            {"id": "out2", "type": "output.formatted", "position": {"x": 400, "y": 200}, "data": {}}
        )
    return {"version": 2, "name": "askback", "nodes": nodes, "edges": edges}


@pytest.fixture
def package(tmp_path: Path) -> Path:
    directory = tmp_path / "workflows" / "askback"
    (directory / "functions").mkdir(parents=True)
    (directory / "functions" / "ask.py").write_text(FUNCTION_SOURCE)
    (directory / "workflow.json").write_text(json.dumps(_document()))
    return directory


def _report(package: Path, capsys: pytest.CaptureFixture[str]) -> str:
    parser = cli.build_parser()
    args = parser.parse_args(["validate", str(package)])
    assert args.handler(args) == 0
    return capsys.readouterr().out


class TestTheGateIsReachable:
    def test_a_package_with_a_function_node_prints_no_notes(
        self, package: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The gate's own condition, asserted against the real output."""
        out = _report(package, capsys)

        assert "PROBLEMS FOUND:" not in out
        assert "Notes:" not in out

    def test_the_coverage_statement_is_still_made(
        self, package: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Moved, not dropped — the skip must not become silent."""
        out = _report(package, capsys)

        assert "Not checked:" in out
        assert "askfn1" in out
        assert "no generated field schema" in out


class TestTheOtherClassStillReachesNotes:
    def test_a_node_nothing_is_wired_into_is_a_note(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`81`'s own class. A gate that lost this would be worse than useless."""
        directory = tmp_path / "workflows" / "askback"
        (directory / "functions").mkdir(parents=True)
        (directory / "functions" / "ask.py").write_text(FUNCTION_SOURCE)
        (directory / "workflow.json").write_text(json.dumps(_document(stranded=True)))

        out = _report(directory, capsys)
        notes = out.split("Notes:", 1)[1]

        assert "Notes:" in out
        assert "out2" in notes
        assert "never runs" in notes

    def test_the_two_classes_do_not_share_a_heading(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = tmp_path / "workflows" / "askback"
        (directory / "functions").mkdir(parents=True)
        (directory / "functions" / "ask.py").write_text(FUNCTION_SOURCE)
        (directory / "workflow.json").write_text(json.dumps(_document(stranded=True)))

        out = _report(directory, capsys)
        notes = out.split("Notes:", 1)[1]

        assert "no generated field schema" not in notes


class TestTheSheetAndTheCompilerSayTheSameThing:
    """The ticket's third bullet: whichever way it is settled, both say it."""

    def test_the_sheet_names_the_heading_that_is_not_a_note(self) -> None:
        text = SHEET.read_text()

        assert "Not checked:" in text

    def test_the_compiler_says_where_the_skip_is_published(self) -> None:
        from openstategraph.compile.workflow_compiler import data_key_findings

        assert "Not checked:" in (data_key_findings.__doc__ or "")

    def test_the_plan_keeps_the_two_channels_apart(self) -> None:
        from openstategraph.compile.workflow_compiler import CompiledPlan

        plan = CompiledPlan()
        assert plan.unchecked == []
        assert plan.advisories == []
