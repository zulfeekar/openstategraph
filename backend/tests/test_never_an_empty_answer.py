"""A finished run always says something.

From an exported trace of real use (2026-08-11). The agent's SQL tool had been
detached, so the honest answer was a refusal — and the workflow *produced* one
on attempt one:

    agent-sql  → "I'm still unable to determine the top-earning genre
                  without a way to query the Chinook database."
    grader-sql → rejected it
    agent-sql  → ""            (attempt 2)
    agent-sql  → ""            (attempt 3)
    out1       → ""
    answer: ""   decisions: {grader-sql: "pass"}

Two defects in one run, fixed in the two places they belong:

1. **The grader rejected a correct refusal.** Its criteria demanded the SQL be
   shown, and a refusal has no query to show — so the rubric could not tell
   "bad answer" from "honestly declining". That is a *criteria* gap, so the fix
   is a criterion on `BaseGrader.PROMPT.default_rules`, not code: domain-free, and
   inherited by every grader.

2. **The empty result was delivered as a success.** `_output` is where "the
   run's answer" is defined, so it is the only place that can promise the
   answer is never blank — for every route to it, including the ones with no
   grader at all.
"""

from __future__ import annotations

from typing import Any

from openstategraph.abc.grader import BaseGrader
from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import CompiledPlan


def _output_run(upstream_outputs: dict[str, str], answer: str = "") -> dict[str, Any]:
    runtime = NodeRuntime(model=None)
    document = {
        "nodes": [
            {"id": "a1", "type": "agent.llm", "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "a1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }
    plan = CompiledPlan(nodes=["a1", "out1"], edges=[("a1", "out1")], conditional={})
    run = runtime.factory(document)("out1", document["nodes"][1], plan)
    return run({"outputs": dict(upstream_outputs), "answer": answer, "question": "q"})


class TestTheAnswerIsNeverBlank:
    def test_a_run_that_produced_nothing_says_so(self) -> None:
        """The defect itself. `answer: ""` beside a `pass` is two lies at once:
        it claims success, and it claims there was nothing to say."""
        update = _output_run({"a1": ""})
        assert update["answer"].strip(), "a finished run must never answer with nothing"
        assert "without producing an answer" in update["answer"]

    def test_it_does_not_diagnose_what_it_cannot_see(self) -> None:
        """The floor is honest, not clever. This node cannot know *why* a step
        returned nothing, and a confident wrong reason is worse than a plain
        one — so it points at the trace instead of guessing."""
        answer = _output_run({"a1": ""})["answer"]
        assert "trace" in answer.lower()

    def test_a_real_answer_is_passed_through_untouched(self) -> None:
        update = _output_run({"a1": "Rock, with $826.65."})
        assert update["answer"] == "Rock, with $826.65."

    def test_an_answer_already_in_state_still_wins_over_the_floor(self) -> None:
        """The floor is a last resort, not a competitor: a run whose answer
        arrived by some other path must keep it."""
        update = _output_run({}, answer="Rock, with $826.65.")
        assert update["answer"] == "Rock, with $826.65."


class TestAnHonestRefusalIsAPass:
    def test_the_default_criteria_say_a_refusal_is_correct(self) -> None:
        """Criteria, not code — so it needs no new verdict state, no matching
        against "I cannot", and nothing upstream self-reporting a refusal it
        has every incentive to misreport."""
        criteria = BaseGrader.PROMPT.default_rules.lower()
        assert "declines" in criteria
        assert "pass" in criteria

    def test_it_says_why_retrying_a_refusal_is_pointless(self) -> None:
        # Without this, a grader that merely tolerates refusals still spends
        # the whole retry budget discovering the capability is still missing.
        assert "retrying" in BaseGrader.PROMPT.default_rules.lower()

    def test_the_refusal_clause_carries_no_domain_knowledge(self) -> None:
        """The boundary from ticket 15, held: a grader that learns what a
        SELECT is has stopped being generic, and every non-SQL grader would
        inherit a database."""
        criteria = BaseGrader.PROMPT.default_rules.lower()
        for domain_word in ("sql", "select", "query", "database", "table"):
            assert domain_word not in criteria, f"{domain_word!r} leaked into a generic grader"
