"""The Answer card shows the run's answer — the same one the chat shows.

Reported by a tester driving `?w=concierge` (2026-08-13): "the end node answer
remaining empty while the answer is already produced."

`_output` is the node that *defines* the run's answer: it resolves upstream
text, falls back to `state["answer"]`, and applies the never-blank floor. Then
it published a *different* value as its own output — the raw upstream `text`
— so the two channels disagreed exactly when it mattered:

| how the run arrived                | `answer` (chat)      | `outputs[out1]` (card) |
| ---------------------------------- | -------------------- | ---------------------- |
| upstream wrote a result            | the result           | the result             |
| answer arrived by some other path  | **the answer**       | **""**                 |
| nothing arrived at all             | **the floor**        | **""**                 |

Rows two and three are the bug. The card is fed from `outputs[node]` — the
`update` frame's `output` field (`streaming._run_frames`) — so a viewer read
"Run the workflow to see the result here." beside a chat bubble holding the
answer. Two surfaces, one fact, two stories.

The floor exists so a finished run never says nothing; publishing it to one
channel and not the other reinstates the very silence it was added to end.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import CompiledPlan


def _output_run(upstream_outputs: dict[str, str], answer: str = "") -> dict[str, Any]:
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
    run = NodeRuntime(model=None).factory(document)("out1", document["nodes"][1], plan)
    return run({"outputs": dict(upstream_outputs), "answer": answer, "question": "q"})


class TestTheCardAndTheChatAgree:
    def test_an_answer_that_arrived_by_another_path_reaches_the_card(self) -> None:
        """The mount case: a child's answer can reach state without this
        node's own upstream having written `outputs`."""
        update = _output_run({}, answer="Iron Maiden, with $138.60.")
        assert update["outputs"]["out1"] == "Iron Maiden, with $138.60."
        assert update["outputs"]["out1"] == update["answer"]

    def test_the_floor_is_shown_on_the_card_too(self) -> None:
        """A run that produced nothing says so in both places, or the card
        contradicts the chat about whether anything happened."""
        update = _output_run({"a1": ""})
        assert update["outputs"]["out1"] == update["answer"]
        assert "without producing an answer" in update["outputs"]["out1"]

    def test_an_ordinary_result_is_unchanged(self) -> None:
        update = _output_run({"a1": "Rock, with $826.65."})
        assert update["outputs"]["out1"] == update["answer"] == "Rock, with $826.65."
