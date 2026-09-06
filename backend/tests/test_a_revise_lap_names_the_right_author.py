"""A revise lap must not tell a node it wrote something it did not write.

`organisms-first-class` 54, graduated out of 37. A grader's `revise` edge may
legally land on a node *upstream* of the agent that produced the candidate —
that is LangChain's agentic-RAG shape, and `b12afbb` pinned that it has always
been legal here. What 37 found on the way is this: `revision_request` is
written for the evaluator-optimizer case, where the receiver **is** the
producer, and it was delivered unchanged to a question-rewriter. Printed off a
live compiled run of `agentic-rag-rewrite`, the rewriter's second lap read:

    'What is the target response time for a Severity-1 incident?'
    'Your previous answer was rejected: The handbook does not carry that figure.

     This is the answer that was rejected, in full. Revise it — do not start
     again from nothing:

     the handbook does not say.'

`rewrite1` never wrote "the handbook does not say" — `retrieve1` did. The
preamble is base-owned and not editable, so the only thing standing between
that instruction and a rewriter emitting an answer was a sentence the package
author wrote in their own Rules: a developer countermanding the machinery from
the one section they control, which is the shape `CLAUDE.md`'s
prompt-composition rule exists to prevent.

The compiler already knows the difference and needs nothing new: the receiver
is the producer exactly when a `plan.edges` pair runs from it into the node
whose `revise`/`rejected` edge caused this lap. So the test drives a real
compiled graph in both shapes and reads the human turn the node actually
received — asserting on the helper alone would stay green if the derivation
were wired to the wrong node.

`organisms-first-class` 55 closed the third arm the same way. The bystander
role was pinned at the plan and the helper only, because a `human.approval`
node compiles to `interrupt()` and its sentence reaches a model solely after a
resume carries a person's refusal back — so the helper-level test stayed green
with the approval's `rejected` edge removed from the feedback sources
altogether, which is the run-time seam it was supposed to be about. The live
case pauses a compiled graph at the gate, resumes with
`Command(resume={"decision": "reject", ...})` and reads the turn the holding
agent received. A person's refusal is not a grader's verdict, and the sentence
it produces says so.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from conftest import RespondingModel

GRADER = lambda content: "You are a grader" in content  # noqa: E731

QUESTION = "What is the target response time for a Severity-1 incident?"
COMPLAINT = "The handbook does not carry that figure."
RETRIEVED = "the handbook does not say."


def _upstream_document() -> dict[str, Any]:
    """`agentic-rag-rewrite`'s shape: revise lands two nodes upstream."""
    return {
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {
                "id": "rewrite1",
                "type": "agent.llm",
                "data": {"systemPrompt": "You reshape a question."},
            },
            {
                "id": "retrieve1",
                "type": "agent.llm",
                "data": {"systemPrompt": "You answer from the handbook."},
            },
            {
                "id": "grader1",
                "type": "route.grader",
                "data": {"criteria": "grounded", "maxAttempts": "3"},
            },
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "rewrite1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "rewrite1", "portId": "result"},
                "target": {"nodeId": "retrieve1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "retrieve1", "portId": "result"},
                "target": {"nodeId": "grader1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "grader1", "portId": "revise"},
                "target": {"nodeId": "rewrite1", "portId": "feedback"},
            },
            {
                "source": {"nodeId": "grader1", "portId": "pass"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


def _producer_document() -> dict[str, Any]:
    """The ordinary evaluator-optimizer: revise lands on the producer."""
    return {
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "a1", "type": "agent.llm", "data": {}},
            {
                "id": "g1",
                "type": "route.grader",
                "data": {"criteria": "grounded", "maxAttempts": "3"},
            },
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "a1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "a1", "portId": "result"},
                "target": {"nodeId": "g1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "g1", "portId": "revise"},
                "target": {"nodeId": "a1", "portId": "feedback"},
            },
            {
                "source": {"nodeId": "g1", "portId": "pass"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


def _one_revise_lap(document: dict[str, Any], answer: str = RETRIEVED) -> list[str]:
    """Run the graph through exactly one rejection, return the retry prompts."""
    verdicts = iter([f"FAIL\n{COMPLAINT}", "PASS"])
    model = RespondingModel([(GRADER, "")], default=answer)
    original = model._generate

    def generate(messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        if GRADER(content):
            model.calls.append(content)
            return model._reply(next(verdicts))
        return original(messages, stop=stop, run_manager=run_manager, **kwargs)

    object.__setattr__(model, "_generate", generate)
    runtime = NodeRuntime(model=model)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    graph.invoke(
        {"question": QUESTION, "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 60},
    )
    return [c for c in model.calls if "was rejected" in c and not GRADER(c)]


class TestAnUpstreamNodeIsNotToldItWroteTheAnswer:
    def test_it_is_never_told_the_rejected_text_is_its_own(self) -> None:
        """The defect, verbatim: 'Revise it' about somebody else's text."""
        prompts = _one_revise_lap(_upstream_document())
        assert prompts, "the rewriter never saw the grader's feedback"
        assert "Your previous answer was rejected" not in prompts[0]
        assert "This is the answer that was rejected, in full. Revise it" not in (
            prompts[0]
        )

    def test_it_is_told_the_answer_came_from_what_it_produced(self) -> None:
        """And what it gets instead has to be actionable, not merely silent."""
        prompts = _one_revise_lap(_upstream_document())
        assert prompts, "the rewriter never saw the grader's feedback"
        assert "You did not write it" in prompts[0]
        assert "change what you produce" in prompts[0].lower()

    def test_the_rejected_text_still_travels(self) -> None:
        """`production-ready` 73's guarantee, which this must not trade away."""
        prompts = _one_revise_lap(_upstream_document())
        assert prompts, "the rewriter never saw the grader's feedback"
        assert RETRIEVED in prompts[0]
        assert COMPLAINT in prompts[0]

    def test_silence_is_still_reported_as_silence(self) -> None:
        """A lap that genuinely produced nothing gets no dressed-up placeholder."""
        prompts = _one_revise_lap(_upstream_document(), answer="")
        assert prompts, "the rewriter never saw the grader's feedback"
        assert "in full" not in prompts[0]
        assert QUESTION not in prompts[0].split("was rejected", 1)[1]


class TestTheEvaluatorOptimizerCaseIsUnchanged:
    def test_the_producer_is_still_told_to_revise_what_it_wrote(self) -> None:
        prompts = _one_revise_lap(_producer_document())
        assert prompts, "the agent never saw the grader's feedback"
        assert "Your previous answer was rejected" in prompts[0]
        assert "This is the answer that was rejected, in full. Revise it" in prompts[0]
        assert RETRIEVED in prompts[0]
        assert "You did not write it" not in prompts[0]


def _bystander_document() -> dict[str, Any]:
    """`support-triage`'s shape: a human approval's `rejected` edge lands on an
    agent that neither wrote the draft nor feeds the gate.

    The third role, and it was found by asking which shipped packages the
    derivation changes rather than by reasoning about it. Telling this node
    "your last output produced the rejected answer" would swap one false
    sentence for another.
    """
    return {
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "draft1", "type": "agent.llm", "data": {}},
            {"id": "gate1", "type": "human.approval", "data": {}},
            {
                "id": "hold1",
                "type": "agent.llm",
                "data": {"systemPrompt": "Write the internal record."},
            },
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "draft1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "draft1", "portId": "result"},
                "target": {"nodeId": "gate1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "gate1", "portId": "approved"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
            {
                "source": {"nodeId": "gate1", "portId": "rejected"},
                "target": {"nodeId": "hold1", "portId": "feedback"},
            },
        ],
    }


DRAFT = "Sorry your order was late; here is a voucher."
REFUSAL = "Do not offer a voucher without a manager's sign-off."


def _one_rejected_approval(draft: str = DRAFT) -> list[str]:
    """Drive the bystander shape *live*: pause at the gate, refuse, resume.

    A `human.approval` node compiles to `interrupt()`, so the bystander
    sentence only reaches a model **after** a resume carries a person's
    refusal back into the graph — which is why 54 pinned this arm at the plan
    and the helper instead, and why that is the "green test at the wrong
    layer" shape this ticket exists to close. `InMemorySaver` is enough: the
    pause and the resume happen in one process, so nothing here is a claim
    about durability (`test_cli_resume.py` makes that one, against sqlite).

    Returns the human turns carrying a rejection that a model actually
    received, in order.
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    model = RespondingModel([], default=draft)
    runtime = NodeRuntime(model=model)
    document = _bystander_document()
    graph = WorkflowCompiler().build(
        document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
    )
    config = {"configurable": {"thread_id": "bystander-1"}}
    paused = graph.invoke(
        {"question": QUESTION, "attempts": 0, "decisions": {}, "outputs": {}},
        config,
    )
    assert "__interrupt__" in paused, "the gate did not pause; nothing was resumed"
    before = len(model.calls)
    graph.invoke(
        Command(resume={"decision": "reject", "feedback": REFUSAL}), config
    )
    return [c for c in model.calls[before:] if "was rejected" in c]


class TestABystanderIsNotBlamedEither:
    """Derived at the compiler, not at the node type: the rule is edge shape."""

    def test_the_holding_agent_is_told_it_neither_wrote_nor_caused_it(self) -> None:
        from openstategraph.compile.context import revision_request
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        plan = WorkflowCompiler().plan(_bystander_document())
        direct = {s for s, dst in plan.edges if dst == "gate1"}
        assert "hold1" not in direct, "hold1 did not write the draft"
        reachable = {s for s, dst in plan.edges if dst in direct} | direct
        assert "hold1" not in reachable, "hold1 does not feed the gate either"

        text = revision_request("The draft.", "Too curt.", role="bystander")
        assert "nothing you produced led to it" in text
        assert "Revise it" not in text
        assert "The draft." in text

    def test_a_live_refusal_at_the_gate_reaches_the_holding_agent_unblamed(
        self,
    ) -> None:
        """The seam 54 left open: the interrupt, the resume, and the turn."""
        prompts = _one_rejected_approval()
        assert prompts, "the holding agent never saw the person's refusal"
        assert "nothing you produced led to it" in prompts[0]
        assert "Revise it" not in prompts[0]
        assert "You did not write it and nothing you produced led to it" in prompts[0]
        assert "Your last output was used further down" not in prompts[0]
        assert "Your previous answer was rejected" not in prompts[0]

    def test_the_refused_draft_and_the_persons_reason_both_travel(self) -> None:
        prompts = _one_rejected_approval()
        assert prompts, "the holding agent never saw the person's refusal"
        assert DRAFT in prompts[0]
        assert REFUSAL in prompts[0]

    def test_a_refusal_that_refused_nothing_visible_stays_silent_about_it(
        self,
    ) -> None:
        prompts = _one_rejected_approval(draft="")
        assert prompts, "the holding agent never saw the person's refusal"
        assert "quoted so you know what it said" not in prompts[0]
        assert REFUSAL in prompts[0]

    def test_a_granted_approval_says_nothing_about_a_rejection(self) -> None:
        """The inverse: approving must not deliver a rejection to anybody."""
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.types import Command

        model = RespondingModel([], default=DRAFT)
        runtime = NodeRuntime(model=model)
        document = _bystander_document()
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        config = {"configurable": {"thread_id": "bystander-approved"}}
        graph.invoke(
            {"question": QUESTION, "attempts": 0, "decisions": {}, "outputs": {}},
            config,
        )
        graph.invoke(Command(resume={"decision": "approve"}), config)

        assert not [c for c in model.calls if "was rejected" in c]
