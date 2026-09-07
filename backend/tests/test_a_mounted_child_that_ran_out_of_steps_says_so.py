"""A mounted child that runs out of supersteps must speak in our words.

`organisms-first-class` 60, the residue of 56 and 59. Measured before
anything was written, on a parent whose only real step is a mount of a
package whose revision loop can never settle:

    load_workflow(parent, model=NeverRelents()).ask(q, recursion_limit=4)

    answer   ''
    failures ['Node "mount1" failed and produced no result. '
              'GraphRecursionError: Recursion limit of 4 reached without '
              'hitting a stop condition. You can increase the limit by '
              'setting the `recursion_limit` config key.\\nFor '
              'troubleshooting, visit: https://docs.langchain.com/...']
    exit     1

Two separate defects in one sentence, and a third one next to it.

**1 — a vendor's advice, which this product contradicts.** `56` removed
*"you can increase the limit"* from the loop door precisely because
`step_budget.py`'s and `stepBudget.ts`'s pinned copy says the opposite — *"a
bigger number only lets it run longer"* — and it came straight back through
the mount door, with a `docs.langchain.com` URL no other user-facing copy in
this product carries.

**2 — the mount door had nothing of its own to say.** A mount is *"another
workflow run as one isolated step — task in, answer out"*, and this one
produced no answer. That is a failure, and it stays one: unlike `56`'s loop
door, there is no candidate to publish, and a mount that quietly answered
nothing would be the silence `production-ready` 96 and `workflow-gallery` 52
exist to name. So the **channel and the exit code are unmoved** — only the
words change, from LangGraph's to ours.

**3 — a child that stopped *itself* was silent.** Above the floor the child's
own `56` guard fires, the loop stops, an answer is published — and the
sentence saying so died at the mount boundary exactly as `forced` and
`unrouted` did before `every-workflow-green` 16 and `workflow-gallery` 31.
Measured at `recursion_limit=10`: a correct answer, `warnings == []`. Three
keys had been carried up and the fourth, added an hour earlier by `56`, had
not.

**Whose number is it.** Settled here as *the run's*: a mount inherits the
budget of the run that mounted it, which is what it already effectively does
(the child's counter starts at zero, the ceiling is the same integer). What
is **not** settled is sizing — a child package's own `settings.recursionLimit`
is not consulted on the mount path, verified by saving 200 on the child and
watching a `recursion_limit=4` run die at 4. That is a serialised-field
decision with its own cost, filed as `organisms-first-class` 61 rather than
changed quietly here.

No live model run: a loop that never settles needs a model that never passes
and this environment has no provider credential. Every observation is a
scripted model through a real `WorkflowCompiler`, which is the standard both
parent tickets were measured on.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel, whatever_it_produced
from openstategraph.cli import run_exit_code
from openstategraph.loader import load_workflow

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"

#: Below `59`'s floor for `evaluator-optimizer`, so the child's own guard
#: cannot fire and the exhaustion reaches the boundary as an exception.
STARVED = 4
#: Above it, so the child stops itself and has something to publish.
ROOMY = 10

#: Vendor copy that must never reach a caller, in any of its parts.
VENDOR = ("increase the limit", "docs.langchain.com", "GraphRecursionError", "recursion limit")
#: Labels `CLAUDE.md` forbids wherever a user reads.
FORBIDDEN_LABELS = ("iterations", "max turns")


class _NeverRelents(RespondingModel):
    """The only model shape that can exhaust a step budget."""

    def __init__(self) -> None:
        super().__init__(rules=[])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        context = "\n".join(str(m.content) for m in messages)
        if "You are a grader" not in context:
            return self._reply("a draft of the answer")
        return self._reply("FAIL\nstill not good enough")


class _RelentsAtOnce(RespondingModel):
    """The inverse: the loop settles, so nothing here may cost it anything."""

    def __init__(self) -> None:
        super().__init__(rules=[])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        context = "\n".join(str(m.content) for m in messages)
        if "You are a grader" not in context:
            return self._reply("a draft of the answer")
        return self._reply("PASS")


def _packages(root: Path, child_budget: int | None = None) -> Path:
    """A parent whose one real step mounts a child that cannot settle.

    Built rather than borrowed: `nested-mounts` composes three documents and
    none of them loops, so it can only show the exhaustion by being starved
    below what its own three nodes cost — which measures the parent, not the
    mount.
    """
    child = root / "runaway-child"
    shutil.copytree(EXAMPLES / "evaluator-optimizer", child)
    payload = json.loads((child / "workflow.json").read_text())
    for node in payload["document"]["nodes"]:
        if node["id"] == "grader1":
            node["data"]["maxAttempts"] = 500
    if child_budget is not None:
        payload["document"].setdefault("settings", {})["recursionLimit"] = child_budget
    (child / "workflow.json").write_text(json.dumps(payload))

    parent = root / "runaway-parent"
    parent.mkdir()
    (parent / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "Runaway Parent",
                "published": False,
                "savedAt": "2026-08-22T00:00:00+00:00",
                "document": {
                    "version": 3,
                    "name": "Runaway Parent",
                    "settings": {},
                    "nodes": [
                        {"id": "in1", "type": "input.text", "title": "Q", "data": {},
                         "position": {"x": 0, "y": 0}},
                        {"id": "mount1", "type": "workflow.subgraph", "title": "Child",
                         "data": {"workflow": "runaway-child"},
                         "position": {"x": 300, "y": 0}},
                        {"id": "out1", "type": "output.formatted", "title": "A", "data": {},
                         "position": {"x": 600, "y": 0}},
                    ],
                    "edges": [
                        {"source": {"nodeId": "in1", "portId": "text"},
                         "target": {"nodeId": "mount1", "portId": "input"}},
                        {"source": {"nodeId": "mount1", "portId": "output"},
                         "target": {"nodeId": "out1", "portId": "input"}},
                    ],
                },
            }
        )
    )
    return parent


def _run(root: Path, model: Any, budget: int, child_budget: int | None = None) -> Any:
    parent = _packages(root, child_budget)
    workflow = load_workflow(parent, model=model)
    return whatever_it_produced(
        lambda: workflow.ask("Describe the export fix.", recursion_limit=budget)
    )


def _everything_a_caller_reads(result: Any) -> str:
    return " ".join(
        [
            str(result),
            *(result.warnings or []),
            *(result.failures or []),
            *(str(v) for v in (result.outputs or {}).values()),
            *(str(v) for v in (getattr(result, "nested_outputs", None) or {}).values()),
        ]
    ).lower()


class TestTheChildsExhaustionArrivesInOurWords:
    """The starved child: below the floor, so its own guard cannot save it."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        return _run(tmp_path_factory.mktemp("starved"), _NeverRelents(), STARVED)

    def test_no_vendor_copy_reaches_any_surface(self, result: Any) -> None:
        """The whole of defect 1, at every place a caller looks."""
        readable = _everything_a_caller_reads(result)
        for phrase in VENDOR:
            assert phrase.lower() not in readable, phrase

    def test_the_forbidden_labels_are_absent(self, result: Any) -> None:
        readable = _everything_a_caller_reads(result)
        for label in FORBIDDEN_LABELS:
            assert label not in readable, label

    def test_it_says_the_step_budget_ran_out(self, result: Any) -> None:
        line = " ".join(result.failures or [])
        assert "step budget" in line.lower()
        assert "supersteps" in line.lower()

    def test_it_names_the_mount_and_the_package(self, result: Any) -> None:
        """Which step, and which document — the two things a reader needs to
        find the drawing that could not finish."""
        line = " ".join(result.failures or [])
        assert "mount1" in line
        assert "runaway-child" in line

    def test_it_says_the_budget_is_the_runs(self, result: Any) -> None:
        """The reading this ticket settled, said where it is acted on: a
        mount spends the budget of the run that mounted it."""
        assert "run" in " ".join(result.failures or []).lower()

    def test_it_stays_a_failure_and_keeps_its_exit_code(self, result: Any) -> None:
        """Unlike `56`'s loop door there is no candidate to publish, so the
        channel does not move: a mount that produced no answer failed."""
        assert len(result.failures or []) == 1, result.failures
        assert run_exit_code(result) == 1

    def test_the_childs_own_saved_budget_does_not_change_this(
        self, tmp_path: Path
    ) -> None:
        """`organisms-first-class` 61 in one assertion: the child saves 200
        supersteps and still dies at the run's 4."""
        result = _run(tmp_path, _NeverRelents(), STARVED, child_budget=200)
        assert len(result.failures or []) == 1
        assert "step budget" in result.failures[0].lower()


