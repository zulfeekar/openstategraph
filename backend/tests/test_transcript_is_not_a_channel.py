"""The conversation record carries turns — not scaffolding, not context echo.

Two tickets pointed at one seam (24 and 27): *the transcript echo is
unfiltered, and everything downstream inherits whatever was written to it.*

27, from an exported trace: a developer-audience run's ```suggestion fence was
stored in `messages` and replayed into the router's prompt on the next turn.
Nothing leaked to a customer, so neither audience guard was violated — the
fence simply became conversation, and turn two's context read as a discussion
about a missing tool rather than about music revenue.

24, traced in-process: `router1`'s *output* was the rendered transcript, so
`recover_from_run` could pull a **previous** turn's fenced SQL out of a turn
that ran no SQL at all. A refusal case would then have been graded
`should_have_refused` for a run that never touched the database.

Both are fixed at **write time**, in the two places that write the two
channels, because a read-time filter has to be remembered by every future
reader — which is the condition that produced both tickets:

- `_output` records the **prose** of a turn in `messages`; `answer` keeps the
  fence so the transport can route it to the developer channel.
- `_router` records the **turn** in `outputs`; the rendered conversation is
  what it classifies against, never what it claims to have produced.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, _thread_question
from openstategraph.compile.workflow_compiler import CompiledPlan, WorkflowCompiler
from openstategraph.evaluation.recovery import recover_from_run

FENCE = (
    "```suggestion\n"
    '{"nodeType": "tool.sql-query", "attachTo": "agent-sql", "port": "tools",\n'
    ' "label": "Add SQL query capability", "reason": "A SQL query is needed."}\n'
    "```"
)


def _output_run(text: str) -> dict[str, Any]:
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
    return run({"outputs": {"a1": text}, "answer": "", "question": "q"})


class TestTheDeveloperChannelNeverBecomesConversation:
    def test_the_recorded_turn_carries_the_prose_and_not_the_fence(self) -> None:
        update = _output_run(f"I cannot query the database.\n\n{FENCE}")
        recorded = update["messages"][0].content

        assert "I cannot query the database." in recorded
        assert "```suggestion" not in recorded
        assert "tool.sql-query" not in recorded

    def test_the_answer_still_carries_it_so_the_transport_can_route_it(self) -> None:
        """The split that feeds the developer channel happens at the edge, and
        it must still have something to split. Stripping here as well would
        delete the suggestion instead of moving it."""
        update = _output_run(f"I cannot query the database.\n\n{FENCE}")

        assert "```suggestion" in update["answer"]

    def test_a_fence_only_turn_is_recorded_as_a_sentence_not_as_nothing(self) -> None:
        """A blank assistant turn is worse than no turn: `_thread_question`
        renders `Assistant:` with nothing after it, and the next classification
        reads a conversation in which the assistant said nothing at all."""
        recorded = _output_run(FENCE)["messages"][0].content

        assert recorded.strip()
        assert "```suggestion" not in recorded

    def test_the_next_turn_classifies_against_a_transcript_with_no_fence(self) -> None:
        """The end-to-end shape of the exported trace, replayed: whatever the
        output node recorded is what the router reads next turn."""
        first = _output_run(f"I cannot query the database.\n\n{FENCE}")["messages"][0]
        state = {
            "question": "Which genre earns the most revenue?",
            "messages": [
                SimpleNamespace(type="human", content="Which genre earns the most?"),
                SimpleNamespace(type="ai", content=first.content),
                SimpleNamespace(type="human", content="Which genre earns the most revenue?"),
            ],
        }

        assert "```suggestion" not in _thread_question(state)
        assert "nodeType" not in _thread_question(state)


ROUTED = {
    "version": 2,
    "nodes": [
        {"id": "in1", "type": "input.text", "data": {}},
        {
            "id": "router1",
            "type": "route.classifier",
            "data": {
                "branches": [{"id": "b-data", "name": "data_query"},
                             {"id": "b-chat", "name": "conversation"}],
                "fallback": "conversation",
                "rules": "data_query: asks about the database.",
            },
        },
        {"id": "a1", "type": "agent.llm", "data": {}},
        {"id": "a2", "type": "agent.llm", "data": {}},
    ],
    "edges": [
        {"source": {"nodeId": "in1", "portId": "text"},
         "target": {"nodeId": "router1", "portId": "question"}},
        {"source": {"nodeId": "router1", "portId": "branch:b-data"},
         "target": {"nodeId": "a1", "portId": "prompt"}},
        {"source": {"nodeId": "router1", "portId": "branch:b-chat"},
         "target": {"nodeId": "a2", "portId": "prompt"}},
    ],
}

PREVIOUS_TURN = (
    "Rock earns the most.\n\n```sql\nSELECT g.Name, SUM(il.UnitPrice) FROM Genre g "
    "JOIN Track t ON t.GenreId = g.GenreId JOIN InvoiceLine il ON il.TrackId = "
    "t.TrackId GROUP BY g.Name ORDER BY 2 DESC LIMIT 1;\n```"
)


class _RecordingModel:
    """Answers with a branch name and keeps what it was asked to classify."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.questions: list[str] = []

    def invoke(self, messages: list[Any]) -> Any:
        self.questions.append(str(messages[-1].content))
        return SimpleNamespace(content=self.answer)


