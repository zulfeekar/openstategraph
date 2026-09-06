"""The Guardrail node: a real state-transforming step with a visible refusal.

Guardrails ticket 01, and the code half of tickets 02 and 03.

Three properties are asserted here that nothing else in the suite can:

1. **A blocked message takes a wire.** The map's "done when" is that a
   developer can *see* a refusal travel back to the user, so the node is
   conditional (`allowed` / `blocked`) and the compiler dispatches on it —
   the same node-decides / edge-dispatches split the router, the grader and
   the approval already use.

2. **Position is the scope, mechanically.** The same builder, the same class,
   the same rules: an instance placed after Input and an instance placed
   before Output differ only in the table they carry. What makes the outbound
   one behave differently is not a flag — it is that by the time it runs there
   is a settled `answer` and a populated `outputs` map for it to act on.

3. **A redaction covers every wire-visible surface, not just the prose.**
   `outputs` rides the `done` frame to *both* audiences (`api/audience.py`'s
   own table says so), so an outbound guard that scrubbed only its own text
   would hand the customer a clean answer beside 59 real email addresses in
   the payload next to it. That is the defect this file's
   `TestTheScrubReachesEverySettledSurface` exists for.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

EMAIL = "carla.almeida@example.com"
CARD = "5105-1051-0510-5100"

GUARD = "guard.policy"


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


def guarded_document() -> dict[str, Any]:
    """in -> guard-in -[allowed]-> agent -> guard-out -[allowed]-> out
                       -[blocked]-> refusal-out
    """
    return {
        "version": 1,
        "name": "guarded",
        "nodes": [
            node("in1", "input.text"),
            node(
                "guard-in",
                GUARD,
                policy=[
                    {"entity": "email", "strategy": "pass"},
                    {"entity": "credit_card", "strategy": "block"},
                ],
            ),
            node("agent1", "agent.llm"),
            node("guard-out", GUARD, policy=[{"entity": "email", "strategy": "redact"}]),
            node("out1", "output.formatted"),
            node("refusal", "output.formatted"),
        ],
        "edges": [
            edge("in1", "text", "guard-in", "content"),
            edge("guard-in", "allowed", "agent1", "prompt"),
            edge("guard-in", "blocked", "refusal", "result"),
            edge("agent1", "result", "guard-out", "content"),
            edge("guard-out", "allowed", "out1", "result"),
        ],
    }


def build(document: dict[str, Any], answer: str = "ok") -> Any:
    runtime = NodeRuntime(model=_fake_model(answer))
    return WorkflowCompiler().build(document, RunState, runtime.factory(document))


def _fake_model(answer: str) -> Any:
    from itertools import repeat

    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    return GenericFakeChatModel(messages=repeat(answer))


class TestCompilerDispatch:
    def test_declares_one_conditional_edge_per_outcome(self) -> None:
        plan = WorkflowCompiler().plan(guarded_document())
        assert plan.conditional["guard-in"] == {"allowed": "agent1", "blocked": "refusal"}

    def test_the_refusal_output_is_not_a_bogus_entry_node(self) -> None:
        # A blocked destination is reached, so it must not be wired from START
        # as though it were a second entry — the same trap the grader's pass
        # edge and the approval's two edges already avoid.
        plan = WorkflowCompiler().plan(guarded_document())
        assert "refusal" not in plan.entry
        assert plan.entry == ["in1"]

    def test_a_guard_with_only_the_allowed_wire_still_plans(self) -> None:
        # The common shape while a graph is being sketched. It must not become
        # an entry-less or exit-less plan.
        plan = WorkflowCompiler().plan(guarded_document())
        assert plan.conditional["guard-out"] == {"allowed": "out1"}
        assert plan.warnings == []


class TestTheEmailLookupCase:
    """The owner's requirement, end to end: one entity, two answers.

    Inbound the machine reads the true address, because that is what makes
    the lookup possible at all. Outbound the human sees it redacted. Neither
    instance knows which it is.
    """

    def test_inbound_pass_hands_the_true_value_to_the_machine(self) -> None:
        graph = build(guarded_document())
        final = graph.invoke({"question": f"look up {EMAIL}"})

        assert final["outputs"]["guard-in"] == f"look up {EMAIL}"
        assert final["decisions"]["guard-in"] == "allowed"

    def test_outbound_redact_removes_it_from_what_a_human_reads(self) -> None:
        graph = build(guarded_document(), answer=f"Her address is {EMAIL}.")
        final = graph.invoke({"question": f"look up {EMAIL}"})

        assert EMAIL not in final["answer"]
        assert "[REDACTED_EMAIL]" in final["answer"]

    def test_the_inbound_guard_never_publishes_the_question_as_the_answer(self) -> None:
        # `answer` is `keep_latest_nonempty`, so a guard that wrote to it
        # unconditionally would announce the user's own question as the run's
        # answer on any path where the agent produced nothing. The guard
        # writes `answer` only when it *changed* an answer that already
        # existed — which an inbound instance, by position, never has.
        graph = build(guarded_document(), answer="The answer.")
        final = graph.invoke({"question": f"look up {EMAIL}"})

        assert final["answer"] == "The answer."


class TestABlockedMessageTakesAVisibleWire:
    def test_it_routes_to_the_refusal_output(self) -> None:
        graph = build(guarded_document())
        final = graph.invoke({"question": f"my card is {CARD}"})

        assert final["decisions"]["guard-in"] == "blocked"
        assert "refusal" in final["outputs"]

    def test_the_refusal_reaches_the_user_as_the_run_s_answer(self) -> None:
        graph = build(guarded_document())
        final = graph.invoke({"question": f"my card is {CARD}"})

        assert "credit card number" in final["answer"]
        assert CARD not in final["answer"]

    def test_the_blocked_content_never_reaches_the_agent(self) -> None:
        graph = build(guarded_document())
        final = graph.invoke({"question": f"my card is {CARD}"})

        assert "agent1" not in final["outputs"]
        # And it is not left lying in the input node's echo either. A block
        # reaches further than a redaction on purpose: `redact` means the
        # reader must not see it, `block` means this workflow must not hold
        # it — including in a checkpointed trace that outlives the run.
        assert CARD not in str(final["outputs"])

    def test_an_unwired_blocked_port_still_refuses_rather_than_leaking(self) -> None:
        # `_router_for` falls back to the first declared destination when a
        # decision names a branch nobody wired. That degrades to "the refusal
        # continues down the allowed wire", which is safe — the blocked
        # content is already gone — and it is worth pinning, because the
        # unsafe reading of the same fallback would be to pass the original
        # text on.
        document = guarded_document()
        document["edges"] = [e for e in document["edges"] if e["source"]["portId"] != "blocked"]
        document["nodes"] = [n for n in document["nodes"] if n["id"] != "refusal"]

        final = build(document).invoke({"question": f"my card is {CARD}"})
        assert CARD not in str(final["outputs"])


class TestTheScrubReachesEverySettledSurface:
    """`outputs` rides the `done` frame to a customer, so it is a wire too."""

    def test_it_scrubs_what_an_upstream_node_already_published(self) -> None:
        graph = build(guarded_document(), answer=f"Her address is {EMAIL}.")
        final = graph.invoke({"question": "who is she"})

        # The agent published the true address into `outputs` before the guard
        # ran. Every one of those entries is downstream of the guard on the
        # only wire that matters — the one to the browser.
        assert EMAIL not in str(final["outputs"])
        assert final["outputs"]["agent1"] == "Her address is [REDACTED_EMAIL]."

    def test_an_inbound_guard_scrubbing_nothing_leaves_upstream_alone(self) -> None:
        graph = build(guarded_document())
        final = graph.invoke({"question": f"look up {EMAIL}"})

        # `email -> pass` inbound: the input node's echo is untouched, which
        # is the whole point of the row being there.
        assert final["outputs"]["in1"] == f"look up {EMAIL}"

    def test_the_outbound_guard_leaves_the_user_s_own_question_alone(self) -> None:
        """Found by the live smoke run, not by reasoning.

        The first version scrubbed **every** `outputs` entry, so `guard-out`
        rewrote `outputs["in1"]` — the echo of the question — to
        `What plan is [REDACTED_EMAIL] on…`, in a document whose inbound card
        says `email → pass`. Two things were wrong with that. It protects
        nobody: ticket 02's own asymmetry is that inbound PII is the user's
        own and they typed it. And it destroys the evidence that the machine
        ever received the true address, which is the one thing this whole
        design is about.

        So the scrub covers entries written by nodes that **produced new
        text**. An input echoes, a router forwards, a guard rewrites — none of
        them invent, and none of them is what an outbound policy exists to
        catch. That is the same set the unguarded-exit check uses, and it is
        "position is the scope" holding for the trace as well as the wire.
        """
        graph = build(guarded_document(), answer=f"Her address is {EMAIL}.")
        final = graph.invoke({"question": f"look up {EMAIL}"})

        assert final["outputs"]["in1"] == f"look up {EMAIL}"
        assert final["outputs"]["guard-in"] == f"look up {EMAIL}"
        # …while the thing the agent produced is scrubbed.
        assert EMAIL not in final["outputs"]["agent1"]


class TestWhatARedactionLeavesBehind:
    def test_it_records_counts_and_entities_on_its_own_state_key(self) -> None:
        graph = build(guarded_document(), answer=f"{EMAIL}, b@x.io and c@y.io")
        final = graph.invoke({"question": "who"})

        assert final["redactions"]["guard-out"] == [
            {"entity": "email", "strategy": "redact", "count": 3}
        ]

    def test_it_never_records_a_value(self) -> None:
        graph = build(guarded_document(), answer=f"Her address is {EMAIL}.")
        final = graph.invoke({"question": "who"})

        assert EMAIL not in str(final["redactions"])

    def test_a_block_is_recorded_too(self) -> None:
        graph = build(guarded_document())
        final = graph.invoke({"question": f"my card is {CARD}"})

        assert final["redactions"]["guard-in"] == [
            {"entity": "credit_card", "strategy": "block", "count": 1}
        ]

    def test_a_guard_that_found_nothing_records_nothing(self) -> None:
        graph = build(guarded_document(), answer="Nothing sensitive here.")
        final = graph.invoke({"question": "hello"})

        assert final.get("redactions", {}).get("guard-out") is None


class TestTheStateKeyObeysTheReducerRule:
    def test_two_guards_writing_in_one_superstep_do_not_raise(self) -> None:
        # CLAUDE.md: a key more than one node type can write needs a named
        # reducer, and `answer` proved that a scalar passes every scripted
        # single-writer test right up until a real fan-out. `redactions` is a
        # map merged by name from the day it exists rather than after the
        # first `InvalidUpdateError`.
        from typing import get_type_hints

        from openstategraph.compile.node_runtime import RunState as _RunState
        from openstategraph.compile.reducers import Reducer, reducer_for

        annotation = get_type_hints(_RunState, include_extras=True)["redactions"]
        assert reducer_for(Reducer.MERGE) in annotation.__metadata__

    def test_a_developer_writes_a_custom_detector_as_a_pattern_not_code(self) -> None:
        document = guarded_document()
        for candidate in document["nodes"]:
            if candidate["id"] == "guard-out":
                candidate["data"]["policy"] = [
                    {"entity": "phone", "strategy": "mask", "detector": r"\+\d[\d ]{6,}\d"}
                ]

        final = build(document, answer="call +47 123 45 678").invoke({"question": "how"})
        assert "+47 123 45 678" not in final["answer"]


class TestABadTableIsLoudRatherThanAbsent:
    def test_a_card_claiming_a_protection_it_cannot_deliver_reports_itself(self) -> None:
        # A guardrail that silently does nothing is worse than no guardrail:
        # the drawing says the policy is enforced. The failure arrives as the
        # node's output — `errors.py`'s degrade-loud rule — rather than as an
        # exception that takes the run down.
        document = guarded_document()
        for candidate in document["nodes"]:
            if candidate["id"] == "guard-out":
                candidate["data"]["policy"] = [{"entity": "passport", "strategy": "redact"}]

        final = build(document, answer="anything").invoke({"question": "how"})
        assert "guard-out" in final["answer"] or "passport" in final["answer"]


class TestTheStreamedTextIsNotTheGuardsToReach:
    """The honest limit, pinned so it cannot be forgotten (ticket 02).

    A node cannot redact what left before it ran. `token` frames are streamed
    out of the agent while it is still typing, and the outbound guard runs
    afterwards — so the settled surfaces are covered and the live one is not.
    LangChain draws the same line and answers the second half with
    `PIIMiddleware(apply_to_output=True)`, whose stream transformer sits
    *inside* the agent. That is middleware on the agent base, not a node.
    """

    def test_the_agent_streamed_the_true_value_before_the_guard_ran(self) -> None:
        graph = build(guarded_document(), answer=f"Her address is {EMAIL}.")
        order = [
            name
            for chunk in graph.stream({"question": "who"}, stream_mode="updates")
            for name in chunk
        ]
        assert order.index("agent1") < order.index("guard_out")


def test_the_runtime_state_declares_the_key() -> None:
    assert "redactions" in RunState.__annotations__
