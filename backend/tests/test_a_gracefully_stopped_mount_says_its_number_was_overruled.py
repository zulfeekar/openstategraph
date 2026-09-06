"""A child that stopped itself under an overruled step budget says so — once.

`organisms-first-class` 62, the half `61` left.

**The silence, reproduced before anything was changed.** A copy of
`evaluator-optimizer` saving `settings.recursionLimit: 1000`, mounted into a
run given 60, with `56`'s never-relenting scripted grader. The child's own
guard stops the loop, the answer is published, `exit 0` — and:

```
warnings ['Grader "mount1/grader1" stopped revising because the workflow's
          step budget was nearly spent (3 supersteps left) ...']
```

Correct, and incomplete: the developer who saved 1000 on that package is told
the budget was nearly spent and not that their number was overruled by the
run's 60, on the one surface where the loop actually cost something. Three
levels deep was identical.

**Why `61` did not cover it.** Its sentence is minted inside the mount
closure, which holds both numbers, and only on the *crash* path. This one is
minted in `workflow_compiler.step_budget_warnings` out of the `budget_stops`
state key, whose value was the child's `remaining` — the requested number
never crossed the mount boundary at all.

**How it crosses now: the value widens, no fifth channel.** `budget_stops`
already rides `nested_record` up through every mount beside `outputs`,
`forced` and `unrouted` — a seam that has lost a key three times — and the
streaming door folds these values through verbatim, so widening the value
keeps both doors agreeing for free. A stop is either `3` or
`{"remaining": 3, "overruled": [...]}`, read tolerantly by `read_budget_stop`.

**When it is worth saying, which is the judgement this ticket is.** Only when
the ceiling actually bit: the child stopped itself **and** had asked for more
than the run allowed. A package that asked for less got what it asked for; a
package that asked for more and finished comfortably was not harmed. Inventing
a sentence for either is noise nobody can act on, which `CLAUDE.md`'s law
forbids as squarely as it forbids promising the impossible.

**Once per package, not once per stop.** A package mounted three times saved
the number once, so it is deduplicated on the record itself.

No live model run: exhausting a step budget needs a model that never passes
and this environment has no provider credential. Every measurement is a
scripted model through a real `WorkflowCompiler`, the standard `56`, `59`,
`60` and `61` were measured on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph.cli import run_exit_code
from openstategraph.compile.workflow_compiler import step_budget_warnings
from openstategraph.loader import load_workflow
from openstategraph.step_budget import read_budget_stop, record_overruled_mount

from test_a_mount_is_sized_against_its_own_drawing import (  # noqa: E402
    FORBIDDEN_LABELS,
    VENDOR,
    _NeverRelents,
    _loop_package,
    _mounter,
)

#: Roomy enough that the child's own `56` guard stops the loop — a graceful
#: stop, `56`'s shape, not the crash `61` already reports on.
ROOMY = 60
#: Above `ROOMY`, so the mount boundary must overrule it.
GREEDY = 1000
#: Below `ROOMY`, so the mount boundary honours it whole.
MODEST = 10

OVERRULED = "may only ask for less"


def _lines(result: Any) -> list[str]:
    return [w for w in (result.warnings or []) if OVERRULED in w]


def _multi_mounter(root: Path, slug: str, target: str, mounts: int) -> Path:
    """A parent mounting the *same* package several times, in a chain.

    Each mount is a separate `invoke` with its own superstep counter, so all
    of them reach their own budget stop in one run — which is the only way to
    ask whether one saved number is reported once or `mounts` times.
    """
    package = root / slug
    package.mkdir()
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "title": "Q", "data": {},
         "position": {"x": 0, "y": 0}}
    ]
    edges: list[dict[str, Any]] = []
    previous = ("in1", "text")
    for index in range(1, mounts + 1):
        node_id = f"mount{index}"
        nodes.append({
            "id": node_id, "type": "workflow.subgraph", "title": f"Child {index}",
            "data": {"workflow": target}, "position": {"x": 300 * index, "y": 0},
        })
        edges.append({"source": {"nodeId": previous[0], "portId": previous[1]},
                      "target": {"nodeId": node_id, "portId": "input"}})
        previous = (node_id, "output")
    nodes.append({"id": "out1", "type": "output.formatted", "title": "A", "data": {},
                  "position": {"x": 300 * (mounts + 1), "y": 0}})
    edges.append({"source": {"nodeId": previous[0], "portId": previous[1]},
                  "target": {"nodeId": "out1", "portId": "input"}})
    (package / "workflow.json").write_text(json.dumps({
        "version": 1, "name": slug, "published": False,
        "savedAt": "2026-08-22T00:00:00+00:00",
        "document": {"version": 3, "name": slug, "settings": {},
                     "nodes": nodes, "edges": edges},
    }))
    return package


def _run(root: Path, child_budget: int | None, ceiling: int = ROOMY) -> Any:
    _loop_package(root, "graceful-child", child_budget)
    parent = _mounter(root, "graceful-parent", "graceful-child")
    return load_workflow(parent, model=_NeverRelents()).ask("Go.", recursion_limit=ceiling)


class TestTheOverruledRequestIsReported:
    """The defect: a graceful stop under a ceiling the child did not choose."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        return _run(tmp_path_factory.mktemp("greedy"), GREEDY)

    def test_the_silence_is_over(self, result: Any) -> None:
        assert len(_lines(result)) == 1, result.warnings

    def test_it_names_both_numbers_and_the_package(self, result: Any) -> None:
        line = _lines(result)[0]
        assert str(GREEDY) in line, line
        assert str(ROOMY) in line, line
        assert "graceful-child" in line, line

    def test_the_original_sentence_survives_beside_it(self, result: Any) -> None:
        """`56`'s sentence is the one about *this* loop and is not replaced."""
        stops = [w for w in result.warnings if "stopped revising" in w]
        assert len(stops) == 1, result.warnings
        assert "mount1/grader1" in stops[0]

    def test_it_is_a_report_and_not_a_failure(self, result: Any) -> None:
        """`56` settled that a graceful stop is exit 0, and nothing here moves
        it: the silent channel, never `.failures`, never a non-zero code."""
        assert result.failures == []
        assert run_exit_code(result) == 0
        assert "a draft of the answer" in str(result)

    def test_no_vendor_copy_and_no_forbidden_label(self, result: Any) -> None:
        readable = " ".join([str(result), *result.warnings, *result.failures]).lower()
        for phrase in (*VENDOR, *FORBIDDEN_LABELS):
            assert phrase.lower() not in readable, phrase


