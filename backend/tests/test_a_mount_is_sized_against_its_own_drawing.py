"""A mounted package's own step budget reaches the mount path — downward only.

`organisms-first-class` 61, the half `60` refused to change quietly.

**What was reproduced first**, on `60`'s instrument (a parent whose one real
step mounts a copy of `evaluator-optimizer` at `maxAttempts: 500`, driven by a
scripted grader that never passes):

| child's saved `settings.recursionLimit` | run's ceiling | laps |
| --- | --- | --- |
| 200 | 4 | dies at 4, no answer |
| 10 | 60 | 28 |
| *(none)* | 60 | 28 |

The second and third rows are the whole defect in one comparison: the child's
saved number changed **nothing**, in either direction. Three levels deep is
the same — a grandchild saving 200 under a mid saving 300 spends the run's
number and neither saved number is consulted. `resolve_step_budget` is read by
`loader.py`, `api/routes/runs.py` and `mcp_server.py`, and by no mount.

**The reading taken, of the three the ticket priced: the third, narrowed.**
The child's saved number caps the **child**, and may only *lower* what the run
already allows:

    child's ceiling = min(the run's remaining allowance, what the child saved)

- **Reading 2 — the child's number simply wins — is rejected**, and the
  rejection is pinned below by `test_a_child_asking_for_more_gets_the_runs_number`
  and `test_a_child_asking_for_far_more_does_not_outrun_a_child_asking_for_nothing`.
  A caller who names a step budget has said what this run may cost; a mounted
  package saving 1000 would make a `recursion_limit=10` run unbounded in
  practice, which is the exact ceiling a budget exists to give.
- **Reading 1 — leave it — is rejected** because the downward direction can be
  honoured with no cost to the caller at all, and because a declared field that
  reaches one door and not another is the defect class
  `test_data_key_contract.py` was written for.

**So the field means one thing on both paths and the difference is named**: it
is the size of *this workflow*. Run directly, a caller's explicit number
overrides it either way (`resolve_step_budget` — the saved number is a
default). Mounted, the run's number is a **ceiling** rather than a preference,
so the saved number is a request that can only take less. Both are "how big is
this drawing"; the mount adds the caller's ceiling on top.

**And what cannot be honoured is said out loud.** When the child asked for
more than the run could give *and* then ran out, the mount's failure names
both numbers, so a reader is not left to infer that a field they set was
overruled. It is added to `60`'s sentence, in `60`'s vocabulary — no
"increase the limit", no vendor URL, no "iterations".

No live model run: exhausting a step budget needs a model that never passes
and this environment has no provider credential. Every measurement here is a
scripted model through a real `WorkflowCompiler`, the standard `56`, `59` and
`60` were all measured on.
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
from openstategraph.step_budget import MIN_STEP_BUDGET, mount_step_budget

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"

#: Roomy enough that the child's own `56` guard is what stops the loop, so the
#: lap count is a measurement of the ceiling in play rather than of a crash.
ROOMY = 60
#: Below `59`'s floor for `evaluator-optimizer`: the child cannot stop itself
#: and the exhaustion arrives at the mount boundary.
STARVED = 4
#: The smallest budget `workflow_step_budget` will not clamp away.
SMALL = MIN_STEP_BUDGET

#: Copy that must never reach a caller — `56`'s and `60`'s pinned refusals.
VENDOR = ("increase the limit", "docs.langchain.com", "GraphRecursionError")
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


def _loop_package(root: Path, slug: str, budget: int | None) -> Path:
    """A copy of `evaluator-optimizer` whose loop can never settle."""
    package = root / slug
    shutil.copytree(EXAMPLES / "evaluator-optimizer", package)
    payload = json.loads((package / "workflow.json").read_text())
    for node in payload["document"]["nodes"]:
        if node["id"] == "grader1":
            node["data"]["maxAttempts"] = 500
    if budget is not None:
        payload["document"].setdefault("settings", {})["recursionLimit"] = budget
    (package / "workflow.json").write_text(json.dumps(payload))
    return package


def _mounter(root: Path, slug: str, target: str, budget: int | None = None) -> Path:
    """Input → mount → output, and nothing else that costs a superstep."""
    package = root / slug
    package.mkdir()
    document: dict[str, Any] = {
        "version": 3,
        "name": slug,
        "settings": {},
        "nodes": [
            {"id": "in1", "type": "input.text", "title": "Q", "data": {},
             "position": {"x": 0, "y": 0}},
            {"id": "mount1", "type": "workflow.subgraph", "title": "Child",
             "data": {"workflow": target}, "position": {"x": 300, "y": 0}},
            {"id": "out1", "type": "output.formatted", "title": "A", "data": {},
             "position": {"x": 600, "y": 0}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "mount1", "portId": "input"}},
            {"source": {"nodeId": "mount1", "portId": "output"},
             "target": {"nodeId": "out1", "portId": "input"}},
        ],
    }
    if budget is not None:
        document["settings"]["recursionLimit"] = budget
    (package / "workflow.json").write_text(
        json.dumps({"version": 1, "name": slug, "published": False,
                    "savedAt": "2026-08-22T00:00:00+00:00", "document": document})
    )
    return package


def _run_one_level(root: Path, child_budget: int | None, ceiling: int) -> Any:
    _loop_package(root, "sized-child", child_budget)
    parent = _mounter(root, "sized-parent", "sized-child")
    workflow = load_workflow(parent, model=_NeverRelents())
    return whatever_it_produced(
        lambda: workflow.ask("Describe it.", recursion_limit=ceiling)
    )


def _laps(result: Any) -> int:
    """How many revision laps the child actually made — the loop's cost, and
    therefore the only honest read of which ceiling was in play."""
    return int(getattr(result, "attempts", 0) or 0)


class TestAChildAskingForLessGetsLess:
    """The direction that can be honoured with no cost to the caller."""

    @pytest.fixture(scope="class")
    def baseline(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        """The same package saving nothing: what the run alone buys."""
        return _run_one_level(tmp_path_factory.mktemp("baseline"), None, ROOMY)

    @pytest.fixture(scope="class")
    def small(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        return _run_one_level(tmp_path_factory.mktemp("small"), SMALL, ROOMY)

    def test_the_saved_number_shortens_the_loop(self, small: Any, baseline: Any) -> None:
        """The measurement that was identical before this ticket: 28 and 28."""
        assert _laps(small) < _laps(baseline), (_laps(small), _laps(baseline))

    def test_it_still_publishes_the_answer_it_had(self, small: Any) -> None:
        """`56`'s shape, not a crash: a child that stops itself has something
        to hand back, and stopping sooner must not change that."""
        assert "a draft of the answer" in str(small)
        assert small.failures == []
        assert run_exit_code(small) == 0

    def test_and_says_so_on_the_silent_channel(self, small: Any) -> None:
        lines = [w for w in (small.warnings or []) if "step budget" in w.lower()]
        assert len(lines) == 1, small.warnings
        assert "mount1/grader1" in lines[0]

    def test_a_child_saving_nothing_is_unchanged(self, baseline: Any) -> None:
        """The inverse that would still be green if the new ceiling were
        applied to every mount rather than to one that asked."""
        assert _laps(baseline) == 28, _laps(baseline)


class TestACallersCeilingIsNeverExceeded:
    """Reading 2, rejected and pinned. This is the regression the change
    risks, so it is tested in the direction that would catch an overspend."""

    @pytest.fixture(scope="class")
    def baseline(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        return _run_one_level(tmp_path_factory.mktemp("ceil-base"), None, ROOMY)

    @pytest.fixture(scope="class")
    def greedy(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        return _run_one_level(tmp_path_factory.mktemp("greedy"), 1000, ROOMY)

    def test_a_child_asking_for_far_more_does_not_outrun_a_child_asking_for_nothing(
        self, greedy: Any, baseline: Any
    ) -> None:
        """A mount saving the maximum, inside a run given 60. If the child's
        number won, this loop would make hundreds of laps."""
        assert _laps(greedy) == _laps(baseline), (_laps(greedy), _laps(baseline))

    def test_a_child_asking_for_more_gets_the_runs_number(
        self, tmp_path: Path
    ) -> None:
        """`60`'s own measurement, unmoved: 200 saved, 4 given, dead at 4."""
        result = _run_one_level(tmp_path, 200, STARVED)
        assert len(result.failures or []) == 1, result.failures
        assert "step budget" in result.failures[0].lower()
        assert run_exit_code(result) == 1


