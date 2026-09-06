"""A run that spends its whole step budget says so in this product's words.

`launch-readiness/176`. `organisms-first-class/60` translated the exhaustion
that arrives at a **mount** boundary; the top-level case — the common one,
every document without a mount — was still reported verbatim:

    Recursion limit of 6 reached without hitting a stop condition. You can
    increase the limit by setting the `recursion_limit` config key.
    For troubleshooting, visit: https://docs.langchain.com/.../GRAPH_RECURSION_LIMIT

Every clause of that is out of this product's vocabulary: LangGraph type names
on a user surface (portability guardrail 4 — the settled word is **step
budget**, counted in **supersteps**), the advice `step_budget.py` exists to
contradict, and a vendor URL that sends an adopter off-product to debug a
document we compiled.

And the second half: **neither overrun left a row in the run store.** The runs
that cost the most and returned nothing were the ones a reader asking *what has
this machine run, and what did it cost* was never told about.

The tests come in the two shapes `test_every_run_door_writes_itself_down.py`
uses, for the same reason: the recurring defect is never "this door is wrong",
it is "the fix reached some doors and not others".
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from openstategraph.errors import StepBudgetExhausted
from openstategraph.run_sinks import RunRecord, read_runs, reset_run_sink_registry
from openstategraph.step_budget import MIN_STEP_BUDGET
from openstategraph.api.audience import Audience

#: What must not reach any surface. LangGraph's own sentence, clause by clause.
VENDOR_WORDS: tuple[str, ...] = (
    "Recursion limit",
    "recursion_limit",
    "GraphRecursionError",
    "docs.langchain.com",
    "increase the limit",
)

#: The budget every door is driven with. `MIN_STEP_BUDGET` rather than a
#: literal, because it is the smallest number `RunRequest` will accept and a
#: smaller one is a 422 at the HTTP doors rather than an overrun — and because
#: no library number of LangGraph's may be written down here at all
#: (`test_a_library_default_is_never_literalised.py`). The document below is
#: longer than this by four supersteps, so the smallest legal budget is also
#: the cheapest one to overrun.
BUDGET = MIN_STEP_BUDGET


def _n(i: str, t: str, **d: Any) -> dict[str, Any]:
    return {"id": i, "type": t, "data": d, "position": {"x": 0, "y": 0}}


def _e(s: str, sp: str, t: str, tp: str) -> dict[str, Any]:
    return {"source": {"nodeId": s, "portId": sp}, "target": {"nodeId": t, "portId": tp}}


#: How many `function.format_report` nodes stand between the input and the
#: output. One superstep each, so the run needs `CHAIN + 2` and has `BUDGET`
#: — over the ceiling by a comfortable margin and still under a tenth of a
#: second, because not one of these nodes reaches a model.
CHAIN = 14


def _document() -> dict[str, Any]:
    """A graph that is simply longer than the budget, and reaches no model.

    It was a two-node all-static cycle until `launch-readiness/177` landed the
    rule that such a document does not compile — `always_taken_cycles` puts a
    finding on `plan.warnings`, and the MCP door refuses a document that
    carries one before it can run. That rule is right and is not weakened
    here; what it means is that the cheapest way to spend a real budget is no
    longer a loop.

    So: a straight chain of `CHAIN` mechanical nodes. It compiles clean
    (`validate_document` answers `(True, [])`), it terminates in principle,
    and it exhausts `BUDGET` supersteps before it gets to the end. The
    overrun is LangGraph's, raised from `ainvoke`/`astream` exactly as it is
    on a live document — which is the only property this file needs, and the
    one a cycle was only ever a shortcut to.
    """
    chain = [f"s{i}" for i in range(CHAIN)]
    nodes = [_n("in1", "input.text")]
    nodes += [_n(step, "function.format_report") for step in chain]
    nodes.append(_n("out1", "output.formatted"))

    edges = [_e("in1", "text", chain[0], "candidate")]
    edges += [
        _e(source, "report", target, "candidate")
        for source, target in zip(chain, chain[1:])
    ]
    edges.append(_e(chain[-1], "report", "out1", "result"))

    return {
        "version": 2,
        "name": "Outruns its budget",
        "nodes": nodes,
        "edges": edges,
    }


def _assert_ours(text: str) -> None:
    for word in VENDOR_WORDS:
        assert word not in text, f"{word!r} reached a user surface:\n{text}"
    assert "step budget" in text.lower(), f"the settled word is missing:\n{text}"


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "runs.sqlite"
    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(path))
    reset_run_sink_registry()
    yield path
    reset_run_sink_registry()


@pytest.fixture()
def workflows_root(tmp_path: Path) -> Path:
    root = tmp_path / "workflows"
    root.mkdir()
    return root


@pytest.fixture()
def package(workflows_root: Path) -> Path:
    pkg = workflows_root / "outruns-its-budget"
    pkg.mkdir()
    (pkg / "workflow.json").write_text(json.dumps({"document": _document()}))
    return pkg


def _rows(store: Path) -> list[RunRecord]:
    return read_runs(store)


class TestTheLibraryDoor:
    """`CompiledWorkflow.ask` — the CLI's door and a package's own `tests/`."""

    def test_it_raises_one_of_ours(self, store: Path, package: Path) -> None:
        from openstategraph.loader import load_workflow

        with pytest.raises(StepBudgetExhausted) as raised:
            load_workflow(package).ask("anything", recursion_limit=BUDGET)
        _assert_ours(str(raised.value))

    def test_it_names_the_budget_that_ran_out(self, store: Path, package: Path) -> None:
        """The one number a reader needs to size the next run, and the one the
        vendor's sentence carried that was worth keeping."""
        from openstategraph.loader import load_workflow

        with pytest.raises(StepBudgetExhausted) as raised:
            load_workflow(package).ask("anything", recursion_limit=BUDGET)
        assert str(BUDGET) in str(raised.value)
        assert "superstep" in str(raised.value)


