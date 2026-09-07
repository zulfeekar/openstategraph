"""Chainlogic pins: an agent a classifier routes to can SEE the branch table.

Ticket 11, found live on `page-analytics` (an example since deleted — the
history is why the seam exists, so it is recorded rather than rewritten). The
conversation branch's whole job
is to tell a user what to ask next — so it authors the next question, and the
router has to be able to place that question somewhere that can answer it.
With nothing but a hand-written prompt it offered charts and dashboards that
no branch produces, and phrased a data ask ("Show trends: monthly sales,
media-type mix, top genres") in wording the router classified as
`full_report`: the one branch that ends at a human approval gate and an email
instead of an answer. Fifty-three seconds later the user had no answer.

The branch table is a fact about the *graph*, not knowledge a prompt author
holds, so it rides as generated context — same seam as `advisor_context`.
"""

from __future__ import annotations

import json
from pathlib import Path

from openstategraph.compile.node_runtime import NodeRuntime, branch_context
from openstategraph.compile.workflow_compiler import WorkflowCompiler

ROOT = Path(__file__).resolve().parents[2]


def _routed_document() -> dict:
    return {
        "version": 2,
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {
                "id": "r1",
                "type": "route.classifier",
                "data": {
                    "branches": [
                        {"id": "b-data", "name": "quick_metric"},
                        {"id": "b-chat", "name": "conversation"},
                    ],
                    "fallback": "conversation",
                    "rules": "quick_metric: asks for one number. conversation: everything else.",
                },
            },
            {"id": "a-data", "type": "agent.llm", "data": {"systemPrompt": "answer it"}},
            {"id": "a-chat", "type": "agent.llm", "data": {"systemPrompt": "chat"}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"},
             "target": {"nodeId": "r1", "portId": "question"}},
            {"source": {"nodeId": "r1", "portId": "branch:b-data"},
             "target": {"nodeId": "a-data", "portId": "prompt"}},
            {"source": {"nodeId": "r1", "portId": "branch:b-chat"},
             "target": {"nodeId": "a-chat", "portId": "prompt"}},
            {"source": {"nodeId": "a-data", "portId": "result"},
             "target": {"nodeId": "out1", "portId": "result"}},
            {"source": {"nodeId": "a-chat", "portId": "result"},
             "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


def _nodes(document: dict) -> dict:
    return {n["id"]: n for n in document["nodes"]}


class TestBranchContext:
    def test_a_routed_agent_is_told_every_branch_that_exists(self) -> None:
        document = _routed_document()
        plan = WorkflowCompiler().plan(document)
        text = branch_context("a-chat", plan, _nodes(document))
        assert "quick_metric" in text
        assert "conversation" in text

    def test_it_names_which_branch_the_agent_itself_is(self) -> None:
        document = _routed_document()
        plan = WorkflowCompiler().plan(document)
        assert "You are the 'conversation' branch." in branch_context(
            "a-chat", plan, _nodes(document)
        )
        assert "You are the 'quick_metric' branch." in branch_context(
            "a-data", plan, _nodes(document)
        )

    def test_the_classifier_rules_ride_verbatim(self) -> None:
        """Not re-rendered per branch: the router reads this same string, and
        two renderings of one rule set are two things that can disagree."""
        document = _routed_document()
        plan = WorkflowCompiler().plan(document)
        rules = document["nodes"][1]["data"]["rules"]
        assert rules in branch_context("a-chat", plan, _nodes(document))

    def test_it_forbids_offering_what_no_branch_provides(self) -> None:
        document = _routed_document()
        plan = WorkflowCompiler().plan(document)
        text = branch_context("a-chat", plan, _nodes(document))
        assert "never offer a capability no branch above provides" in text

    def test_it_forbids_reciting_the_branch_table_to_the_person_asking(self) -> None:
        """Ticket 23, live on `chinook-assistant` with `audience: "customer"`.

        Two questions that invited a fabrication were correctly declined — and
        then read the routing vocabulary aloud: *"I can help with greetings,
        general-knowledge facts, or off-topic questions"*, and *"let you know
        the types of requests I can't handle"*. Offering to help with
        "off-topic questions" means nothing to a customer.

        The names are handed over by this block, so this block is what has to
        say what they are for. It cannot be a per-workflow prompt sentence:
        every conversational node a classifier routes to inherits the same
        exposure, and one sentence repeated in N documents is N sentences that
        can disagree.
        """
        document = _routed_document()
        plan = WorkflowCompiler().plan(document)
        text = branch_context("a-chat", plan, _nodes(document))

        assert "never name a branch to the user" in text
        # And the positive half — the branch table is not the vocabulary, but
        # it is still what bounds the offer.
        assert "in the user's own words" in text

    def test_it_says_a_refusal_must_give_its_reason(self) -> None:
        """The same run's data branch was specific — *"the Chinook database
        does not contain a Discount column"* — and that is the bar. Without a
        reason the customer cannot tell "we do not hold that" from "I did not
        understand you"."""
        document = _routed_document()
        plan = WorkflowCompiler().plan(document)
        text = branch_context("a-chat", plan, _nodes(document))

        assert "say what is missing" in text

    def test_an_unrouted_agent_gets_nothing(self) -> None:
        """Most agents are not branch targets; they must not pay for this."""
        document = {
            "version": 2,
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}},
                {"id": "a1", "type": "agent.llm", "data": {}},
                {"id": "out1", "type": "output.formatted", "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"},
                 "target": {"nodeId": "a1", "portId": "prompt"}},
                {"source": {"nodeId": "a1", "portId": "result"},
                 "target": {"nodeId": "out1", "portId": "result"}},
            ],
        }
        plan = WorkflowCompiler().plan(document)
        assert branch_context("a1", plan, _nodes(document)) == ""


class TestItReachesTheRealAgentPrompt:
    """The seam only counts if it survives into what the model is handed."""

    def test_the_conversation_agent_of_the_shipped_example_sees_its_branches(self) -> None:
        """Was pinned on `page-analytics`; that example was deleted for the
        one-example ticket and `chinook-assistant` is now the shipped router.
        Its Front Desk is the branch that has to tell a user what to ask next,
        so it is exactly the node this seam exists for."""
        document = json.loads(
            (ROOT / "workflows" / "chinook-assistant" / "workflow.json").read_text()
        )["document"]
        plan = WorkflowCompiler().plan(document)
        text = branch_context("agent-chat", plan, {n["id"]: n for n in document["nodes"]})
        for branch in ("data_query", "greeting", "off_topic",
                       "general_knowledge", "web_lookup"):
            assert branch in text, f"{branch} missing from the conversation agent's context"

    def test_it_is_composed_as_context_not_appended_to_the_rules(self) -> None:
        """CLAUDE.md's prompt rule: generated context rides above the
        developer's rules and the output contract still renders last. A model
        of `None` short-circuits `_agent` before any provider call, so this
        asserts the composition without needing one — the assertion is that
        `branch_context` is joined into the same `context` argument the skills
        text and the advisor block already use."""
        import inspect

        source = inspect.getsource(NodeRuntime._agent)
        context_arg = source.split("context=", 1)[1].split("middleware=", 1)[0]
        assert "branch_context(" in context_arg, (
            "branch_context must be part of the `context=` composition, never "
            "concatenated into `rules=` — see audit 2026-08 item 4"
        )
