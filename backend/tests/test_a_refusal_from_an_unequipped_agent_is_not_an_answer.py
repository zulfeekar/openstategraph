"""`launch-readiness/103`: a grader must not pass a report of its own brokenness.

Asked *"how many vessels departed mongstad last week?"*, the MCP workflow's
agent answered *"I cannot properly answer because this workflow does not have
the MCP tools…"* — correct, and the honest thing to say. `grader1` returned
**pass**, and that sentence was delivered as the answer, with the same shape and
confidence a working run produces. Silent wrongness.

**Why the grader was right by its own rules, which is what makes this a defect
rather than a bug.** `BaseGrader.PROMPT`'s refusal clause says in as many words
that an honest decline is a PASS — added on evidence, after a grader rejected a
correct refusal and the retries destroyed the only good answer in the run. That
clause is not changed here and must not be: retrying a refusal cannot make a
missing capability appear.

**The fact that was missing.** `tool_use[node]["bound"] == []` meant two
different things at once — *"a writer agent has no tools by design"* and
*"tool nodes were wired to this agent on the canvas and not one of them
materialised"*. `used_no_tools` names the first reading explicitly and is
right to. The second is a **compile-time fact the platform already knows**:
`_bind_tools` walks `plan.tool_bindings`, watches an MCP server hand back
nothing, and records `CAPABILITY_FAILED` — and then threw away which nodes it
was talking about. So the run reached a grader with no way to tell a decline
that is an answer from a decline that is a bug report.

It is recorded now, as `unbound` on the node's own `tool_use` row, and read by
`unbound_capability_claim` — a fact function beside `unrun_query_claim`,
answered off the run's own record with **no model call and no string matching
against "I cannot"**. Six prompt-level rules have been declined on this project
and a seventh would have fared no better: nothing upstream can be asked to
self-report a refusal it has every incentive to misreport.

**The narrowness is the safety**, and every conjunct below is pinned:

- a tool that binds fine and an agent that declines anyway is untouched — that
  is the 2026-08-11 case, and it is a PASS;
- an agent with no tool nodes wired is untouched — nothing was declared, so
  nothing failed;
- one capability of two failing costs one capability and nothing else, which is
  the contract `_bind_tools` already advertises.

And the outcome is neither `pass` nor `revise` in substance: the branch is
`pass` because a cycle cannot fix a capability that is not there, and the
**answer slot carries the platform's own sentence** instead of the model's
prose about its own internals.
"""

from __future__ import annotations

import importlib.metadata
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel
from openstategraph.abc import BaseTool, NoArgs, ToolResult
from openstategraph.compile.node_runtime import NodeRuntime, RuntimeServices
from openstategraph.compile.workflow_compiler import (
    CAPABILITY_UNAVAILABLE_ANSWER,
    WorkflowCompiler,
    unbound_capability_claim,
    used_no_tools,
)
from openstategraph.extensions import TOOLS_GROUP, reset_entry_point_cache
from openstategraph.loader import load_workflow

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"

#: The refusal, near enough verbatim from the live 2026-08-25 run.
REFUSAL = (
    "I cannot properly answer because this workflow does not have the MCP "
    "tools needed to locate the shipping lens and run the query."
)


# --------------------------------------------------------------------------
# Two tools from one distribution: one that materialises, one that does not.
# `tool.mcp` is the real shape — its card carries a whole server, and a server
# that is down hands back an empty list and a warning rather than raising — but
# a test must not dial anything, so the behaviour is scripted.
# --------------------------------------------------------------------------


class VanishingTool(BaseTool):
    """Binds to nothing, loudly. What an MCP card does when the server is down."""

    name = "vanishing"
    description = "A capability that was drawn and did not materialise."
    node_type = "tool.vanishing"
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:  # pragma: no cover - never bound
        return ToolResult(content="never")

    def as_langchain_tools(self, warnings: list[str] | None = None) -> list[Any]:
        if warnings is not None:
            warnings.append("the vanishing server did not answer")
        return []


class SolidTool(BaseTool):
    """Binds normally. The control."""

    name = "solid"
    description = "A capability that is really there."
    node_type = "tool.solid"
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="solid")


class _Dist:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeEntryPoint:
    def __init__(self, result: Any) -> None:
        self.name = "one-oh-three"
        self.group = TOOLS_GROUP
        self.dist = _Dist("one-oh-three")
        self._result = result

    def load(self) -> Any:
        return self._result


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> Any:
    entry = FakeEntryPoint([VanishingTool, SolidTool])

    def fake(*, group: str | None = None, **_: Any) -> list[FakeEntryPoint]:
        return [entry] if group in (None, TOOLS_GROUP) else []

    monkeypatch.setattr(importlib.metadata, "entry_points", fake)
    reset_entry_point_cache()
    yield
    reset_entry_point_cache()