class TestTheBlockingHttpDoor:
    def test_the_detail_is_ours(
        self, store: Path, workflows_root: Path
    ) -> None:
        from openstategraph.api.main import create_app

        client = TestClient(create_app(workflows_root=workflows_root))
        response = client.post(
            "/api/runs",
            json={
                "workflow": _document(),
                "question": "anything",
                "recursion_limit": BUDGET,
            },
        )
        assert response.status_code == 502, response.text
        _assert_ours(response.json()["detail"])


class TestTheStreamingDoor:
    def test_the_error_frame_is_ours(
        self, store: Path, workflows_root: Path
    ) -> None:
        """The developer audience, which is the one that gets a real sentence
        — a customer gets `GENERIC_FAILURE_MESSAGE` whatever failed."""
        from openstategraph.api.main import create_app

        client = TestClient(create_app(workflows_root=workflows_root))
        response = client.post(
            "/api/runs/stream",
            json={
                "workflow": _document(),
                "question": "anything",
                "recursion_limit": BUDGET,
                "audience": "developer",
            },
        )
        assert response.status_code == 200, response.text
        assert "event: error" in response.text
        _assert_ours(response.text)


class TestTheMcpDoor:
    """The strictest of the four: `run` calls `validate_document` first and
    answers *"The document does not compile."* rather than running a graph
    with a finding on it. That is why this door — and only this door — went
    red when `launch-readiness/177` made the old fixture a finding: the other
    three ran it and overran exactly as before."""

    def test_the_error_is_ours(self, store: Path, workflows_root: Path) -> None:
        from openstategraph.api.services import WorkflowServices
        from openstategraph.mcp_server import WorkflowRuns

        services = WorkflowServices(workflows_root=workflows_root)
        result = WorkflowRuns(services).run(
            document=_document(),
            question="anything",
            recursion_limit=BUDGET,
            audience=Audience.CUSTOMER,
        )
        assert result["error"], result
        _assert_ours(result["error"])


