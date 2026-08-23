"""A grader whose `revise` port is unwired says so — at compile time and in the run.

`workflow-gallery` ticket 31. Draw a grader as a checkpoint — `pass` wired,
`revise` left alone — and the compiler plans one conditional edge. Then
`_router_for` resolves a `revise` verdict against a destination map that has no
`revise` in it and falls back to the first declared destination:

    >>> route({"decisions": {"grader1": "revise"}})
    'pass'

So an answer the grader rejected reached the output anyway, with
`decisions {"grader1": "revise"}` sitting beside it and `warnings: []`.

**The fallback is not the defect and is not removed.** Its docstring's argument
holds for a *missing* decision — "a stall here would be a hang, not an error".
Gallery example 19 (`support-triage`) used to rely on it deliberately: three
desk agents behind a classifier, `agent.feedback` is `maxConnections: 1`, so a
`revise` edge landing on a desk directly would have to pick one and a technical
failure redrafted by the billing desk is worse than no loop — so it shipped
`pass` only. `workflow-gallery` 48 gave the router a `feedback` input so the
edge could land there instead and re-dispatch to the desk that actually wrote
the draft, and `workflow-gallery` 78 wired that edge into the packaged copy of
the example (48 had only reached the dev workspace copy). No shipped example
relies on the fallback for `revise` any more; `web-research-digest` below
exercises the wired case, and this module now demonstrates the fallback
against a synthetic stub rather than a gallery example.

What was wrong is that a decision which **exists, is understood, and names a
branch the author never wired** got the same silence as one that was missing.
Both halves are reported here, in channels that already exist:

- **Compile time** — `Finding.UNWIRED_REVISE`, the same family as
  `UNENFORCED_OUTCOME`: a legal graph that came out less capable than it was
  drawn. Deliberately *not* `plan.warnings`, which
  `package_testing.assert_document_shape` requires to be empty and which
  `validate_workflow` reports as a PROBLEM — a document with an unwired
  `revise` is not a broken one, it is a document with something worth saying
  about it.
- **Run time** — `unrouted`, its own state key beside `forced`, turned into a
  sentence by `run_health(...).silent`. Not `decisions`, because the compiler
  dispatches on that exact label and a new value there would change control
  flow (the lesson `forced` already records).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openstategraph.api.registries import runtime_warnings
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import (
    CompiledPlan,
    WorkflowCompiler,
    run_health,
    unrouted_decision_warnings,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "openstategraph" / "examples"


class _StubGrader:
    """Rejects unless told otherwise — the only interesting case here."""

    def __init__(self, passed: bool = False) -> None:
        self.passed = passed

    def grade(self, candidate: str, question: str = "") -> Any:  # noqa: ARG002
        verdict = type("_Verdict", (), {})()
        verdict.passed = self.passed
        verdict.feedback = "" if self.passed else "not good enough"
        # Declared on `Verdict`, and read by `_grader` since
        # `workflow-gallery` 32. A double stands in for the whole type.
        verdict.reason = "passed" if self.passed else "not good enough"
        # And `failed_check` (`production-ready` 92) — empty, because this
        # double stands in for a judgement, not a deterministic rejection.
        verdict.failed_check = ""
        return verdict


def _grader(monkeypatch: Any, conditional: dict[str, str], *, passes: bool = False) -> Any:
    """`(runtime, run)` for one grader whose wired destinations are `conditional`."""
    runtime = NodeRuntime(model=None)
    monkeypatch.setattr(
        "openstategraph.compile.node_runtime.Grader",
        lambda **_kwargs: _StubGrader(passes),
    )
    plan = CompiledPlan()
    plan.edges = [("agent1", "grader1")]
    if conditional:
        plan.conditional = {"grader1": conditional}
    node = {"id": "grader1", "type": "route.grader", "data": {"maxAttempts": "3"}}
    return runtime, runtime._grader("grader1", node, plan)


class TestTheCompilerSaysItBeforeAnythingRuns:
    """The finding that would have made both of the ticket's discoveries free."""

    def test_a_grader_with_only_a_pass_edge_is_reported(self, monkeypatch: Any) -> None:
        runtime, _run = _grader(monkeypatch, {"pass": "out1"})
        assert runtime.diagnostics.any(Finding.UNWIRED_REVISE)

    def test_a_grader_wired_both_ways_is_never_reported(self, monkeypatch: Any) -> None:
        runtime, _run = _grader(monkeypatch, {"pass": "out1", "revise": "draft1"})
        assert not runtime.diagnostics.any(Finding.UNWIRED_REVISE)

    def test_a_grader_with_no_outgoing_edge_at_all_is_reported(self, monkeypatch: Any) -> None:
        """Worse, not better: a `revise` verdict reaches nothing whatsoever."""
        runtime, _run = _grader(monkeypatch, {})
        assert runtime.diagnostics.any(Finding.UNWIRED_REVISE)

    def test_the_sentence_names_the_grader_and_the_fix(self, monkeypatch: Any) -> None:
        runtime, _run = _grader(monkeypatch, {"pass": "out1"})
        matching = [w for w in runtime_warnings(runtime) if "grader1" in w]
        assert matching, runtime_warnings(runtime)
        sentence = matching[0]
        assert "revise" in sentence.lower()
        # A warning names the consequence, not the condition — and points at
        # the fix, which here is either an edge or a change of intent.
        assert "wire" in sentence.lower()
        assert "Traceback" not in sentence and ".py" not in sentence

    def test_the_sentence_teaches_the_router_relay_now_that_48_built_it(
        self, monkeypatch: Any
    ) -> None:
        """Fix 3, re-derived after `workflow-gallery` 48: a router now has a
        `feedback` input and replays its own branch decision, so an unwired
        revise behind a fan-out is a fixable mistake, not only a design
        choice. The sentence teaches that fix rather than offering "read
        this grader as a recorder" as an equally fine default."""
        runtime, _run = _grader(monkeypatch, {"pass": "out1"})
        matching = [w for w in runtime_warnings(runtime) if "grader1" in w]
        sentence = matching[0]
        assert "router" in sentence.lower()
        assert "fan-out" in sentence.lower() or "dispatch" in sentence.lower()

    def test_it_is_loud_and_not_fatal(self, monkeypatch: Any) -> None:
        """A grader used as a recorder is a legal graph that answers questions.

        `plan.warnings` is the channel that would refuse it — `validate` turns
        those into PROBLEMS FOUND and exits non-zero — so the finding must not
        land there.
        """
        _runtime, run = _grader(monkeypatch, {"pass": "out1"})
        result = run({"question": "q", "attempts": 0, "outputs": {"agent1": "draft"}})
        assert result["decisions"]["grader1"] == "revise"


