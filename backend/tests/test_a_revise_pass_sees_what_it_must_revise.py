"""A revise lap hands the agent the answer it is being told to fix.

`production-ready` 73, diagnosed by running `chinook-assistant` against the
cloud model and printing the message list the agent's loop actually received.
The reported symptom was a correct answer published under two banners — a
silent node and a forced pass — and the ticket's own question was *why does a
revise pass write nothing*. The transcript answers it:

    human | 'top artists by revenue'
    human | 'Your previous answer was rejected: The answer is empty.'
    ai    | tool_calls=['chinook_list_tables']
    tool  | '| Table | Rows | ...'
    ...
    ai    | ''                       <- the loop ends, `_final_text` -> ""

Two human turns and nothing else. `_agent` never writes `messages`, so the
conversation state carries only the user's question; the rejected answer is
**not in the payload**. The model is told to revise a text it cannot see, so
it starts the same investigation from the same standing start and rolls the
same die — three attempts are three identical first attempts, and the grader's
complaint never changes between them.

The rejected text was not missing from the run: it is `outputs[<grader>]`,
delivered over the very `revise` edge that caused this lap, and `_agent`
already reads it into `prompt` — then discards it, because the `if feedback`
arm appends the rejection *instead of* the content.

So this pins the payload, not the banners. A warning that stops printing is a
symptom that can go quiet for the wrong reason; a revise lap that can see what
it is revising is the mechanism.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from conftest import RespondingModel

REJECTED = "Rock earns the most revenue: 826.65."
GRADER = lambda content: "You are a grader" in content  # noqa: E731


def _document() -> dict[str, Any]:
    """input -> agent -> grader, `revise` back to the agent's feedback port."""
    return {
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "a1", "type": "agent.llm", "data": {}},
            {
                "id": "g1",
                "type": "route.grader",
                "data": {"criteria": "State the SQL you executed.", "maxAttempts": "3"},
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


def _one_revise_lap(answer: str = REJECTED) -> RespondingModel:
    """Rejects once, then passes. Returns the model, with `.calls` recorded."""
    verdicts = iter(["FAIL\nState the SQL you executed.", "PASS"])
    model = RespondingModel([(GRADER, "")], default=answer)
    original = model._generate

    def generate(messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        if GRADER(content):
            model.calls.append(content)
            return model._reply(next(verdicts))
        return original(messages, stop=stop, run_manager=run_manager, **kwargs)

    object.__setattr__(model, "_generate", generate)

    document = _document()
    runtime = NodeRuntime(model=model)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    graph.invoke(
        {"question": "Which genre earns the most revenue?", "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 60},
    )
    return model


def _retry_prompts(model: RespondingModel) -> list[str]:
    return [c for c in model.calls if "Your previous answer was rejected" in c and not GRADER(c)]


class TestTheReviseLapCarriesTheRejectedAnswer:
    def test_the_reason_still_reaches_the_agent(self) -> None:
        """The half that already worked, kept so a fix cannot trade one for
        the other."""
        prompts = _retry_prompts(_one_revise_lap())
        assert prompts, "the agent never saw the grader's feedback"
        assert "State the SQL you executed." in prompts[0]

    def test_the_rejected_answer_reaches_the_agent_too(self) -> None:
        """The defect. Without this the retry is a repeat, not a revision."""
        prompts = _retry_prompts(_one_revise_lap())
        assert prompts, "the agent never saw the grader's feedback"
        assert REJECTED in prompts[0], (
            "the agent was told to fix an answer it was never shown"
        )


class TestSilenceIsNotDressedUpAsAnAnswer:
    def test_an_empty_previous_attempt_shows_the_agent_no_text(self) -> None:
        """The live repro's own case: the first pass said nothing at all.

        There is no rejected text to carry, and the seed the node would
        otherwise reach for falls back to the user's question — which must
        never be quoted back as *"the answer that was rejected"*.
        """
        prompts = _retry_prompts(_one_revise_lap(answer=""))
        assert prompts, "the agent never saw the grader's feedback"
        assert "the answer that was rejected" not in prompts[0]
        assert "Which genre earns the most revenue?" not in prompts[0].split(
            "Your previous answer was rejected"
        )[1]