class TestAnOverrunIsARowOfItsOwn:
    """The half the ticket asked not to drop. A run that burned the whole
    budget is the row `guardrails/07` most wants and the one it never got."""

    def test_the_library_door_writes_it_down(self, store: Path, package: Path) -> None:
        from openstategraph.loader import load_workflow

        with pytest.raises(StepBudgetExhausted):
            load_workflow(package).ask("what did it cost", recursion_limit=BUDGET)

        rows = _rows(store)
        assert len(rows) == 1, "a run that spent the whole budget left no trace"
        assert rows[0].question == "what did it cost"
        assert rows[0].seconds > 0

    def test_it_is_its_own_kind_and_not_a_failure(
        self, store: Path, package: Path
    ) -> None:
        """`failed` means a node wrote the failure sentinel; none did. A
        finished `run` it is not either — its answer is nothing, and
        `launch-readiness/99` would learn from a blank. So a kind of its own,
        which is why `RunRecord.kind` is a tolerant string (`44`).

        This assertion read `True` for one afternoon, and the assertion was
        right both times. `RunTurn._assemble` derives `failed` from the
        door's own compile failures as well as the run's
        (`bool(self._failures or health.failures)`), and the old fixture's
        all-static cycle had become a compile finding on `plan.warnings`
        (`launch-readiness/177`) — which `load_workflow` carries into
        `failure_warnings` and the library door hands to the turn. So the row
        was reporting a document that could not compile, honestly, and the
        thing that had changed was the fixture rather than the answer. On a
        document that compiles, an overrun is `failed=False`: the only
        readers of the column are `runs list`, which prints `failed` *instead
        of* the kind and would have hidden `exhausted` outright, and the
        editor's past-run badge."""
        from openstategraph.loader import load_workflow
        from openstategraph.run_journal import EXHAUSTED_KIND

        with pytest.raises(StepBudgetExhausted):
            load_workflow(package).ask("anything", recursion_limit=BUDGET)

        assert _rows(store)[0].kind == EXHAUSTED_KIND
        assert _rows(store)[0].failed is False
        assert read_runs(store, kind="run") == []

    def test_the_streaming_door_writes_it_down(
        self, store: Path, workflows_root: Path
    ) -> None:
        """The door that drives its own stream, and therefore never reaches
        the blocking driver where the other three are caught."""
        from openstategraph.api.main import create_app
        from openstategraph.run_journal import EXHAUSTED_KIND

        client = TestClient(create_app(workflows_root=workflows_root))
        client.post(
            "/api/runs/stream",
            json={
                "workflow": _document(),
                "question": "streamed and overran",
                "recursion_limit": BUDGET,
            },
        )
        rows = _rows(store)
        assert len(rows) == 1, "a streamed overrun left the store empty"
        assert rows[0].kind == EXHAUSTED_KIND


# ----------------------------------------------------- the census


def _package_root() -> Path:
    import openstategraph

    return Path(openstategraph.__file__).parent


#: Where LangGraph's exhaustion may be *named*, and what each one does with it.
#:
#: `compile/nodes/mount.py` is the mount boundary (`organisms-first-class` 60).
#: It was `compile/node_runtime.py` until the mount family moved into its own
#: module (`docs-and-gaps/03`); this list is why that move could not be silent.
#: `run_doors.py` is the blocking driver every door but one goes through.
#: `api/streaming.py` is that one — it drives `astream` itself.
#: `run_journal.py` holds the translation and the row.
#:
#: A fifth module naming it is a fifth surface deciding for itself what the
#: vendor's sentence meant, which is the defect this file exists for — the
#: shape `test_a_runs_diagram_opens_its_mounts.py` uses for `draw_mermaid`.
CATCHERS: frozenset[str] = frozenset(
    {
        "compile/nodes/mount.py",
        "run_doors.py",
        "api/streaming.py",
        "run_journal.py",
    }
)


class TestNoFifthSurfaceDecidesForItself:
    def test_only_the_sanctioned_modules_name_the_vendors_error(self) -> None:
        named: set[str] = set()
        for path in _package_root().rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "GraphRecursionError":
                    named.add(str(path.relative_to(_package_root())))
                elif (
                    isinstance(node, ast.Attribute)
                    and node.attr == "GraphRecursionError"
                ):
                    named.add(str(path.relative_to(_package_root())))
        assert named <= CATCHERS, (
            f"{sorted(named - CATCHERS)} decides for itself what LangGraph's "
            "exhaustion means — the translation is `run_journal.budget_exhausted`"
        )

    def test_the_wording_has_one_home(self) -> None:
        """`step_budget.py` owns the vocabulary — 'supersteps, not iterations'
        is its opening line. A second sentence somewhere else is a second
        chance to say 'max iterations'."""
        from openstategraph.step_budget import step_budget_exhausted_message

        _assert_ours(step_budget_exhausted_message(BUDGET, workflow="anything"))
