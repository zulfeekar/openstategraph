"""`output.static` — the exit that says something nothing produced.

`osg-agent-experience/55`, which is `46`'s other half decided at last. `46`
offered `output.formatted` an optional `text` field and declined it, because
the field has two possible readings and the case that asked for it is served
by neither:

- **fallback** (`text` when nothing arrives) never fires on the branch that
  wants it — an ask-back branch always carries *something*, the user's own
  question, which is exactly the sentence that must not be printed;
- **override** (`text` wins) puts a typed field in a position to silently
  discard a run's answer at the one node where "the run's answer" is defined.

Both readings are defects of the same shape: one node, two semantics, and a
reader cannot see from the canvas which one is in force. So the sentence gets
its own node type instead, and the ambiguity has nowhere to live — an
`output.formatted` prints what reaches it, always; an `output.static` prints
its own text, always.

The inbound port stays **required**, and that is the ticket's cardinality
question answered rather than dodged: the port is not the sentence, it is how
a branch *reaches* this exit. A static output with nothing wired to it is a
node the graph never schedules, so it is not a reply — it is dead text. What
the port does not do is contribute: its value is ignored, which is the whole
difference from the node beside it.

Every test here compiles and runs a real graph with no model anywhere.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.state import NO_ANSWER_PRODUCED
from openstategraph.compile.workflow_compiler import ROUTE_CHECK_TYPE, WorkflowCompiler

STATIC_OUTPUT_TYPE = "output.static"

ASK_BACK = "Which time window should I use? Name a year or a quarter."

BRANCHES = [
    {"id": "b1", "name": "ask_back"},
    {"id": "b2", "name": "answer"},
]


def _document(text: str = ASK_BACK) -> dict:
    """The try-project shape: a computed fork, one arm of which just speaks.

    `in1 -> r1 -> {static output | formatted output}`. No model, no package
    function on the speaking arm — that arm is one node, which is the whole
    point of the ticket: before this it was two, a `function.<name>` returning
    a constant in front of an Output.
    """
    return {
        "version": 2,
        "name": "static-output-test",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "r1",
                "type": ROUTE_CHECK_TYPE,
                "position": {"x": 200, "y": 0},
                "data": {"check": "needs_a_date_range", "branches": BRANCHES},
            },
            {
                "id": "ask",
                "type": STATIC_OUTPUT_TYPE,
                "position": {"x": 400, "y": 0},
                "data": {"text": text},
            },
            {"id": "ans", "type": "output.formatted", "position": {"x": 400, "y": 120}, "data": {}},
            {
                "id": "fell",
                "type": "output.formatted",
                "position": {"x": 400, "y": 240},
                "data": {},
            },
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "r1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "r1", "portId": "branch:b1"},
                "target": {"nodeId": "ask", "portId": "when"},
            },
            {
                "source": {"nodeId": "r1", "portId": "branch:b2"},
                "target": {"nodeId": "ans", "portId": "result"},
            },
            {
                "source": {"nodeId": "r1", "portId": "fallback"},
                "target": {"nodeId": "fell", "portId": "result"},
            },
        ],
    }


def _needs_a_date_range(text: str) -> str:
    lowered = text.lower()
    return "answer" if any(t in lowered for t in ("2024", "2025", "q1")) else "ask_back"


def _run(document: dict, question: str) -> dict:
    runtime = NodeRuntime(functions={"function.needs_a_date_range": _needs_a_date_range})
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": question, "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
    )


class TestItPrintsItsOwnSentence:
    def test_the_ask_back_branch_says_the_authors_words(self) -> None:
        final = _run(_document(), "How much did we export?")

        assert final["decisions"]["r1"] == "b1"
        assert final["answer"] == ASK_BACK
        assert final["outputs"]["ask"] == ASK_BACK

    def test_it_never_prints_what_arrived(self) -> None:
        """The defect the fallback reading could not have fixed."""
        question = "How much did we export?"
        final = _run(_document(), question)
        assert question not in final["answer"]

    def test_the_other_branch_still_publishes_the_runs_answer(self) -> None:
        """And the override reading's defect: nothing of the run is discarded."""
        final = _run(_document(), "How much did we export in 2024?")
        assert final["decisions"]["r1"] == "b2"
        assert "ask" not in final["outputs"]
        assert "ans" in final["outputs"]

    def test_an_empty_sentence_hits_the_same_floor(self) -> None:
        """A blank exit reports itself rather than succeeding silently."""
        final = _run(_document(text="   "), "How much did we export?")
        assert final["answer"] == NO_ANSWER_PRODUCED

    def test_it_records_the_turn_in_the_conversation(self) -> None:
        final = _run(_document(), "How much did we export?")
        assert [m.content for m in final["messages"]][-1] == ASK_BACK

    def test_it_is_an_exit_that_publishes(self) -> None:
        """`published` is what a door reads to know an exit finished."""
        final = _run(_document(), "How much did we export?")
        assert "ask" in final["published"]


class TestTheCatalogueSaysWhatItIs:
    def test_the_node_type_publishes_one_field_and_one_inbound_port(self) -> None:
        from openstategraph.compile.node_catalogue import CATALOGUE

        record = next(node for node in CATALOGUE.nodes if node["type"] == STATIC_OUTPUT_TYPE)
        assert "text" in {field["key"] for field in record["fields"]}
        inbound = [port for port in record["ports"] if port["direction"] == "in"]
        assert [port["id"] for port in inbound] == ["when"]
        assert inbound[0]["required"] is True
        assert [port for port in record["ports"] if port["direction"] == "out"] == []