class TestItIsSaidOnlyWhenItIsWorthSaying:
    """The inverses. A sentence nobody can act on is the noise regression."""

    def test_a_child_that_asked_for_less_says_nothing_extra(self, tmp_path: Path) -> None:
        result = _run(tmp_path, MODEST)
        assert _lines(result) == [], result.warnings
        assert any("stopped revising" in w for w in result.warnings)

    def test_a_child_that_asked_for_nothing_says_nothing_extra(self, tmp_path: Path) -> None:
        result = _run(tmp_path, None)
        assert _lines(result) == [], result.warnings

    def test_a_child_that_asked_for_more_and_finished_says_nothing(
        self, tmp_path: Path
    ) -> None:
        """The case that was never harmed: the ceiling was lower than the
        request and the loop never came near it, so there is nothing to
        explain. It holds structurally rather than by a guard: the record
        rides a `budget_stops` value, so a mount with no stop has nothing to
        put it on — which is why the fires-always mutation is expressed
        against the two cases above, where a stop exists and the request does
        not deserve a sentence."""
        _loop_package(tmp_path, "settled-child", GREEDY)
        payload = json.loads((tmp_path / "settled-child" / "workflow.json").read_text())
        for node in payload["document"]["nodes"]:
            if node["id"] == "grader1":
                node["data"]["maxAttempts"] = 1
        (tmp_path / "settled-child" / "workflow.json").write_text(json.dumps(payload))
        parent = _mounter(tmp_path, "settled-parent", "settled-child")
        result = load_workflow(parent, model=_NeverRelents()).ask(
            "Go.", recursion_limit=ROOMY
        )
        assert _lines(result) == [], result.warnings
        assert run_exit_code(result) == 0