def _router_run(model: Any, state: dict[str, Any]) -> dict[str, Any]:
    runtime = NodeRuntime(model=model)
    plan = WorkflowCompiler().plan(ROUTED)
    node = next(n for n in ROUTED["nodes"] if n["id"] == "router1")  # type: ignore[union-attr]
    run = runtime.factory(ROUTED)("router1", node, plan)
    return run(state)


def _conversation() -> dict[str, Any]:
    return {
        "question": "What is the weather in Berlin today?",
        "messages": [
            SimpleNamespace(type="human", content="Which genre earns the most revenue?"),
            SimpleNamespace(type="ai", content=PREVIOUS_TURN),
            SimpleNamespace(type="human", content="What is the weather in Berlin today?"),
        ],
        "outputs": {},
        "decisions": {},
    }


class TestARouterPublishesTheTurnNotTheTranscript:
    def test_it_still_classifies_against_the_whole_conversation(self) -> None:
        """The reason `_thread_question` exists (ticket 11) is untouched: the
        classification is what needs the history."""
        model = _RecordingModel("conversation")
        _router_run(model, _conversation())

        assert model.questions[0].startswith("Conversation so far:")
        assert "Which genre earns the most revenue?" in model.questions[0]

    def test_its_output_is_the_new_message_alone(self) -> None:
        """`outputs[node]` means "what this node produced". A router produces a
        classification; the transcript it read is not its work, and publishing
        it makes every earlier turn look like this turn's evidence."""
        update = _router_run(_RecordingModel("conversation"), _conversation())

        assert update["outputs"]["router1"] == "What is the weather in Berlin today?"

    def test_sql_recovery_cannot_read_a_previous_turns_query(self) -> None:
        """Ticket 24's reproduction. Turn 2 ran no SQL; before the fix the
        recovery found turn 1's query in the router's output and any
        refusal case would have been scored `should_have_refused`."""
        update = _router_run(_RecordingModel("conversation"), _conversation())
        outputs = {k: str(v) for k, v in update["outputs"].items()}

        assert recover_from_run("Berlin is sunny right now.", outputs) == (None, "")

    def test_an_upstream_transform_still_rides_through_untouched(self) -> None:
        """A node that rewrites the question before the router is not a
        context echo, and its text is what the branch must receive."""
        state = _conversation()
        state["outputs"] = {"in1": "Rewritten: which genre earns most?"}
        update = _router_run(_RecordingModel("data_query"), state)

        assert update["outputs"]["router1"] == "Rewritten: which genre earns most?"