# --------------------------------------------------------------------------
# The fact, on its own. No graph, no model.
# --------------------------------------------------------------------------


class TestTheFactFunction:
    """`unbound_capability_claim` — strict in trusting, and every conjunct pinned."""

    def test_a_wired_capability_that_bound_nothing_is_named(self) -> None:
        claim = unbound_capability_claim({"agent1": {"bound": [], "ran": [], "unbound": ["mcp1"]}})
        assert claim is not None
        assert "agent1" in claim
        assert "mcp1" in claim

    def test_an_agent_with_nothing_wired_is_not_accused(self) -> None:
        """A writer agent has no tools by design. `used_no_tools` already says
        so and this must say the same thing, or every prose workflow reports a
        capability failure on every turn."""
        assert unbound_capability_claim({"a": {"bound": [], "ran": []}}) is None

    def test_one_capability_of_two_failing_is_not_a_blocked_run(self) -> None:
        """`_bind_tools` advertises that a capability which cannot materialise
        costs **one capability**. An agent still holding a working tool is an
        agent that can still work."""
        rows = {"agent1": {"bound": ["solid"], "ran": [], "unbound": ["mcp1"]}}
        assert unbound_capability_claim(rows) is None

    def test_a_working_capability_anywhere_clears_the_whole_run(self) -> None:
        """Same shape as `unrun_query_claim`'s "any query anywhere": a document
        whose *other* agent is fully equipped is not a broken run."""
        rows = {
            "writer": {"bound": [], "ran": [], "unbound": ["mcp1"]},
            "analyst": {"bound": ["solid"], "ran": ["solid"]},
        }
        assert unbound_capability_claim(rows) is None

    def test_it_is_tolerant_about_what_it_is_handed(self) -> None:
        assert unbound_capability_claim(None) is None
        assert unbound_capability_claim({"a": "not a row"}) is None

    def test_it_says_retrying_cannot_help(self) -> None:
        """The routing decision, in the sentence itself: this is not `revise`."""
        claim = unbound_capability_claim({"a1": {"bound": [], "unbound": ["m1"]}})
        assert claim is not None and "retry" in claim.lower()


class TestUsedNoToolsIsUnchanged:
    """The neighbouring reading stays exactly as it was — this adds a fact, it
    does not redefine an existing one. `capability_door` offers a developer a
    tool to *build*, and a server that is down is not a tool anyone must build."""

    def test_a_declared_capability_that_failed_still_opens_no_door(self) -> None:
        assert used_no_tools({"a1": {"bound": [], "ran": [], "unbound": ["m1"]}}) is False


# --------------------------------------------------------------------------
# The compile-time half: `_bind_tools` records which drawn capabilities
# resolved to nothing.
# --------------------------------------------------------------------------


def _document(*tool_types: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "data": {}},
        {"id": "agent1", "type": "agent.llm", "data": {"tier": "react"}},
        {"id": "out1", "type": "output.formatted", "data": {}},
    ]
    edges: list[dict[str, Any]] = [
        {"source": {"nodeId": "in1", "portId": "text"},
         "target": {"nodeId": "agent1", "portId": "prompt"}},
        {"source": {"nodeId": "agent1", "portId": "result"},
         "target": {"nodeId": "out1", "portId": "result"}},
    ]
    for index, tool_type in enumerate(tool_types):
        node_id = f"t{index}"
        nodes.append({"id": node_id, "type": tool_type, "data": {}})
        edges.append(
            {"source": {"nodeId": node_id, "portId": "tool"},
             "target": {"nodeId": "agent1", "portId": "tools"}}
        )
    return {"version": 1, "name": "103", "nodes": nodes, "edges": edges}


def _bind(*tool_types: str) -> NodeRuntime:
    document = _document(*tool_types)
    plan = WorkflowCompiler().plan(document)
    registry = {"tool.vanishing": VanishingTool(), "tool.solid": SolidTool()}
    runtime = NodeRuntime(services=RuntimeServices(model=None, tools=registry))  # type: ignore[arg-type]
    runtime._types = {n["id"]: n["type"] for n in document["nodes"]}
    runtime._nodes = {n["id"]: n for n in document["nodes"]}
    runtime._bind_tools("agent1", plan)
    return runtime


class TestBindTimeRecordsWhatDidNotMaterialise:
    def test_the_node_that_bound_nothing_is_named(self) -> None:
        runtime = _bind("tool.vanishing")
        assert runtime._unbound_capabilities == {"agent1": ["t0"]}

    def test_a_healthy_binding_records_nothing(self) -> None:
        """Absent rather than empty, the convention `queried` and `unmet_tools`
        already follow: a node with nothing to report must not look like a node
        reporting nothing."""
        assert _bind("tool.solid")._unbound_capabilities == {}

    def test_a_mixed_agent_names_only_the_one_that_failed(self) -> None:
        runtime = _bind("tool.solid", "tool.vanishing")
        assert runtime._unbound_capabilities == {"agent1": ["t1"]}