class TestOnePackageIsOneSentence:
    """Mounted three times, saved once, said once."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        root = tmp_path_factory.mktemp("thrice")
        _loop_package(root, "thrice-child", GREEDY)
        parent = _multi_mounter(root, "thrice-parent", "thrice-child", 3)
        return load_workflow(parent, model=_NeverRelents()).ask("Go.", recursion_limit=ROOMY)

    def test_three_mounts_all_stopped(self, result: Any) -> None:
        stops = [w for w in result.warnings if "stopped revising" in w]
        assert len(stops) == 3, result.warnings
        assert {"mount1/grader1", "mount2/grader1", "mount3/grader1"} == {
            line.split('"')[1] for line in stops
        }

    def test_and_the_overruled_number_is_said_once(self, result: Any) -> None:
        assert len(_lines(result)) == 1, result.warnings


class TestThreeLevelsDeep:
    """The prefixing seam that has lost a key three times."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        root = tmp_path_factory.mktemp("deep")
        _loop_package(root, "deep62-grandchild", GREEDY)
        _mounter(root, "deep62-mid", "deep62-grandchild")
        top = _mounter(root, "deep62-top", "deep62-mid")
        return load_workflow(top, model=_NeverRelents()).ask("Go.", recursion_limit=ROOMY)

    def test_the_grandchilds_overruled_request_reaches_the_top(self, result: Any) -> None:
        line = _lines(result)
        assert len(line) == 1, result.warnings
        assert "deep62-grandchild" in line[0], line
        assert str(GREEDY) in line[0], line

    def test_the_stop_is_still_keyed_through_both_mounts(self, result: Any) -> None:
        stops = [w for w in result.warnings if "stopped revising" in w]
        assert len(stops) == 1, result.warnings
        assert "mount1/mount1/grader1" in stops[0]

    def test_exit_zero_holds_two_levels_up(self, result: Any) -> None:
        assert result.failures == []
        assert run_exit_code(result) == 0


class TestTheValueShape:
    """One widened value, read tolerantly and trusted strictly."""

    def test_a_bare_count_still_reads(self) -> None:
        assert read_budget_stop(3) == (3, [])

    def test_junk_is_not_interpreted_as_an_overrule(self) -> None:
        assert read_budget_stop({"remaining": 3, "overruled": "yes"}) == (3, [])
        assert read_budget_stop({"remaining": 3, "overruled": [1, "x"]}) == (3, [])

    def test_a_record_is_appended_not_replaced(self) -> None:
        once = record_overruled_mount(3, "inner", 200, 60)
        twice = record_overruled_mount(once, "outer", 300, 60)
        assert read_budget_stop(twice)[1] == [
            {"workflow": "inner", "requested": 200, "allowed": 60},
            {"workflow": "outer", "requested": 300, "allowed": 60},
        ]

    def test_the_same_record_cannot_double(self) -> None:
        once = record_overruled_mount(3, "inner", 200, 60)
        assert record_overruled_mount(once, "inner", 200, 60) == once

    def test_a_bare_count_produces_no_extra_sentence(self) -> None:
        assert len(step_budget_warnings({"grader1": 3})) == 1

    def test_two_stops_of_one_package_produce_one_extra_sentence(self) -> None:
        value = record_overruled_mount(3, "child", 200, 60)
        lines = step_budget_warnings({"a/grader1": value, "b/grader1": value})
        assert len(lines) == 3, lines
        assert sum(OVERRULED in line for line in lines) == 1, lines
