"""An agent fed over a conditional edge receives the deciding node's content.

The page-analytics dispatcher found this live: `plan.edges` carries only
static edges, so an `agent.llm` placed after `human.approval` (or a grader's
`pass`) seeded its prompt from `state["question"]` and never saw the approved
candidate — it either fabricated figures or refused. `_subgraph` and
`_output` had already closed this gap; `_agent` had not.

The pin reads the seed the same way `_agent.run` does, via the module's own
helpers, against a real `CompiledPlan` — no model required.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import NodeRuntime, RunState, _upstream_text
from openstategraph.compile.workflow_compiler import CompiledPlan


def _prompt_seed(runtime: NodeRuntime, plan: CompiledPlan, node_id: str, state: RunState) -> str:
    """Mirrors `_agent`'s seed exactly; a drift here should fail loudly."""
    upstream = [src for src, dst in plan.edges if dst == node_id]
    conditional = [
        src
        for src, dests in plan.conditional.items()
        if node_id in dests.values() and runtime._types.get(src) != "route.classifier"
    ]
    return _upstream_text(state, upstream + conditional) or state.get("question", "")


class TestConditionalFeed:
    def test_an_approvals_candidate_reaches_the_downstream_agent(self) -> None:
        plan = CompiledPlan()
        plan.conditional["approve1"] = {"approved": "dispatcher", "rejected": "lead1"}
        state = RunState(question="send the report", outputs={"approve1": "THE APPROVED REPORT"})  # type: ignore[typeddict-item]
        seed = _prompt_seed(NodeRuntime(model=None), plan, "dispatcher", state)
        assert seed == "THE APPROVED REPORT"

    def test_a_graders_pass_feeds_the_downstream_agent_too(self) -> None:
        plan = CompiledPlan()
        plan.conditional["grader1"] = {"pass": "dispatcher", "revise": "lead1"}
        state = RunState(question="q", outputs={"grader1": "GRADED CANDIDATE"})  # type: ignore[typeddict-item]
        assert _prompt_seed(NodeRuntime(model=None), plan, "dispatcher", state) == "GRADED CANDIDATE"

    def test_a_router_fed_agent_still_receives_the_question(self) -> None:
        runtime = NodeRuntime(model=None)
        runtime._types["router1"] = "route.classifier"
        plan = CompiledPlan()
        plan.conditional["router1"] = {"b-general": "dispatcher"}
        state = RunState(question="hello there", outputs={"router1": "rendered block"})  # type: ignore[typeddict-item]
        assert _prompt_seed(runtime, plan, "dispatcher", state) == "hello there"


class TestStaleFeedbackIsIgnored:
    """`feedback` is keep_latest_nonempty, so "" can never clear it — an
    agent must honor it only while its deciding node still says revise."""

    @staticmethod
    def _live(plan: CompiledPlan, node_id: str, state: RunState) -> bool:
        sources = [
            src
            for src, dests in plan.conditional.items()
            if node_id in (dests.get("revise"), dests.get("rejected"))
        ]
        decisions = state.get("decisions") or {}
        return bool(state.get("feedback")) and any(
            decisions.get(src) in ("revise", "rejected") for src in sources
        )

    def test_feedback_is_dead_once_the_grader_passes(self) -> None:
        plan = CompiledPlan()
        plan.conditional["grader1"] = {"pass": "out1", "revise": "agent1"}
        state = RunState(feedback="old rejection", decisions={"grader1": "pass"})  # type: ignore[typeddict-item]
        assert not self._live(plan, "agent1", state)

    def test_feedback_is_live_while_the_grader_still_says_revise(self) -> None:
        plan = CompiledPlan()
        plan.conditional["grader1"] = {"pass": "out1", "revise": "agent1"}
        state = RunState(feedback="fix the numbers", decisions={"grader1": "revise"})  # type: ignore[typeddict-item]
        assert self._live(plan, "agent1", state)

    def test_another_nodes_feedback_never_leaks_to_a_bystander_agent(self) -> None:
        """The dispatcher after approval: grader-report's stale revise text
        must not shadow the approved report it was actually handed."""
        plan = CompiledPlan()
        plan.conditional["grader1"] = {"pass": "approve1", "revise": "lead1"}
        plan.conditional["approve1"] = {"approved": "dispatcher", "rejected": "lead1"}
        state = RunState(  # type: ignore[typeddict-item]
            feedback="grader once said no",
            decisions={"grader1": "pass", "approve1": "approved"},
        )
        assert not self._live(plan, "dispatcher", state)
