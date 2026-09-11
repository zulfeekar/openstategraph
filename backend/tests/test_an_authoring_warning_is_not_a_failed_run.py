"""A compile finding about how a graph is *drawn* must not decide an exit code.

`workflow-gallery` 49 split `RunResult` into a failure half and a report half
and pointed `cli.run_exit_code` at the failures. The right-hand term became
honest — a silent node, a forced pass and an unrouted verdict are reports. The
left-hand term did not: `CompiledWorkflow.warnings` was one undivided bag of
authoring findings and all of it counted as *"the run failed"*.

The sharp evidence, measured on the shipped `support-triage` package before
anything was written (before `workflow-gallery` 78 wired its `revise` edge —
see `_report_only_package` below for what this file uses now):

    warnings:         ['Grader "grader1" has no revise edge — a verdict of
                       revise routes to its pass branch instead, …']
    failure_warnings: [the same sentence]

That is the identical observation the runtime reports as `unrouted`, which 49
deliberately classified as a **report**. So one finding was a report when the
run noticed it and a failure when the compiler did, and on any run that
answered with nothing it alone exited 1.

`production-ready` 89 had already built the machinery one layer over —
`CompileDiagnostics.failure_warnings()` and `REPORT_ONLY`. This ticket is the
classification pass 89's single member left undone.

**The inverse is the load-bearing half.** `production-ready` 53's mount that
cannot be loaded leaves no marker in `outputs`, is a genuinely broken run, and
must still exit 1. `TestAnUnloadableMountStillExitsOne` says so by name.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from conftest import whatever_it_produced

from openstategraph import cli
from openstategraph.compile.diagnostics import REPORT_ONLY, Finding
from openstategraph.loader import CompiledWorkflow, load_workflow

EXAMPLES = Path(__file__).resolve().parents[1] / "openstategraph" / "examples"


def _report_only_package(tmp_path: Path) -> Path:
    """A grader with its `revise` edge stripped.

    Until `workflow-gallery` 78 this class read the shipped `support-triage`
    package directly — it carried `Finding.UNWIRED_REVISE` on purpose
    (gallery 31). 78 wired that edge into the packaged copy to match the fix
    `48` gave the dev workspace copy, so no shipped package carries the
    finding any more and this class needs its own synthetic one, built the
    same way `test_validate_prints_the_compilers_findings.py`'s `report_only`
    fixture builds it: a real package (`web-research-digest`) whose grader
    *is* wired, with that edge removed.
    """
    package = tmp_path / "report-demo"
    shutil.copytree(EXAMPLES / "web-research-digest", package)
    shutil.rmtree(package / "tests", ignore_errors=True)
    manifest = package / "workflow.json"
    saved = json.loads(manifest.read_text())
    document = saved["document"]
    document["edges"] = [
        e
        for e in document["edges"]
        if e["source"] != {"nodeId": "grader1", "portId": "revise"}
    ]
    manifest.write_text(json.dumps(saved))
    return package


class _EmptyAnswerGraph:
    """A graph that runs and answers with nothing.

    The condition `run_exit_code` gates on is *both* halves — no answer **and**
    something wrong — so an empty answer is what makes a compile finding
    decisive. This is the shape the ticket describes as "any run that answers
    with nothing".
    """

    async def ainvoke(self, _state: Any, _config: Any = None, **_kw: Any) -> dict[str, Any]:
        return {"answer": "", "attempts": 0, "decisions": {}, "outputs": {}}


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


@pytest.fixture(autouse=True)
def _memory_checkpointer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSTATEGRAPH_CHECKPOINT_PATH", "memory")


def _exit_code_of_an_empty_run(workflow: CompiledWorkflow) -> int:
    """What `openstategraph run` would exit with for a run that answers nothing.

    The *door* is in the test on purpose. Asserting on `REPORT_ONLY` alone
    would stay green against a fix wired to the wrong list — the trap this
    repository has paid for twice — because the target of this ticket is an
    exit code, not a set.
    """
    empty = dataclasses.replace(workflow, graph=_EmptyAnswerGraph())
    # The door raises on exactly this shape since `launch-readiness/171` — no
    # answer and a reason — and the run it would have returned is on the error.
    # This helper is about the *exit code* that shape earns, which is read from
    # the same predicate the raise is, so unwrapping loses nothing.
    return cli.run_exit_code(whatever_it_produced(lambda: empty.ask("anything")))


class TestADrawingWarningDoesNotFailTheRun:
    """The ticket's own evidence, on a synthetic package built to carry it —
    see `_report_only_package` for why this is no longer the shipped one."""

    def test_support_triage_reports_its_unwired_grader(self, tmp_path: Path) -> None:
        workflow = load_workflow(_report_only_package(tmp_path))
        try:
            assert any("no revise edge" in warning for warning in workflow.warnings)
        finally:
            workflow.close()

    def test_and_does_not_call_it_a_failure(self, tmp_path: Path) -> None:
        workflow = load_workflow(_report_only_package(tmp_path))
        try:
            assert workflow.failure_warnings == []
        finally:
            workflow.close()

    def test_so_a_run_that_answers_nothing_still_exits_zero(self, tmp_path: Path) -> None:
        workflow = load_workflow(_report_only_package(tmp_path))
        try:
            assert _exit_code_of_an_empty_run(workflow) == cli.EXIT_OK
        finally:
            workflow.close()

    def test_but_the_reader_is_still_told_as_a_warning(self, tmp_path: Path) -> None:
        """Demoted from the exit code, never from the report."""
        workflow = load_workflow(_report_only_package(tmp_path))
        try:
            result = dataclasses.replace(workflow, graph=_EmptyAnswerGraph()).ask("anything")
        finally:
            workflow.close()
        lines = cli.run_report_lines(result)
        assert [line for line in lines if "no revise edge" in line and line.startswith("warning:")]
        assert not [line for line in lines if line.startswith("error:")]


class TestAnUnloadableMountStillExitsOne:
    """`production-ready` 53, which is why compile findings were failures at all.

    A mount naming a package that is not in the workflows root leaves **no**
    marker in `outputs`, so `run_exit_code`'s `outputs` half sees nothing and
    the compile finding is the only thing that knows. This is the direction a
    careless widening of `REPORT_ONLY` would break silently, and the reason
    this ticket's safe direction of error is to leave a finding a failure.
    """

    def test_the_finding_is_a_failure_not_only_a_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package = _package(tmp_path, "ghost-mount", mounts="no-such-package-anywhere")
        monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(tmp_path))
        workflow = load_workflow(package)
        try:
            assert any("could not load that package" in w for w in workflow.warnings)
            assert workflow.failure_warnings == workflow.warnings
        finally:
            workflow.close()

    def test_and_a_run_with_no_answer_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package = _package(tmp_path, "ghost-mount", mounts="no-such-package-anywhere")
        monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(tmp_path))
        workflow = load_workflow(package)
        try:
            assert _exit_code_of_an_empty_run(workflow) == cli.EXIT_FAILURE
        finally:
            workflow.close()


class TestEveryProducerHasASide:
    """The ticket asks for a test pinning which side each *producer* lands on.

    Spelled as the whole partition rather than as `assert X in REPORT_ONLY`, so
    a fourteenth `Finding` is a red test until somebody decides what it means.
    Deciding is the work; the default of silence is what this ticket is about.
    """

    #: "This graph cannot do what it says." Every one of these describes work
    #: the run did not do: a tool with no implementation, a function with no
    #: callable, a node type with no factory, a mount that would not load, an
    #: override that did not apply, a capability that never became one, a
    #: guardrail row that protects nothing — and an Output that emits what the
    #: document's own policy redacts on the path beside it — and a mount whose
    #: child requires a run-context key this document cannot name, which raises
    #: before `invoke` on every run, so the composition produces no answer at
    #: all (`organisms-first-class` 79; it is `UNRESOLVED_SUBGRAPH`'s class one
    #: reason over — the package loads, and still nothing can come out of it).
    FAILURES = frozenset(
        {
            Finding.UNRESOLVED_TOOL,
            Finding.UNRESOLVED_FUNCTION,
            Finding.UNKNOWN_NODE_TYPE,
            Finding.UNRESOLVED_SUBGRAPH,
            Finding.OVERRIDE_PROBLEM,
            Finding.CAPABILITY_FAILED,
            Finding.UNGUARDED_EXIT,
            Finding.INVALID_GUARDRAIL_RULE,
            Finding.UNSUPPLIABLE_CONTEXT,
        }
    )

    #: "This graph is drawn oddly." The run did everything it was drawn to do.
    #: `STATELESS_MOUNT_REDOES` is the third, and the closest call of the
    #: three (`organisms-first-class` 65): a stateless mount over a workflow
    #: that holds an approval *does* pause, resume and answer — so the run did
    #: everything it was drawn to do — and what the sentence reports is that
    #: answering it does the work before the gate a **second** time. Advice
    #: about a mode, not a lost capability, so it may not move an exit code.
    #: `UNENFORCED_OUTCOME` is the fourth (`workflow-gallery` 61): the same
    #: "no grader routes revise" predicate this file's own subject reports one
    #: level down, so keeping the two apart made one fact a failure at the
    #: parent and a report at the child.
    #: `OVERRIDE_APPLIED` is the fifth (`launch-readiness` 40): confirmation
    #: that a mount override reached its target, the counterpart
    #: `OVERRIDE_PROBLEM` never had for the success case. The write already
    #: happened — this sentence is advice about scope, not a claim the run
    #: came out less capable, so it may not move an exit code either.
    #: `MODEL_SELECTION_DEGRADED` joined it in `launch-readiness` 45/62: a
    #: node's own model selection was syntactically valid and this
    #: installation still could not serve it — no key, no provider package.
    #: The run answers, on the shared default rather than the node's choice,
    #: which is worth a sentence and never worth failing a build over: the
    #: identical selection succeeds the moment the credential exists, and
    #: `validate`'s own docstring promises an answer "on a machine with no
    #: credential" — a promise that already covered the *shared* default and
    #: this extends to a *per-node* one. Blocking the exit code here would
    #: fail every shipped package naming a real paid provider in any
    #: environment, CI included, that does not carry that provider's key.
    #: `REPEATED_SIDE_EFFECT` and `APPROVAL_COMES_TOO_LATE` are the sixth and
    #: seventh (`launch-readiness` 121), and they join for a reason none of the
    #: others needed: their condition is a **conservative assumption** rather
    #: than an observation. `BaseTool.side_effecting` defaults to `True` so an
    #: undeclared tool lands on the safe side, which means an adopter whose
    #: read-only tool predates the flag gets both sentences about a graph that
    #: is entirely correct. A guess may be loud; it may not exit 1.
    REPORTS = frozenset(
        {
            Finding.UNENFORCED_OUTCOME,
            Finding.UNWIRED_REVISE,
            Finding.STALE_TOOL_DENIAL,
            Finding.STATELESS_MOUNT_REDOES,
            Finding.OVERRIDE_APPLIED,
            Finding.MODEL_SELECTION_DEGRADED,
            Finding.REPEATED_SIDE_EFFECT,
            Finding.APPROVAL_COMES_TOO_LATE,
            Finding.UNDECLARED_FALLBACK,
            # The eighth, ninth and tenth (`launch-readiness` 94) are the
            # first reports about a run that used a *better* source than the
            # document records: a skill node's file on disk beats the copy
            # stored beside it, so the run is right and the document is stale.
            # `SKILL_FROM_SNAPSHOT` is the one that would hurt most on the
            # other side — `mcp_server.compile_workflow` is stateless and has
            # no package to read from, so every stateless compile of a
            # document naming a file records it, and exiting 1 there would
            # fail a correct run through a supported door for a condition that
            # door can never not be in.
            Finding.SKILL_SOURCE_DRIFTED,
            Finding.SKILL_FROM_SNAPSHOT,
            Finding.SKILL_FILE_UNUSED,
            # The eleventh, and a report for the plainest reason on this list:
            # the setting it names could be typed onto a card that could never
            # honour it, so the value is the platform's mistake rather than the
            # author's (`langchain-drift-watch` 01). Exiting 1 would fail a
            # working graph in somebody's CI over a field that never did
            # anything — and it would fail *every* document saved before the
            # field was withdrawn, since the editor wrote it onto every node.
            Finding.TIMEOUT_NEEDS_ASYNC_NODE,
        }
    )

    def test_the_two_sides_are_the_whole_enum(self) -> None:
        assert self.FAILURES | self.REPORTS == set(Finding)
        assert not (self.FAILURES & self.REPORTS)

    def test_report_only_is_exactly_the_report_side(self) -> None:
        assert REPORT_ONLY == self.REPORTS

    def test_an_unwired_revise_is_the_finding_this_ticket_moved(self) -> None:
        # Named alone as well as in the set, because the set above will grow
        # and this is the sentence the ticket was filed about: it is the same
        # observation `run_health` publishes as `unrouted`, which 49 classified
        # as a report. One observation cannot be both.
        assert Finding.UNWIRED_REVISE in REPORT_ONLY