class TestTheCallerIsToldWhatCouldNotBeHonoured:
    """A field set by a developer and overruled must not be overruled in
    silence — and the sentence stays in this product's vocabulary."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        return _run_one_level(tmp_path_factory.mktemp("told"), 200, STARVED)

    def test_it_names_both_numbers(self, result: Any) -> None:
        line = " ".join(result.failures or [])
        assert "200" in line, line
        assert str(STARVED) in line, line

    def test_it_still_names_the_mount_and_the_package(self, result: Any) -> None:
        line = " ".join(result.failures or [])
        assert "mount1" in line
        assert "sized-child" in line

    def test_no_vendor_copy_and_no_forbidden_label(self, result: Any) -> None:
        readable = " ".join([str(result), *(result.warnings or []), *(result.failures or [])]).lower()
        for phrase in (*VENDOR, *FORBIDDEN_LABELS):
            assert phrase.lower() not in readable, phrase

    def test_a_child_that_asked_for_nothing_is_told_nothing_extra(
        self, tmp_path: Path
    ) -> None:
        """The inverse: no invented sentence about a field nobody set."""
        result = _run_one_level(tmp_path, None, STARVED)
        line = " ".join(result.failures or [])
        assert "saved" not in line.lower(), line


class TestThreeLevelsDeep:
    """The ticket's framing names one level. A grandchild is where a mount
    inside a mount reads its own document — and it must obey the same rule."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        root = tmp_path_factory.mktemp("deep")
        _loop_package(root, "deep-grandchild", SMALL)
        _mounter(root, "deep-mid", "deep-grandchild")
        top = _mounter(root, "deep-top", "deep-mid")
        workflow = load_workflow(top, model=_NeverRelents())
        return whatever_it_produced(lambda: workflow.ask("Go.", recursion_limit=ROOMY))

    @pytest.fixture(scope="class")
    def baseline(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        root = tmp_path_factory.mktemp("deep-base")
        _loop_package(root, "deep-grandchild", None)
        _mounter(root, "deep-mid", "deep-grandchild")
        top = _mounter(root, "deep-top", "deep-mid")
        workflow = load_workflow(top, model=_NeverRelents())
        return whatever_it_produced(lambda: workflow.ask("Go.", recursion_limit=ROOMY))

    def test_the_grandchilds_own_number_reaches_it(self, result: Any, baseline: Any) -> None:
        assert _laps(result) < _laps(baseline), (_laps(result), _laps(baseline))

    def test_it_is_keyed_through_both_mounts(self, result: Any) -> None:
        lines = [w for w in (result.warnings or []) if "step budget" in w.lower()]
        assert len(lines) == 1, result.warnings
        assert "mount1/mount1/grader1" in lines[0]

    def test_the_answer_still_comes_back_up_two_levels(self, result: Any) -> None:
        assert "a draft of the answer" in str(result)
        assert result.failures == []


class TestTheResolution:
    """One function decides, so there is one thing to get right — and it is
    `min`, never `max`, never the child alone."""

    def _doc(self, value: Any) -> dict[str, Any]:
        return {"settings": {"recursionLimit": value}}

    def test_a_child_that_saved_nothing_inherits_untouched(self) -> None:
        assert mount_step_budget(60, {}) == 60
        assert mount_step_budget(60, {"settings": {}}) == 60
        assert mount_step_budget(60, None) == 60

    def test_a_smaller_saved_number_is_honoured(self) -> None:
        assert mount_step_budget(60, self._doc(20)) == 20

    def test_a_larger_saved_number_never_raises_the_ceiling(self) -> None:
        assert mount_step_budget(60, self._doc(1000)) == 60
        assert mount_step_budget(4, self._doc(200)) == 4

    def test_the_clamp_still_applies_before_the_comparison(self) -> None:
        """A saved 5 is a saved 10 (`workflow_step_budget`), so it must not
        arrive here as a 5 and starve a run below the floor `59` computed."""
        assert mount_step_budget(60, self._doc(5)) == MIN_STEP_BUDGET

    def test_nonsense_is_not_interpreted(self) -> None:
        for junk in ("many", None, True, [], 3.5):
            assert mount_step_budget(60, self._doc(junk)) == 60
        assert mount_step_budget(60, {"settings": "nope"}) == 60
