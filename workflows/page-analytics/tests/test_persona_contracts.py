"""Persona-sweep pins for the two published flows (ticket 11).

Every assertion here stands for one failure observed in a real API run, and
each one is a fact about the *documents* — the router's rule text, the
conversation agent's rules, the grader's criteria — because that is where the
behaviour was actually wrong. The prompts are the source; the model is not.

Run log that produced these (page-analytics / chinook-nl-to-sql, real runs):

- "Show trends (Monthly sales, media-type mix, top genres)" — the assistant's
  OWN suggested phrasing — classified `full_report`, so 53s of fan-out ended
  at a human-approval gate asking whether to EMAIL a report. No answer ever
  reached the user. The old rule described `full_report` by listing the
  metrics it contains, so any question naming two of them matched.
- The conversation branch offered "charts", "dashboards" and "copy/paste
  reports" that no branch in this workflow produces.
- On chinook-nl-to-sql, "hi there" and "what's the weather in Oslo?" each
  burned all three grader attempts before passing, because the criteria
  demanded a SQL SELECT from every answer including a greeting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _document(slug: str) -> dict:
    return json.loads((ROOT / slug / "workflow.json").read_text())["document"]


def _node(slug: str, node_id: str) -> dict:
    for node in _document(slug)["nodes"]:
        if node["id"] == node_id:
            return node
    raise AssertionError(f"{slug} has no node {node_id!r}")


class TestTheReportBranchIsAboutSendingNotAboutMetrics:
    """The mis-route that produced the owner's "it never ends"."""

    @pytest.fixture()
    def rules(self) -> str:
        return _node("page-analytics", "router1")["data"]["rules"]

    def test_the_rules_say_the_report_branch_does_not_answer_in_the_chat(
        self, rules: str
    ) -> None:
        """`full_report` terminates at `human.approval` + `send_email`. A
        classifier that does not know that will route a "show me" question
        into a branch that structurally cannot answer one."""
        lowered = rules.lower()
        assert "approve" in lowered
        assert "email" in lowered

    def test_naming_several_metrics_is_explicitly_not_the_report_branch(
        self, rules: str
    ) -> None:
        assert "however many" in rules.lower(), (
            "the old rule listed the report's own metrics, so any multi-metric "
            "question matched it — the exclusion has to be explicit"
        )

    def test_show_trends_is_named_on_the_deep_dive_branch(self, rules: str) -> None:
        """The exact wording the assistant suggested and the router then
        mis-classified. It is cheap to name it; it cost 53 seconds not to."""
        deep_dive = rules.split("database_deep_dive:", 1)[1].split("sql_specialist:", 1)[0]
        assert "show trends" in deep_dive.lower()
        assert "media-type mix" in deep_dive.lower()

    def test_a_follow_up_is_ruled_conversation_before_anything_else(
        self, rules: str
    ) -> None:
        """Regression caught in verification, not review: widening the
        deep-dive branch to catch "show trends" also swallowed "how did you
        get that?" — the router classifies against the thread, so a follow-up
        to a trends answer looks like a trends question. Follow-ups therefore
        need a rule that fires BEFORE the topical ones, not one that competes
        with them from the bottom of the list."""
        head = rules.split("Otherwise classify", 1)[0]
        assert "how did you get that" in head.lower()
        assert "ALWAYS conversation" in head

    def test_the_deep_dive_branch_still_reaches_a_plain_output(self) -> None:
        """The property that makes it the right destination: it ends in an
        answer, with no approval gate in the way."""
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        document = _document("page-analytics")
        plan = WorkflowCompiler().plan(document)
        assert plan.conditional["router1"]["b-deep"] == "team1"
        assert ("team1", "out1") in plan.edges


class TestTheConversationBranchOnlyPromisesWhatExists:
    @pytest.fixture()
    def prompt(self) -> str:
        return _node("page-analytics", "agent-chat")["data"]["systemPrompt"]

    def test_it_defers_to_the_generated_branch_list(self, prompt: str) -> None:
        """It must not carry its own hand-written capability list — that list
        is what drifted from the graph in the first place."""
        assert "branches listed in your context" in prompt

    def test_it_refuses_the_capabilities_it_was_caught_inventing(self, prompt: str) -> None:
        for invented in ("charts", "dashboards", "files"):
            assert invented in prompt, f"{invented!r} was offered live and must be ruled out"

    def test_it_may_not_state_a_figure(self, prompt: str) -> None:
        """It has no tools bound — every figure it utters is recalled."""
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        plan = WorkflowCompiler().plan(_document("page-analytics"))
        assert not plan.tool_bindings.get("agent-chat"), (
            "agent-chat gained a tool; the never-state-a-figure rule needs rewriting"
        )
        assert "Never state, estimate or recall a figure" in prompt

    def test_suggestions_must_be_pasteable_back(self, prompt: str) -> None:
        """The chainlogic rule stated as a prompt obligation: a suggestion the
        user cannot paste back and get answered is a broken promise."""
        assert "paste back verbatim" in prompt


class TestChinookAnswersNonDatabaseMessagesWithoutFlailing:
    def test_the_agent_is_told_not_to_query_for_a_greeting(self) -> None:
        prompt = _node("chinook-nl-to-sql", "agent-sql")["data"]["systemPrompt"]
        assert "call NO tools" in prompt
        assert "greeting" in prompt.lower()

    def test_the_grader_does_not_demand_sql_from_a_non_database_answer(self) -> None:
        """Observed: "hi there" and the Oslo weather question each spent all
        three attempts being rejected for containing no SELECT, then passed
        only because the budget ran out. The budget is the safety net, not the
        mechanism."""
        criteria = _node("chinook-nl-to-sql", "grader-sql")["data"]["criteria"]
        assert "First decide whether the QUESTION is a database question" in criteria
        assert "the absence of a query is correct, not a failure" in criteria

    def test_the_sql_requirements_still_bind_for_real_questions(self) -> None:
        criteria = _node("chinook-nl-to-sql", "grader-sql")["data"]["criteria"]
        tail = criteria.split("If it IS a database question", 1)[1]
        assert "must state the SQL SELECT that was executed" in tail
        assert "never from general knowledge" in tail

    def test_the_criteria_still_replace_the_defaults(self) -> None:
        assert _node("chinook-nl-to-sql", "grader-sql")["data"]["criteriaMode"] == "replace"


class TestBothFlowsStillCompileClean:
    @pytest.mark.parametrize("slug", ["page-analytics", "chinook-nl-to-sql"])
    def test_no_warnings(self, slug: str) -> None:
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        assert WorkflowCompiler().plan(_document(slug)).warnings == []

    @pytest.mark.parametrize("slug", ["page-analytics", "chinook-nl-to-sql"])
    def test_still_published(self, slug: str) -> None:
        envelope = json.loads((ROOT / slug / "workflow.json").read_text())
        assert envelope.get("published", True) is True