class TestTheRunSaysItToo:
    """A compile-time warning is read once; a run is read every time."""

    def test_a_revise_that_reaches_nothing_is_recorded(self, monkeypatch: Any) -> None:
        _runtime, run = _grader(monkeypatch, {"pass": "out1"})
        result = run({"question": "q", "attempts": 0, "outputs": {"agent1": "draft"}})
        assert result["unrouted"] == {"grader1": "revise"}

    def test_a_wired_revise_records_nothing(self, monkeypatch: Any) -> None:
        _runtime, run = _grader(monkeypatch, {"pass": "out1", "revise": "draft1"})
        result = run({"question": "q", "attempts": 0, "outputs": {"agent1": "draft"}})
        assert "unrouted" not in result

    def test_a_pass_records_nothing_even_with_revise_unwired(self, monkeypatch: Any) -> None:
        """The common shape. A grader that approved lost nothing."""
        _runtime, run = _grader(monkeypatch, {"pass": "out1"}, passes=True)
        result = run({"question": "q", "attempts": 0, "outputs": {"agent1": "draft"}})
        assert result["decisions"]["grader1"] == "pass"
        assert "unrouted" not in result

    def test_an_exhausted_grader_is_not_this_case(self, monkeypatch: Any) -> None:
        """Gallery ticket 22's shape, kept separate. At the cap the branch is
        `pass`, the answer really was published, and `forced` already says so —
        nothing was unrouted."""
        _runtime, run = _grader(monkeypatch, {"pass": "out1"})
        result = run(
            {"question": "q", "revisions": {"grader1": 2}, "outputs": {"agent1": "draft"}}
        )
        assert result["decisions"]["grader1"] == "pass"
        assert "forced" in result
        assert "unrouted" not in result

    def test_the_decision_itself_is_unchanged(self, monkeypatch: Any) -> None:
        """The branch vocabulary stays `pass`/`revise`. A third label would
        route nowhere and would be a breaking change to what every trace row,
        warning and test reads."""
        _runtime, run = _grader(monkeypatch, {"pass": "out1"})
        result = run({"question": "q", "attempts": 0, "outputs": {"agent1": "draft"}})
        assert result["decisions"]["grader1"] == "revise"


