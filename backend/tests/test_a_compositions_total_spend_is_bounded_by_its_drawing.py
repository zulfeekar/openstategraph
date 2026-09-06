"""What a whole composition may spend, counted rather than feared.

`organisms-first-class` 63, whose title said *unbounded*. It is not, and the
first job of this file is the measurement that settles that.

**Measured, on `56`'s never-relenting scripted grader at `recursion_limit=60`**
— one loop package (`evaluator-optimizer` at `maxAttempts: 500`) instantiated
in five different drawings:

| drawing | loop leaves | model calls |
| --- | --- | --- |
| top → leaf | 1 | 56 |
| top → mid → leaf (three levels) | 1 | 56 |
| top → leaf, leaf, leaf | 3 | 168 |
| two mids of two leaves each | 4 | 224 |
| three levels branching two-by-two | 8 | 448 |

**Depth on its own costs nothing.** Row two is three levels deep and spends
exactly what row one spends. The cost tracks the number of mount *instances in
the expansion*, which is a property of the drawing — depth multiplies only
because a branching tree's leaf count is a product, which is the same sentence
as "a drawing with eight loops in it runs eight loops".

**And the expansion is finite, statically.** `NodeRuntime._subgraph` compiles
every child eagerly at build time and refuses a mount cycle there
(`_ancestry`), so by the time a graph exists, every mount it will ever make has
already been compiled and counted. A worst case therefore *exists* and is
computable before the run starts: the sum, over the top graph and every mount
instance below it, of the ceiling each one runs under — `61`'s downward-only
cap applied at every edge.

**So the answer taken is reporting, not preventing**, and the two preventions
are rejected here rather than in prose:

- **One shared, decrementing allowance** across the composition is what
  "bound the total" would mean, and it makes a mount's cost depend on what ran
  before it. `CLAUDE.md` defines a mount as *"another workflow run as one
  isolated step — task in, answer out"*; a package that behaves differently in
  the second position than in the first is not that.
  `TestIsolationSurvives` pins the rejection by measuring the same package in
  both positions.
- **A depth-scaled ceiling** — each level gets a fraction — is bounded and
  position-independent, and silently starves the innermost loop, which is
  `61`'s stated cost multiplied. `TestTheBoundIsNotScaledByDepth` pins it: the
  ceiling a leaf runs under does not shrink with depth.

No live model run: exhausting a step budget needs a model that never passes and
this environment has no provider credential. Every measurement here is a
scripted model through a real `WorkflowCompiler`, the standard `56`, `59`,
`60`, `61` and `62` were all measured on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openstategraph.loader import load_workflow
from openstategraph.step_budget import composition_step_budget

from test_a_mount_is_sized_against_its_own_drawing import (
    ROOMY,
    SMALL,
    _NeverRelents,
    _loop_package,
)


class _Counting(_NeverRelents):
    """The never-relenting grader, plus a tally of what it was asked."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        self.calls += 1
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _mounter(root: Path, slug: str, targets: list[str], budget: int | None = None) -> Path:
    """Input → mount → mount → … → output, and nothing else that costs a step.

    `61`'s helper takes one target; a composition's shape is the *number* of
    mounts as much as the depth, so this one takes a list. Chained rather than
    fanned so the mounts run in a known order — which is what makes
    `TestIsolationSurvives` a measurement of position.
    """
    import json

    package = root / slug
    package.mkdir()
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "title": "Q", "data": {},
         "position": {"x": 0, "y": 0}}
    ]
    edges: list[dict[str, Any]] = []
    previous = ("in1", "text")
    for index, target in enumerate(targets, start=1):
        node_id = f"mount{index}"
        nodes.append({"id": node_id, "type": "workflow.subgraph", "title": target,
                      "data": {"workflow": target},
                      "position": {"x": 300 * index, "y": 0}})
        edges.append({"source": {"nodeId": previous[0], "portId": previous[1]},
                      "target": {"nodeId": node_id, "portId": "input"}})
        previous = (node_id, "output")
    nodes.append({"id": "out1", "type": "output.formatted", "title": "A", "data": {},
                  "position": {"x": 300 * (len(targets) + 1), "y": 0}})
    edges.append({"source": {"nodeId": previous[0], "portId": previous[1]},
                  "target": {"nodeId": "out1", "portId": "input"}})
    document: dict[str, Any] = {"version": 3, "name": slug, "settings": {},
                                "nodes": nodes, "edges": edges}
    if budget is not None:
        document["settings"]["recursionLimit"] = budget
    (package / "workflow.json").write_text(json.dumps(
        {"version": 1, "name": slug, "published": False,
         "savedAt": "2026-08-22T00:00:00+00:00", "document": document}))
    return package


