"""`validate` said VALID for a package that is not there (production-ready 53).

The one command whose job is *tell me before I ship* passed a workflow that
mounts `no-such-package-anywhere`, and the run that followed also exited 0. So
a CI gate built on either was green for a workflow that answers nothing.

Four separate defects, all reproduced here before they were fixed:

1. **`validate` never looked.** A mount is the only cross-package reference a
   document can hold, resolving it is a filesystem lookup, and a typo in a slug
   is the likeliest way to break composition. `ValidateWorkflowTool` plans the
   graph in memory and never touches a root, so it cannot see this — which is
   why the check is its own function taking a root, not a second validator.

2. **A run that produced no answer exited 0.** Two causes stacked: the
   formatted-output node substitutes a *sentence* when it has nothing, so
   `run_exit_code`'s "the answer is empty" test was false; and the only
   evidence it consulted was `node_failure_warnings(outputs)`, which reads
   failure markers left in node outputs. A mount that could not be loaded
   leaves no such marker — it is a compile finding, on `result.warnings`.

3. **"Check the run trace to see which step returned nothing"** was printed
   directly below the line that already names the step, and no surface offers
   the CLI a trace to open.

4. **"Subgraph workflow"** is a LangGraph name in a sentence a user reads.
   CLAUDE.md forbids that, the settled words are *mount* and *workflow node*,
   and this compiler emits no LangGraph subgraph anyway (production-ready 37).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph import cli
from openstategraph.validation import unresolved_mounts


def _document(*, mounts: str | None = None) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
        {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 9, "y": 0}},
    ]
    edges: list[dict[str, Any]] = []
    if mounts is None:
        edges.append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        )
    else:
        nodes.insert(
            1,
            {
                "id": "mount1",
                "type": "workflow.subgraph",
                "title": "The mount",
                "data": {"workflow": mounts},
                "position": {"x": 5, "y": 0},
            },
        )
        edges += [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "mount1", "portId": "input"},
            },
            {
                "source": {"nodeId": "mount1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ]
    return {"version": 3, "name": "doc", "nodes": nodes, "edges": edges}


def _package(root: Path, slug: str, *, mounts: str | None = None) -> Path:
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {"version": 1, "name": slug, "savedAt": "", "document": _document(mounts=mounts)}
        )
    )
    return directory


class TestTheCheckItself:
    def test_a_missing_package_is_named(self, tmp_path: Path) -> None:
        _package(tmp_path, "ghost-mount", mounts="no-such-package-anywhere")

        findings = unresolved_mounts(_document(mounts="no-such-package-anywhere"), tmp_path)

        assert len(findings) == 1
        # The slug, because that is the thing with the typo in it.
        assert "no-such-package-anywhere" in findings[0]

    def test_a_package_that_is_there_is_no_finding(self, tmp_path: Path) -> None:
        _package(tmp_path, "child")

        assert unresolved_mounts(_document(mounts="child"), tmp_path) == []

    def test_a_mount_with_no_target_chosen_is_named_too(self, tmp_path: Path) -> None:
        # An empty mount is a node that will produce nothing, exactly like a
        # mistyped one. Reported in the words a user can act on rather than as
        # a lookup of the empty string.
        findings = unresolved_mounts(_document(mounts=""), tmp_path)

        assert len(findings) == 1
        assert "no workflow" in findings[0].lower()

    def test_it_recurses_so_a_two_deep_chain_is_checked(self, tmp_path: Path) -> None:
        # The ticket asks for this by name: the defect is a *typo*, and a typo
        # two packages down breaks the run just as completely.
        _package(tmp_path, "mid", mounts="no-such-grandchild")

        findings = unresolved_mounts(_document(mounts="mid"), tmp_path)

        assert len(findings) == 1
        assert "no-such-grandchild" in findings[0]
        # Which chain led there, because "no-such-grandchild" appears nowhere
        # in the document the user just validated.
        assert "mid" in findings[0]

    def test_a_cycle_terminates_rather_than_recursing_forever(self, tmp_path: Path) -> None:
        # Termination is still the requirement, and it is still met — but the
        # cycle is now *reported* on the way out rather than passed over in
        # silence (workflow-gallery 27). This test asserted `== []` until
        # then, on the argument that the compile-time refusal was the better
        # message; it arrives too late to be a gate, which is what 27 is about.
        # The words are pinned against `node_runtime`'s own in
        # `test_validate_sees_a_mount_cycle.py`.
        _package(tmp_path, "a", mounts="b")
        _package(tmp_path, "b", mounts="a")

        findings = unresolved_mounts(_document(mounts="a"), tmp_path)

        assert len(findings) == 1
        assert "mounts itself" in findings[0]

    def test_each_missing_slug_is_reported_once(self, tmp_path: Path) -> None:
        # Two mounts of one absent package is one typo, not two problems.
        document = _document(mounts="absent")
        document["nodes"].append(
            {
                "id": "mount2",
                "type": "workflow.subgraph",
                "data": {"workflow": "absent"},
                "position": {"x": 5, "y": 9},
            }
        )

        assert len(unresolved_mounts(document, tmp_path)) == 1


class TestTheCommand:
    def test_a_ghost_mount_is_not_valid(self, tmp_path: Path, capsys: Any) -> None:
        package = _package(tmp_path, "ghost-mount", mounts="no-such-package-anywhere")

        code = cli.main(["validate", str(package)])

        out = capsys.readouterr().out
        assert code == cli.EXIT_FAILURE
        assert "VALID" not in out.splitlines()[0]
        assert "no-such-package-anywhere" in out

    def test_a_real_mount_still_validates(self, tmp_path: Path, capsys: Any) -> None:
        _package(tmp_path, "child")
        package = _package(tmp_path, "parent", mounts="child")

        code = cli.main(["validate", str(package)])

        assert code == cli.EXIT_OK
        assert "VALID" in capsys.readouterr().out

    def test_a_bare_document_file_is_still_validated(self, tmp_path: Path, capsys: Any) -> None:
        # `validate path/to/workflow.json` is documented and must keep working.
        # The root is the file's own parent's parent — where its siblings live.
        _package(tmp_path, "child")
        package = _package(tmp_path, "parent", mounts="child")

        assert cli.main(["validate", str(package / "workflow.json")]) == cli.EXIT_OK
        assert "VALID" in capsys.readouterr().out


class TestTheExitCode:
    def test_a_run_that_answers_nothing_fails(self, tmp_path: Path, capsys: Any) -> None:
        package = _package(tmp_path, "ghost-mount", mounts="no-such-package-anywhere")

        code = cli.main(["run", str(package), "Explain a compiler in one sentence."])

        assert code == cli.EXIT_FAILURE, "a CI gate cannot be built on a run that always passes"
        assert "no-such-package-anywhere" in capsys.readouterr().err

    def test_an_answer_beside_a_warning_is_still_a_success(self) -> None:
        # The recorded exception, kept: a degrade is this project's preferred
        # failure, and failing the exit code on every partial run would make
        # them all look broken.
        from openstategraph.results import RunResult

        result = RunResult("here is the answer", warnings=["a tool did not resolve"])

        assert cli.run_exit_code(result) == cli.EXIT_OK

    def test_an_empty_answer_with_nothing_wrong_is_still_legal(self) -> None:
        # The other recorded exception. A workflow may answer with nothing,
        # and nothing about that run went wrong.
        from openstategraph.results import RunResult

        assert cli.run_exit_code(RunResult("")) == cli.EXIT_OK

    def test_the_no_answer_sentence_counts_as_no_answer(self) -> None:
        # The half that made the bug invisible: the formatted-output node
        # substitutes a sentence when it has nothing, so "is the answer empty"
        # was answered by a string that says it is.
        from openstategraph.compile.node_runtime import NO_ANSWER_PRODUCED
        from openstategraph.results import RunResult

        result = RunResult(NO_ANSWER_PRODUCED, warnings=["a mount did not resolve"])

        assert cli.run_exit_code(result) == cli.EXIT_FAILURE


class TestTheWords:
    def test_the_unresolved_mount_sentence_says_mount(self) -> None:
        from openstategraph.compile.diagnostics import CompileDiagnostics, Finding

        sentence = CompileDiagnostics.sentence_for(Finding.UNRESOLVED_SUBGRAPH)

        # CLAUDE.md: our own runtime vocabulary, never LangGraph's, in
        # anything a user reads. And this compiler emits no LangGraph
        # subgraph, so the word was not even accurate internally.
        assert "subgraph" not in sentence.lower()
        assert "mount" in sentence.lower() or "workflow node" in sentence.lower()

    def test_the_floor_message_does_not_send_anyone_to_a_trace(self) -> None:
        from openstategraph.compile.node_runtime import NO_ANSWER_PRODUCED

        # Printed directly below the line that already names the step, and the
        # CLI has no trace to open. Advice a surface cannot honour is worse
        # than none.
        assert "trace" not in NO_ANSWER_PRODUCED.lower()
        assert NO_ANSWER_PRODUCED.strip()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