class TestTheSentenceItReports:
    def test_it_names_the_grader(self) -> None:
        warnings = unrouted_decision_warnings({"grader1": "revise"})
        assert len(warnings) == 1
        assert "grader1" in warnings[0]

    def test_it_says_the_answer_shipped_anyway(self) -> None:
        """A reader must not think the run was blocked. It was not."""
        warning = unrouted_decision_warnings({"g1": "revise"})[0]
        assert "shipped" in warning.lower() or "published" in warning.lower()

    def test_nothing_unrouted_is_nothing_said(self) -> None:
        assert unrouted_decision_warnings({}) == []

    def test_every_grader_that_lost_a_verdict_is_named(self) -> None:
        assert len(unrouted_decision_warnings({"g1": "revise", "g2": "revise"})) == 2


class TestBothDoorsCarryIt:
    """`run_health` is the one assembly, and neither endpoint adds a source
    locally — that is exactly how the two doors drifted twice before."""

    def test_it_arrives_on_the_silent_list(self) -> None:
        health = run_health({}, {}, {}, {"grader1": "revise"})
        assert any("grader1" in w for w in health.silent)

    def test_it_never_reaches_the_failure_list(self) -> None:
        """`failures` feed `cli.run_exit_code`. A grader whose verdict went
        nowhere is a report about how the answer was reached, not a failed run."""
        health = run_health({}, {}, {}, {"grader1": "revise"})
        assert health.failures == []

    def test_the_argument_is_optional(self) -> None:
        """Both doors read state off different shapes and either can hand over
        `None` — the same tolerance the other three sources already have."""
        assert run_health({}, {}, {}, None).silent == []


class TestTheShippedExamples:
    """The packages the ticket names, asserted from their real documents.

    `support-triage` used to be here as the deliberately-unwired case (gallery
    31): `pass` only, falling back to `pass` on a `revise` verdict. That
    stopped being true of the *packaged* copy in `workflow-gallery` 78, which
    wired `grader1.revise -> router1.feedback` into it to match the dev
    workspace copy `48` had already fixed — so this class now pins the
    opposite fact about it: the fallback no longer applies, because there is
    no missing destination left for it to catch.
    """

    def _plan(self, slug: str) -> Any:
        document = json.loads((EXAMPLES / slug / "workflow.json").read_text())
        return WorkflowCompiler().plan(document.get("document", document))

    def test_example_19_no_longer_needs_the_fallback(self) -> None:
        """`support-triage` now wires both `pass` and `revise`, so a `revise`
        verdict routes to the router it actually names — not to `pass` by
        default."""
        plan = self._plan("support-triage")
        assert plan.conditional["grader1"] == {"pass": "gate1", "revise": "router1"}
        route = WorkflowCompiler._router_for("grader1", plan.conditional["grader1"])
        # The label, not the destination node — `revise` is itself now a
        # declared destination, so the fallback (which would return the
        # first-declared label) never gets a chance to run.
        assert route({"decisions": {"grader1": "revise"}}) == "revise"

    def test_example_19_is_still_a_valid_document(self) -> None:
        """Wiring the edge cannot introduce a warning: `plan.warnings` stays
        empty so `assert_document_shape` and `openstategraph validate` still
        pass."""
        assert self._plan("support-triage").warnings == []

    def test_example_18_wired_the_edge_and_is_not_reported(self) -> None:
        assert "revise" in self._plan("web-research-digest").conditional["grader1"]