def _run(top: Path, ceiling: int = ROOMY) -> tuple[Any, int, Any]:
    """The run, the model calls it made, and the loaded workflow."""
    model = _Counting()
    workflow = load_workflow(top, model=model)
    result = workflow.ask("Go.", recursion_limit=ceiling)
    return result, model.calls, workflow


def _one_leaf(root: Path) -> Path:
    _loop_package(root, "leaf", None)
    return _mounter(root, "top", ["leaf"])


class TestWhatDepthActuallyCosts:
    """The ticket's premise, measured. Depth alone is free; instances are not."""

    @pytest.fixture(scope="class")
    def shallow(self, tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, int, Any]:
        return _run(_one_leaf(tmp_path_factory.mktemp("shallow")))

    @pytest.fixture(scope="class")
    def deep(self, tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, int, Any]:
        root = tmp_path_factory.mktemp("deep")
        _loop_package(root, "leaf", None)
        _mounter(root, "mid", ["leaf"])
        return _run(_mounter(root, "top", ["mid"]))

    @pytest.fixture(scope="class")
    def wide(self, tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, int, Any]:
        root = tmp_path_factory.mktemp("wide")
        _loop_package(root, "leaf", None)
        return _run(_mounter(root, "top", ["leaf", "leaf", "leaf"]))

    def test_three_levels_deep_spends_what_one_level_spends(
        self, deep: tuple[Any, int, Any], shallow: tuple[Any, int, Any]
    ) -> None:
        """Growth is **not** multiplicative in depth. One loop is one loop
        however many mounts it is wrapped in."""
        assert deep[1] == shallow[1], (deep[1], shallow[1])

    def test_three_loops_side_by_side_spend_three_times(
        self, wide: tuple[Any, int, Any], shallow: tuple[Any, int, Any]
    ) -> None:
        """Growth is additive in the number of mount instances drawn."""
        assert wide[1] == 3 * shallow[1], (wide[1], shallow[1])

    def test_and_every_one_of_them_still_publishes(self, wide: tuple[Any, int, Any]) -> None:
        result = wide[0]
        assert result.failures == []
        stops = [w for w in (result.warnings or []) if "step budget" in w.lower()]
        assert len(stops) == 3, result.warnings


