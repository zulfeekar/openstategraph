"""`openstategraph validate` names the node that can never run.

`osg-agent-experience/81`. A session built a router from the shipped sheet,
ran the package tests (green) and `validate` (VALID), and reported the work
done. The owner opened the same document in the editor and read four red
diagnostics off the canvas: three mounts with no inbound edge and a static
exit with nothing wired to its `when` port.

None of the four is a defect this command was blind to for want of a check.
`80` had already added them — `plan.advisories` names every node the entry
preference declines to start, by id, in the compiler's own words. The defect
is that **only one of the product's two doors printed them**:
`validation.validate_document`, which MCP's `validate_workflow` calls, appends
the advisories to its findings; `cli.cmd_validate` builds its own report and
never read the channel. Two doors of one product answering differently about
one document is the thing the sheet's gate cannot be written against.

Pinned here, both halves:

- the advisory **reaches the command**, naming the node id — otherwise the
  agent reading the terminal has no way to learn what the canvas draws in red;
- and it is a **note, not a problem**: `80` ruled this channel one that can
  never move VALID to INVALID (a lone agent on a fresh canvas has a required
  `prompt` with nothing feeding it and must still run), so the exit code stays
  0. A command that failed CI over an advisory would have the channel
  suppressed within a week.

Driven as a subprocess for `test_validate_prints_the_compilers_findings.py`'s
reason: the target is what a person at a terminal sees, stdout and exit code
together. No model is called — `cmd_validate` compiles with the drawing-only
stand-in.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from openstategraph import cli


def _validate(package: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "openstategraph.cli", "validate", str(package)],
        cwd=str(package.parent),
        env={**os.environ, "PYTHONPATH": str(Path(cli.__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
    )


def _write(package: Path, nodes: list[dict], edges: list[dict]) -> Path:
    package.mkdir(parents=True, exist_ok=True)
    (package / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "Stranded",
                "document": {"version": 1, "name": "Stranded", "settings": {}, "nodes": nodes, "edges": edges},
            },
            indent=2,
        )
    )
    return package


@pytest.fixture()
def stranded(tmp_path: Path) -> Path:
    """One wired path, and a second exit nobody drew an edge into.

    The owner's own canvas in miniature: `out_stranded` declares a required
    in-port, nothing feeds it, and the run finishes without it ever executing.
    """
    return _write(
        tmp_path / "stranded",
        [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "hi"}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
            {"id": "out_stranded", "type": "output.formatted", "position": {"x": 200, "y": 200}, "data": {}},
        ],
        [{"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "out1", "portId": "result"}}],
    )


def test_the_command_names_the_node_that_never_runs(stranded: Path) -> None:
    result = _validate(stranded)

    #: The sentence, not the id. `out_stranded` is printed on the Topology
    #: line either way — it *is* an exit of the drawn graph — so asserting the
    #: bare id is a test that passes against a command which reports nothing.
    note = next(
        (line for line in result.stdout.splitlines() if line.startswith("- ") and "out_stranded" in line),
        None,
    )
    assert note is not None, (
        "`validate` said nothing about a node the editor draws in red and the "
        f"compiler already reports on `plan.advisories`: {result.stdout}"
    )
    assert "never runs" in note, note


def test_it_is_a_note_and_never_moves_the_exit_code(stranded: Path) -> None:
    result = _validate(stranded)

    assert result.returncode == 0, (
        "an advisory moved the exit code, which `80` ruled it must never do: "
        f"{result.stdout}"
    )
    assert "PROBLEMS FOUND" not in result.stdout
    assert "Notes:" in result.stdout


def test_a_fully_wired_document_carries_no_note(tmp_path: Path) -> None:
    """The other half, and the one that keeps the gate worth running: a clean
    document must print no note at all, or "Notes is empty" is not a bar."""
    package = _write(
        tmp_path / "wired",
        [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "hi"}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
        ],
        [{"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "out1", "portId": "result"}}],
    )

    result = _validate(package)

    assert result.returncode == 0, result.stdout
    assert "Notes:" not in result.stdout, result.stdout