# --------------------------------------------------------------------------
# The defect, at the layer a caller stands on.
# --------------------------------------------------------------------------


class _RefusingAgent(RespondingModel):
    """An agent that declines honestly, and a grader that would pass it."""

    def __init__(self) -> None:
        super().__init__(rules=[])
        object.__setattr__(self, "graded", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        context = "\n".join(str(m.content) for m in messages)
        if "You are a grader" in context:
            object.__setattr__(self, "graded", self.graded + 1)
            return self._reply("PASS\nan honest decline is a correct answer")
        return self._reply(REFUSAL)


def _package(tmp_path: Path, *tool_types: str) -> Path:
    """`budget-exhaustion` — one agent, one grader, a revise edge — with the
    drawn capabilities of this test bolted onto its agent."""
    destination = tmp_path / "one-oh-three"
    shutil.copytree(EXAMPLES / "budget-exhaustion", destination)
    payload = json.loads((destination / "workflow.json").read_text())
    document = payload["document"]
    for index, tool_type in enumerate(tool_types):
        node_id = f"t{index}"
        document["nodes"].append(
            {"id": node_id, "type": tool_type, "title": tool_type,
             "data": {}, "position": {"x": 380, "y": 400 + 80 * index}}
        )
        document["edges"].append(
            {"source": {"nodeId": node_id, "portId": "tool"},
             "target": {"nodeId": "draft1", "portId": "tools"}}
        )
    (destination / "workflow.json").write_text(json.dumps(payload))
    return destination


def _run(tmp_path: Path, *tool_types: str) -> Any:
    model = _RefusingAgent()
    workflow = load_workflow(_package(tmp_path, *tool_types), model=model)
    return workflow.ask("How many vessels departed Mongstad last week?"), model


class TestTheRefusalIsNotDeliveredAsTheAnswer:
    """The ticket, reproduced and then closed."""

    @pytest.fixture(scope="function")
    def run(self, tmp_path: Path) -> Any:
        return _run(tmp_path, "tool.vanishing")

    def test_the_model_prose_is_not_the_answer(self, run: Any) -> None:
        """This is the whole defect: before this, `str(result)` was the
        refusal, and every surface presented it as the answer."""
        result, _ = run
        assert REFUSAL not in str(result)

    def test_the_platform_says_the_workflow_could_not_run(self, run: Any) -> None:
        result, _ = run
        assert CAPABILITY_UNAVAILABLE_ANSWER in str(result)

    def test_no_grading_model_was_asked(self, run: Any) -> None:
        """A fact needs no judgement. The deterministic prelude is the point:
        the run pays for nothing it does not need, and a model cannot be talked
        out of a fact."""
        _, model = run
        assert model.graded == 0

    def test_it_is_not_routed_to_revise(self, run: Any) -> None:
        """A retry with the same missing capability produces the same refusal
        and burns the budget. The ticket says so; the branch obeys it."""
        result, _ = run
        assert result.decisions.get("grader1") == "pass"

    def test_the_developer_channel_names_the_capability(self, run: Any) -> None:
        """A customer is told the workflow could not run; whoever can fix it is
        told which capability did not materialise. Two audiences, one fact."""
        assert any("vanishing" in line for line in (run[0].warnings or []))


class TestAnEquippedAgentIsUntouched:
    """The control, and it is the load-bearing one. `BaseGrader`'s refusal
    clause exists because rejecting a correct decline destroyed the only good
    answer a run produced. Nothing here may re-open that."""

    @pytest.fixture(scope="function")
    def run(self, tmp_path: Path) -> Any:
        return _run(tmp_path, "tool.solid")

    def test_the_decline_is_still_published_as_the_answer(self, run: Any) -> None:
        result, _ = run
        assert REFUSAL in str(result)
        assert CAPABILITY_UNAVAILABLE_ANSWER not in str(result)

    def test_the_grader_was_asked_for_a_judgement(self, run: Any) -> None:
        _, model = run
        assert model.graded >= 1


class TestAnAgentWithNoToolsAtAllIsUntouched:
    """A workflow that wires no capability declares none, so none can fail."""

    @pytest.fixture(scope="function")
    def run(self, tmp_path: Path) -> Any:
        return _run(tmp_path)

    def test_the_answer_is_what_the_workflow_produced(self, run: Any) -> None:
        result, _ = run
        assert REFUSAL in str(result)
        assert CAPABILITY_UNAVAILABLE_ANSWER not in str(result)
