"""A skill's text has one authority, and the other copy says it is one.

`launch-readiness/94`. `input.markdown` carries **two** fields describing the
same text — `filename`, which the editor writes when a file is picked, and
`content`, the copy it pastes in beside it — and until this ticket the
compiler read only the second. `filename` was never read at run time by
anything.

Found live rather than by reading: in a shipped NL2SQL package the SQL
validator loads `skills/lenses/*.md` from disk while the agent reads the
embedded copy, and **seven of twelve had drifted**. A commit that declared four
lenses, two routing rules and the "ask, don't guess" guidance reached the
validator and never reached the model. The traces looked like an agent
ignoring its rules; it had never been shown them.

**The rule this file pins, and it is the same rule at every door:**

| the document says | the run uses | and reports |
| --- | --- | --- |
| inline `instruction` text | that text | that the named file went unread |
| a `filename` this run can read | **the file** | drift, when the stored copy differs |
| a `filename` this run cannot read | the stored copy | that it ran from a snapshot |
| no `filename` at all | the stored copy | nothing — there is one source |

The stateless door (`mcp_server.compile_workflow`) has no package on disk, so
every one of its runs is row three. That is not a different rule; it is the
same rule reaching a different answer, which is why the sentence exists — a
caller who cannot see the difference cannot know their edit did not apply.

Both readers go through one seam, and the last class here fails the day a
third one re-implements the precedence in a fourth module.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph.compile.diagnostics import REPORT_ONLY, CompileDiagnostics, Finding
from openstategraph.compile.node_runtime import NodeRuntime, RuntimeServices
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.schema import normalize_document

BACKEND = Path(__file__).resolve().parent.parent

ON_DISK = "# Analyst\n\nJoin with QUALIFY ROW_NUMBER().\nAsk, do not guess.\n"
STORED = "# Analyst\n\nJoin it.\n"


def _document(data: dict[str, Any]) -> dict[str, Any]:
    return normalize_document(
        {
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {"prompt": "hi"}},
                {"id": "skill1", "type": "input.markdown", "data": data},
                {"id": "a1", "type": "agent.llm", "data": {}},
                {"id": "out1", "type": "output.text", "data": {}},
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "a1", "portId": "prompt"},
                },
                {
                    "source": {"nodeId": "skill1", "portId": "skill"},
                    "target": {"nodeId": "a1", "portId": "skill"},
                },
                {
                    "source": {"nodeId": "a1", "portId": "result"},
                    "target": {"nodeId": "out1", "portId": "text"},
                },
            ],
        }
    )


def _package(tmp_path: Path, data: dict[str, Any], *, write_file: bool = True) -> Path:
    package = tmp_path / "drift-demo"
    (package / "skills").mkdir(parents=True)
    if write_file:
        (package / "skills" / "analyst.md").write_text(ON_DISK)
    (package / "workflow.json").write_text(json.dumps({"document": _document(data)}))
    return package


def _runtime(package: Path | None, data: dict[str, Any]) -> NodeRuntime:
    document = _document(data)
    runtime = NodeRuntime(services=RuntimeServices(skills_package_dir=package))
    runtime.factory(document)
    return runtime


def _skill_reaching_the_model(runtime: NodeRuntime) -> str:
    """What an agent's `skill` port actually contributes to the prompt.

    Deliberately not `_static_text`: a node wired to a `skill` port is
    `bound_only`, so it never runs and never writes `outputs` — the reader
    that decides what the model is shown is `_wired_skill`, in a different
    module, and it was the second of the two places that open-coded the field
    precedence this ticket is about.
    """
    from openstategraph.compile.state import _wired_skill

    return _wired_skill({}, ["skill1"], runtime.static_sources)


def _text_of(runtime: NodeRuntime, plan_document: dict[str, Any]) -> str:
    plan = WorkflowCompiler().plan(plan_document)
    node = next(n for n in plan_document["nodes"] if n["id"] == "skill1")
    return str(runtime._static_text("skill1", node, plan)({})["outputs"]["skill1"])


class TestTheFileWins:
    @pytest.fixture
    def runtime(self, tmp_path: Path) -> NodeRuntime:
        data = {"filename": "skills/analyst.md", "content": STORED}
        return _runtime(_package(tmp_path, data), data)

    def test_the_model_is_shown_the_file_not_the_stored_copy(
        self, runtime: NodeRuntime
    ) -> None:
        shown = _skill_reaching_the_model(runtime)

        assert "Ask, do not guess." in shown
        assert shown.strip() == ON_DISK.strip()

    def test_the_unwired_node_emits_the_file_too(
        self, runtime: NodeRuntime, tmp_path: Path
    ) -> None:
        document = _document({"filename": "skills/analyst.md", "content": STORED})

        assert "Ask, do not guess." in _text_of(runtime, document)

    def test_the_drift_is_reported(self, runtime: NodeRuntime) -> None:
        sentences = runtime.diagnostics.warnings()

        assert len(sentences) == 1
        assert "skill1" in sentences[0]
        assert "skills/analyst.md" in sentences[0]

    def test_a_bare_name_resolves_under_skills(self, tmp_path: Path) -> None:
        data = {"filename": "analyst.md", "content": STORED}
        runtime = _runtime(_package(tmp_path, data), data)

        assert "Ask, do not guess." in _skill_reaching_the_model(runtime)


class TestAnAgreeingCopyIsSilent:
    def test_a_stored_copy_that_matches_reports_nothing(self, tmp_path: Path) -> None:
        data = {"filename": "skills/analyst.md", "content": ON_DISK}
        runtime = _runtime(_package(tmp_path, data), data)

        assert runtime.diagnostics.warnings() == []
        assert "Ask, do not guess." in _skill_reaching_the_model(runtime)

    def test_a_document_naming_no_file_reports_nothing(self, tmp_path: Path) -> None:
        """One field populated is one source, which is the shape most
        documents have. Reporting on it would be a warning every reader
        learns to skip."""
        data = {"content": STORED}
        runtime = _runtime(_package(tmp_path, data, write_file=False), data)

        assert runtime.diagnostics.warnings() == []
        assert _skill_reaching_the_model(runtime).strip() == STORED.strip()


class TestTheStatelessDoorSaysSo:
    """No package on disk — `mcp_server.compile_workflow`'s whole situation.

    The stored copy is used, which is why it must not be dropped, and the run
    says it ran from a snapshot rather than letting a caller believe their
    edit applied.
    """

    def test_the_stored_copy_is_used(self) -> None:
        data = {"filename": "skills/analyst.md", "content": STORED}

        assert _skill_reaching_the_model(_runtime(None, data)).strip() == STORED.strip()

    def test_the_snapshot_is_reported(self) -> None:
        data = {"filename": "skills/analyst.md", "content": STORED}

        sentences = _runtime(None, data).diagnostics.warnings()

        assert len(sentences) == 1
        assert "skills/analyst.md" in sentences[0]

    def test_a_named_file_that_is_missing_reports_the_same_way(
        self, tmp_path: Path
    ) -> None:
        data = {"filename": "skills/analyst.md", "content": STORED}
        runtime = _runtime(_package(tmp_path, data, write_file=False), data)

        assert runtime.diagnostics.any(Finding.SKILL_FROM_SNAPSHOT)
        assert _skill_reaching_the_model(runtime).strip() == STORED.strip()

    def test_a_path_leaving_the_package_never_resolves(self, tmp_path: Path) -> None:
        """`filename` addresses the package and nothing above it. A document
        is data from wherever it came from, and a compile that reads an
        arbitrary path off it is a compile that can be pointed anywhere."""
        outside = tmp_path / "secret.md"
        outside.write_text("PRIVATE")
        data = {"filename": "../secret.md", "content": STORED}
        runtime = _runtime(_package(tmp_path, data), data)

        shown = _skill_reaching_the_model(runtime)
        assert "PRIVATE" not in shown
        assert shown.strip() == STORED.strip()
        assert runtime.diagnostics.any(Finding.SKILL_FROM_SNAPSHOT)


class TestTheThirdSource:
    """`instruction` is a field a developer types into, and it still wins.

    Deliberately: the editor's Markdown card lets you load a file and then
    tweak it, and a load that silently discarded the tweak would be the same
    defect pointing the other way. What changes is that the file it then
    leaves unread is named, because a whole lens hiding behind one typed
    sentence is exactly this ticket's shape one field over.
    """

    @pytest.fixture
    def runtime(self, tmp_path: Path) -> NodeRuntime:
        data = {
            "filename": "skills/analyst.md",
            "content": STORED,
            "instruction": "Answer in one line.",
        }
        return _runtime(_package(tmp_path, data), data)

    def test_the_typed_text_still_wins(self, runtime: NodeRuntime) -> None:
        assert _skill_reaching_the_model(runtime).strip() == "Answer in one line."

    def test_the_unread_file_is_named(self, runtime: NodeRuntime) -> None:
        sentences = runtime.diagnostics.warnings()

        assert len(sentences) == 1
        assert "skills/analyst.md" in sentences[0]
        assert runtime.diagnostics.any(Finding.SKILL_FILE_UNUSED)


class TestTheseAreReportsNotFailures:
    """A document in every one of these states runs, and answers, with every
    drawn node producing its output — `REPORT_ONLY`'s own test. Exiting 1 on a
    stale stored copy would fail a package mid-edit; exiting 1 on a snapshot
    would fail every stateless compile of a document that names a file."""

    @pytest.mark.parametrize(
        "finding",
        [
            Finding.SKILL_SOURCE_DRIFTED,
            Finding.SKILL_FROM_SNAPSHOT,
            Finding.SKILL_FILE_UNUSED,
        ],
    )
    def test_no_exit_code_moves(self, finding: Finding) -> None:
        diagnostics = CompileDiagnostics()
        diagnostics.record(finding, "skill1", "skills/analyst.md")

        assert finding in REPORT_ONLY
        assert diagnostics.warnings() != []
        assert diagnostics.failure_warnings() == []


class TestOnlyOneModuleKnowsThePrecedence:
    """The comparison lives at one seam, and this is what keeps it there.

    Two modules used to read `instruction` → `instructions` → `content` off a
    node's `data`: `node_runtime._static_text` and `state._wired_skill`. A
    third would have been the natural way to add a feature, and neither of the
    two would have failed. Parsed rather than grepped, on the precedent of
    `test_a_runs_diagram_opens_its_mounts.py`.
    """

    FIELDS = {"instruction", "instructions", "content", "filename"}
    SEAM = "openstategraph/compile/static_source.py"

    def test_no_other_module_reads_the_field_chain(self) -> None:
        offenders: list[str] = []
        for path in sorted((BACKEND / "openstategraph").rglob("*.py")):
            relative = str(path.relative_to(BACKEND))
            if relative == self.SEAM or "/examples/" in relative:
                continue
            named: set[str] = set()
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                callee = node.func
                name = (
                    callee.attr
                    if isinstance(callee, ast.Attribute)
                    else getattr(callee, "id", "")
                )
                if name not in {"_text", "get"}:
                    continue
                last = node.args[-1]
                if isinstance(last, ast.Constant) and last.value in self.FIELDS:
                    named.add(str(last.value))
            # Two or more of them in one module is the signature of a second
            # precedence chain. One is an ordinary read of an unrelated field
            # — a message's `content`, a tool argument's `filename`.
            if len(named) > 1:
                offenders.append(f"{relative} reads {sorted(named)}")
        assert not offenders, (
            "these re-implement a skill source's precedence: "
            f"{offenders} — go through compile.static_source"
        )