class TestTheWorstCaseIsReported:
    """A number a caller can have *before* the run, because the compiler has
    already built every mount by then."""

    def test_a_workflow_with_no_mounts_reports_its_own_ceiling(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """The inverse that would still be green if the bound double-counted:
        a single-level run is untouched."""
        root = Path(str(tmp_path))
        leaf = _loop_package(root, "leaf", None)
        workflow = load_workflow(leaf, model=_NeverRelents())
        assert workflow.composition_step_budget(ROOMY) == ROOMY

    def test_it_counts_one_ceiling_per_mount_instance(self, tmp_path: Path) -> None:
        """Four graphs — the top and three mounts — so four ceilings."""
        _loop_package(tmp_path, "leaf", None)
        top = _mounter(tmp_path, "top", ["leaf", "leaf", "leaf"])
        workflow = load_workflow(top, model=_NeverRelents())
        assert workflow.composition_step_budget(ROOMY) == 4 * ROOMY

    def test_a_chain_and_a_fan_of_the_same_size_report_the_same(
        self, tmp_path: Path
    ) -> None:
        """Three mounts is three mounts, in a row or in a tower — which is the
        measurement above, stated as a bound."""
        chain = tmp_path / "chain"
        chain.mkdir()
        _loop_package(chain, "leaf", None)
        _mounter(chain, "a", ["leaf"])
        _mounter(chain, "b", ["a"])
        tower = load_workflow(_mounter(chain, "top", ["b"]), model=_NeverRelents())

        fan = tmp_path / "fan"
        fan.mkdir()
        _loop_package(fan, "leaf", None)
        flat = load_workflow(_mounter(fan, "top", ["leaf", "leaf", "leaf"]),
                             model=_NeverRelents())
        assert tower.composition_step_budget(ROOMY) == flat.composition_step_budget(ROOMY)

    def test_the_bound_actually_bounds_a_real_three_level_run(
        self, tmp_path: Path
    ) -> None:
        """The one that makes it a bound rather than an arithmetic identity: a
        composition driven until every loop in it stops itself spends less than
        the number reported before it started."""
        _loop_package(tmp_path, "leaf", None)
        _mounter(tmp_path, "mid", ["leaf", "leaf"])
        top = _mounter(tmp_path, "top", ["mid", "mid"])
        result, calls, workflow = _run(top)
        bound = workflow.composition_step_budget(ROOMY)
        assert bound == 7 * ROOMY, bound
        # Two model calls per lap, and a lap costs at least one superstep.
        assert calls / 2 < bound, (calls, bound)
        assert result.failures == []

    def test_a_child_that_asked_for_less_lowers_the_bound(self, tmp_path: Path) -> None:
        """`61`'s downward-only cap composes: the bound is not a flat
        multiplication, it is the sum of the ceilings actually in play."""
        _loop_package(tmp_path, "leaf", SMALL)
        top = _mounter(tmp_path, "top", ["leaf"])
        workflow = load_workflow(top, model=_NeverRelents())
        assert workflow.composition_step_budget(ROOMY) == ROOMY + SMALL

    def test_the_runs_own_number_is_used_when_none_is_named(
        self, tmp_path: Path
    ) -> None:
        """No argument means the number this document would run under, so the
        answer never disagrees with `ask()`'s own resolution."""
        _loop_package(tmp_path, "leaf", None)
        top = _mounter(tmp_path, "top", ["leaf"], budget=SMALL)
        workflow = load_workflow(top, model=_NeverRelents())
        assert workflow.composition_step_budget() == 2 * SMALL


class TestIsolationSurvives:
    """Reading 2 — one shared, decrementing allowance — rejected and pinned.

    A mount is *"another workflow run as one isolated step"*. Under a shared
    allowance the second mount of a package would run under whatever the first
    left, so the same drawing would answer differently depending on where it
    sat. These two measurements are what would go red.
    """

    @pytest.fixture(scope="class")
    def both(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        root = tmp_path_factory.mktemp("positions")
        _loop_package(root, "leaf", None)
        return _run(_mounter(root, "top", ["leaf", "leaf"]))

    def test_the_same_package_costs_the_same_in_either_position(
        self, both: Any, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        alone = _run(_one_leaf(tmp_path_factory.mktemp("alone")))
        assert both[1] == 2 * alone[1], (both[1], alone[1])

    def test_neither_position_is_starved_into_a_failure(self, both: Any) -> None:
        result = both[0]
        assert result.failures == []
        stops = [w for w in (result.warnings or []) if "step budget" in w.lower()]
        assert len(stops) == 2, result.warnings


class TestTheBoundIsNotScaledByDepth:
    """Reading 3 — divide the ceiling among the levels — rejected and pinned.

    Under a depth-scaled ceiling the innermost loop would get a fraction, so a
    grandchild would make fewer laps than a child of the same package. It does
    not.
    """

    def test_a_grandchild_makes_the_same_laps_as_a_child(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        shallow_root = tmp_path_factory.mktemp("scale-shallow")
        _loop_package(shallow_root, "leaf", None)
        shallow = _run(_mounter(shallow_root, "top", ["leaf"]))

        deep_root = tmp_path_factory.mktemp("scale-deep")
        _loop_package(deep_root, "leaf", None)
        _mounter(deep_root, "mid", ["leaf"])
        deep = _run(_mounter(deep_root, "top", ["mid"]))

        assert deep[1] == shallow[1], (deep[1], shallow[1])


class TestTheArithmetic:
    """One function decides, so there is one thing to get right."""

    def test_no_mounts_is_the_ceiling_itself(self) -> None:
        assert composition_step_budget(60, {}) == 60

    def test_each_mount_adds_its_own_ceiling(self) -> None:
        mounts = {"a": _Mount(None), "b": _Mount(None)}
        assert composition_step_budget(60, mounts) == 180

    def test_a_saved_number_may_only_lower_a_branch(self) -> None:
        assert composition_step_budget(60, {"a": _Mount(20)}) == 80
        assert composition_step_budget(60, {"a": _Mount(1000)}) == 120

    def test_a_lowered_branch_lowers_everything_under_it(self) -> None:
        """The cap is inherited, so a small mid caps its own grandchild too."""
        deep = _Mount(20, {"g": _Mount(None)})
        assert composition_step_budget(60, {"a": deep}) == 60 + 20 + 20

    def test_it_is_the_same_whatever_order_the_mounts_are_in(self) -> None:
        small, large = _Mount(20), _Mount(None)
        assert composition_step_budget(60, {"a": small, "b": large}) == composition_step_budget(
            60, {"a": large, "b": small}
        )


class _Mount:
    """The two fields `composition_step_budget` reads off a `MountedGraph`."""

    def __init__(self, saved: int | None, mounts: Any = None) -> None:
        self.saved_step_budget = saved
        self.mounts = mounts or {}
