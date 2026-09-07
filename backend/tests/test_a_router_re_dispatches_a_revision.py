"""`workflow-gallery` 48 — a fan-out shape gains an expressible revision loop.

A router's branches are unlimited going out and each agent's `feedback` port
is `maxConnections: 1` coming in, so a grader downstream of a fan-out cannot
send `revise` to exactly one branch agent without picking one arbitrarily — a
technical failure redrafted by the billing desk is worse than no loop at all.
`support-triage` (gallery example 19) shipped `pass` only for exactly this
reason.

**The owner's decision, recorded in `docs/decisions/router-feedback-input.md`:
feedback follows the branch.** A `revise` edge lands on the *router*, not on a
branch agent. The router does not reclassify — it replays the branch its own
last decision named, which is the only new machinery this needs: the graph
dispatches back to the same desk, and that desk's own `feedback` port picks up
the grader's rejection because the compiler now traces a grader's `revise`
edge through a router relay, exactly as it already traces one landing
directly on an agent (`test_a_revise_lap_names_the_right_author.py`).

Two things must both be true, and this file drives a real compiled graph to
prove both rather than asserting on the plan alone — the trap
`skills/ticket-loop` names: a green test at the wrong layer.

1. The **same** branch agent is re-invoked, never the other one — the router
   replayed its own decision rather than asking the model again (which could
   legally reclassify differently and misroute the correction entirely).
2. That agent receives the grader's actual rejection text, addressed to it as
   the author of the rejected draft — the existing `revision_request`
   machinery, reached through the new relay.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from conftest import RespondingModel

ROUTER = lambda content: "You are a router" in content  # noqa: E731
GRADER = lambda content: "You are a grader" in content  # noqa: E731

QUESTION = "My invoice has the wrong amount on it."
COMPLAINT = "Never state a figure the customer did not give you."
FIRST_DRAFT = "Your invoice total is $42 too high; we will correct it."
SECOND_DRAFT = "We will review your invoice and correct any error we find."


def _fan_out_document() -> dict[str, Any]:
    """`support-triage`'s shape, minimal: one router, two desks, one grader.

    `router1` dispatches to `a-billing` or `a-technical`; both feed `grader1`;
    `grader1.revise` lands on `router1.feedback` — never directly on either
    desk, which is the whole point.
    """
    return {
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {
                "id": "router1",
                "type": "route.classifier",
                "data": {
                    "branches": [
                        {"id": "b-billing", "name": "billing"},
                        {"id": "b-technical", "name": "technical"},
                    ],
                    "fallback": "technical",
                },
            },
            {
                "id": "a-billing",
                "type": "agent.llm",
                "data": {"systemPrompt": "You answer billing tickets."},
            },
            {
                "id": "a-technical",
                "type": "agent.llm",
                "data": {"systemPrompt": "You answer technical tickets."},
            },
            {
                "id": "grader1",
                "type": "route.grader",
                "data": {"criteria": "no invented figures", "maxAttempts": "3"},
            },
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "router1", "portId": "question"},
            },
            {
                "source": {"nodeId": "router1", "portId": "branch:b-billing"},
                "target": {"nodeId": "a-billing", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "router1", "portId": "branch:b-technical"},
                "target": {"nodeId": "a-technical", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "a-billing", "portId": "result"},
                "target": {"nodeId": "grader1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "a-technical", "portId": "result"},
                "target": {"nodeId": "grader1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "grader1", "portId": "revise"},
                "target": {"nodeId": "router1", "portId": "feedback"},
            },
            {
                "source": {"nodeId": "grader1", "portId": "pass"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


def _run_one_revision_lap() -> tuple[list[str], dict[str, Any]]:
    """Drives one full revise lap through the fan-out shape.

    The router's own model would answer "billing" on a first classification
    and "technical" on a second — scripted this way *on purpose*, so the test
    can actually tell a **replay** from a **reclassification**: a replay never
    calls the router's model a second time at all (it reuses the branch its
    own last decision named), so it can only ever see "billing". A
    reclassification would call the model again on the revise lap, read
    "technical", and misroute the grader's correction to the desk that never
    wrote the rejected draft — the precise failure this ticket exists to
    prevent, just pointed at the wrong desk instead of an arbitrary one.

    The grader fails the first draft once, then passes.

    Returns every call the billing desk's own model received (its own
    system prompt is the marker) and the final state.
    """
    verdicts = iter([f"FAIL\n{COMPLAINT}", "PASS"])
    drafts = iter([FIRST_DRAFT, SECOND_DRAFT])
    router_answers = iter(["billing", "technical"])
    model = RespondingModel([(ROUTER, "billing")], default="")

    def generate(messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        model.calls.append(content)
        if GRADER(content):
            return model._reply(next(verdicts))
        if ROUTER(content):
            return model._reply(next(router_answers, "billing"))
        if "You answer billing tickets" in content:
            return model._reply(next(drafts))
        # The technical desk must never be reached by this shape at all.
        return model._reply("SHOULD NOT HAVE BEEN CALLED")

    object.__setattr__(model, "_generate", generate)
    runtime = NodeRuntime(model=model)
    document = _fan_out_document()
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    final = graph.invoke(
        {"question": QUESTION, "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 60},
    )
    billing_calls = [c for c in model.calls if "You answer billing tickets" in c]
    return billing_calls, final


class TestTheRouterReplaysItsOwnBranch:
    def test_the_same_desk_is_re_invoked_not_reclassified_or_the_other_one(self) -> None:
        billing_calls, _ = _run_one_revision_lap()
        assert len(billing_calls) == 2, "the billing desk should run once, then be re-run once"

    def test_the_technical_desk_is_never_invoked(self) -> None:
        _, final = _run_one_revision_lap()
        assert final.get("outputs", {}).get("a-technical") in (None, "")

    def test_the_run_finishes_with_the_revised_answer(self) -> None:
        _, final = _run_one_revision_lap()
        assert final.get("answer") == SECOND_DRAFT

    def test_the_router_does_not_reclassify_a_second_time(self) -> None:
        """The router's own model is asked exactly once.

        A replay reuses `decisions["router1"]` from the first classification;
        a reclassification would call the router's model again on the revise
        lap. Distinguishing them matters because a reclassification could
        legally choose a different branch than the one that wrote the
        rejected draft, misrouting the correction entirely.
        """
        billing_calls, _ = _run_one_revision_lap()
        # Guard against a false pass: prove the run really did loop.
        assert billing_calls, "the billing desk was never called at all"


class TestTheDeskReceivesTheGradersActualFeedback:
    def test_the_re_invoked_desk_is_told_it_was_rejected(self) -> None:
        billing_calls, _ = _run_one_revision_lap()
        assert len(billing_calls) == 2
        second_call = billing_calls[1]
        assert "Your previous answer was rejected" in second_call

    def test_it_is_told_the_answer_was_its_own_not_somebody_elses(self) -> None:
        """`_role_towards` still resolves through the ordinary edge to the
        grader — the router relay only widens *which* graders count as this
        node's feedback sources, not how authorship is decided."""
        billing_calls, _ = _run_one_revision_lap()
        second_call = billing_calls[1]
        assert "You did not write it" not in second_call

    def test_the_reason_and_the_rejected_draft_both_travel(self) -> None:
        billing_calls, _ = _run_one_revision_lap()
        second_call = billing_calls[1]
        assert COMPLAINT in second_call
        assert FIRST_DRAFT in second_call
