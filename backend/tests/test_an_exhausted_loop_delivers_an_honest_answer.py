"""What a workflow delivers when a later attempt is worse than an earlier one.

`one-chinook-honest` 25, from an exported trace: `chinook-assistant` with its
SQL tool detached refused honestly on attempt one, the grader rejected the
refusal, attempts two and three returned `""`, and the run delivered
`answer: ""` under `decisions.grader-sql: "pass"`.

**The traced run is fixed and this file pins it.** Two mechanisms landed
elsewhere and between them they cover it: `answer` is `LATEST_NONEMPTY`, so an
empty attempt cannot overwrite a good one, and `_output` floors a blank run
with `NO_ANSWER_PRODUCED`. The honest refusal reaches `out1` today.

What the diagnosis found is that the *first* of those saved the traced run by
accident of shape. `_grader.run` fell back to `state["answer"]` — a graph-wide
key — so the text it graded was only the agent's own earlier attempt because
that document has one agent. `_agent` already refuses to read that key for
exactly this reason, in a comment naming the hazard: it "in a multi-agent
document may belong to somebody else". Measured, it does: a two-agent chain
whose *second* agent returned nothing had the grader judge, force-pass and
publish the **first** agent's text as the second's answer.

So the fallback is now the grader's own previous outcome — `outputs[node_id]`,
the best candidate *this* grader has actually seen this turn, reset at the turn
boundary with every other per-run channel. It keeps the traced run's fix (an
agent's own attempt one) and drops the borrowing (another node's answer).
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from conftest import RespondingModel

REFUSAL = (
    "I'm still unable to determine the top-earning genre without a way to "
    "query the Chinook database."
)
OTHER = "Rock earns the most revenue: 826.65 in total."
GRADER = lambda content: "You are a grader" in content  # noqa: E731


def _agent_node(node_id: str) -> dict[str, Any]:
    return {"id": node_id, "type": "agent.llm", "data": {}}


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _one_agent(cap: str = "3") -> dict[str, Any]:
    """The traced shape: input -> agent -> grader, revise back to the agent."""
    return {
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            _agent_node("a1"),
            {
                "id": "g1",
                "type": "route.grader",
                "data": {"criteria": "State the SQL you executed.", "maxAttempts": cap},
            },
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            _edge("in1", "text", "a1", "prompt"),
            _edge("a1", "result", "g1", "candidate"),
            _edge("g1", "revise", "a1", "feedback"),
            _edge("g1", "pass", "out1", "result"),
        ],
    }


def _two_agents(cap: str = "2") -> dict[str, Any]:
    """A chain: the graded agent is the *second*, and the first answered well."""
    document = _one_agent(cap)
    document["nodes"].insert(2, _agent_node("a2"))
    document["edges"] = [
        _edge("in1", "text", "a1", "prompt"),
        _edge("a1", "result", "a2", "prompt"),
        _edge("a2", "result", "g1", "candidate"),
        _edge("g1", "revise", "a2", "feedback"),
        _edge("g1", "pass", "out1", "result"),
    ]
    return document


def _run(document: dict[str, Any], answers: list[str], verdicts: list[str]) -> dict[str, Any]:
    """Drives the real compiled graph with a scripted model.

    `answers` are the agent replies in order; `verdicts` the grader's, the last
    repeating. No provider is reached.
    """
    replies = iter(answers)
    judgements = iter(verdicts)
    last_judgement = [verdicts[-1]]
    model = RespondingModel([(GRADER, "")], default="")

    def generate(messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        if GRADER(content):
            last_judgement[0] = next(judgements, last_judgement[0])
            return model._reply(last_judgement[0])
        return model._reply(next(replies, ""))

    object.__setattr__(model, "_generate", generate)
    runtime = NodeRuntime(model=model)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": "Which genre earns the most revenue?", "attempts": 0,
         "decisions": {}, "outputs": {}},
        {"recursion_limit": 80},
    )


FAIL = "FAIL\nThe answer does not include the SQL."


class TestTheTracedRun:
    def test_the_honest_refusal_reaches_the_customer(self) -> None:
        """Attempt one was right; attempts two and three returned nothing."""
        final = _run(_one_agent(), [REFUSAL, "", ""], [FAIL])
        assert final["outputs"]["out1"] == REFUSAL
        assert final["answer"] == REFUSAL

    def test_the_run_still_reports_that_nothing_passed(self) -> None:
        """Delivering the refusal must not dress a forced pass as a real one."""
        final = _run(_one_agent(), [REFUSAL, "", ""], [FAIL])
        assert final["decisions"]["g1"] == "pass"
        assert final["forced"]["g1"]
        assert final["verdicts"]["g1"]["verdict"] == "revise"

    def test_a_run_that_never_said_anything_says_so(self) -> None:
        """No attempt produced text, so there is nothing to keep."""
        final = _run(_one_agent(), ["", "", ""], [FAIL])
        rendered = final["outputs"]["out1"]
        assert rendered != ""
        assert "could not produce an answer after 3 attempts" in rendered
        assert final["answer"] == rendered


class TestTheCandidateIsTheGradersOwn:
    def test_an_empty_agent_is_not_handed_another_nodes_answer(self) -> None:
        """The defect. `a2` produced nothing; `a1`'s answer is not `a2`'s."""
        final = _run(_two_agents(), [OTHER, "", ""], [FAIL])
        rendered = final["outputs"]["out1"]
        assert OTHER not in rendered, (
            "the grader borrowed another node's answer: " + rendered
        )
        assert "could not produce an answer" in rendered

    def test_the_borrowed_text_is_not_credited_to_the_silent_node(self) -> None:
        """`outputs` is what the canvas draws, so it must not claim `a2` spoke."""
        final = _run(_two_agents(), [OTHER, "", ""], [FAIL])
        assert final["outputs"]["a2"] == ""
        assert OTHER not in final["outputs"]["g1"]


class TestABetterAttemptStillWins:
    def test_a_genuine_improvement_replaces_the_first_answer(self) -> None:
        """The inverse: keeping an earlier candidate must not freeze the loop."""
        final = _run(_one_agent(), [REFUSAL, OTHER], [FAIL, "PASS"])
        assert final["outputs"]["out1"] == OTHER
        assert final["answer"] == OTHER
        assert "g1" not in (final.get("forced") or {})

    def test_a_disliked_but_real_answer_is_published_unchanged(self) -> None:
        """At the cap a candidate the grader merely disliked is still the
        answer the workflow produced — our commentary would be worse."""
        final = _run(_one_agent("2"), [REFUSAL, OTHER], [FAIL])
        assert final["outputs"]["out1"] == OTHER