class TestAChildThatStoppedItselfIsHeard:
    """Defect 3: above the floor the child's `56` guard fires and publishes,
    and the sentence saying so must cross the mount boundary."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        return _run(tmp_path_factory.mktemp("roomy"), _NeverRelents(), ROOMY)

    def test_the_answer_the_child_had_is_published(self, result: Any) -> None:
        assert "a draft of the answer" in str(result)

    def test_the_budget_stop_is_reported_exactly_once(self, result: Any) -> None:
        lines = [w for w in (result.warnings or []) if "step budget" in w.lower()]
        assert len(lines) == 1, result.warnings

    def test_it_is_keyed_under_the_mount_it_happened_in(self, result: Any) -> None:
        """`mount1/grader1`, the same key `nested_record` mints for outputs
        and `streaming.py` folds from the child's own frames — so the two
        doors cannot disagree about it."""
        lines = [w for w in (result.warnings or []) if "step budget" in w.lower()]
        assert "mount1/grader1" in lines[0]

    def test_it_is_on_the_silent_channel_and_moves_no_exit_code(self, result: Any) -> None:
        """`bc58fc1`'s rule: the run completed, took a wired edge and
        published, so this is a report about how the answer was reached."""
        assert result.failures == []
        assert run_exit_code(result) == 0


class TestASettlingChildPaysNothing:
    """The inverse that would still be green if the guard fired always."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        return _run(tmp_path_factory.mktemp("settles"), _RelentsAtOnce(), ROOMY)

    def test_the_answer_is_the_childs(self, result: Any) -> None:
        assert "a draft of the answer" in str(result)

    def test_nothing_is_reported_about_a_budget(self, result: Any) -> None:
        assert [w for w in (result.warnings or []) if "step budget" in w.lower()] == []

    def test_and_nothing_failed(self, result: Any) -> None:
        assert result.failures == []
        assert run_exit_code(result) == 0
