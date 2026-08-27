"""`launch-readiness/127`: the run discloses the substitution, not the model.

The Persian Gulf case, in one paragraph. A user asked for *"the ports which
are in the persian gulf"*. No region axis in that warehouse holds the string
"Persian Gulf"; the canonical value is `Middle East Gulf (MEG)`. One run
returned 67 of 68 correct ports and another refused with an invented country
set, and at the moment each was produced a reader could not tell them apart.

The owner's question — *"how did you get that answer if 'persian' was not
there?"* — is answered by `how_matched`, and the reason it is answered by the
**run** rather than by the model is this file: `_output` renders the
disclosure off what the run recorded, so a model that never mentions the
substitution cannot suppress it.
"""

from __future__ import annotations

from typing import Any

import pytest

from openstategraph.abc import tool_notes
from openstategraph.abc.tool_notes import Substitution, record_notes, take_notes
from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import CompiledPlan

THREAD = "127-thread"


@pytest.fixture(autouse=True)
def _a_run_to_record_against(monkeypatch: pytest.MonkeyPatch) -> None:
    take_notes(THREAD)
    monkeypatch.setattr(tool_notes, "_current_thread", lambda: THREAD)
    yield
    take_notes(THREAD)


def _output_run(answer: str) -> dict[str, Any]:
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
    return run({"outputs": {"a1": answer}, "answer": "", "question": "q"})


def _meg(how_matched: str = "declared_synonym") -> Substitution:
    return Substitution(
        user_term="persian gulf",
        axis="load_shipping_region_v2",
        canonical_value="Middle East Gulf (MEG)",
        how_matched=how_matched,  # type: ignore[arg-type]
    )


class TestTheRunDisclosesIt:
    def test_an_answer_built_on_a_substituted_word_says_so(self) -> None:
        record_notes((_meg(),))
        update = _output_run("There are 68 ports.")
        assert "There are 68 ports." in update["answer"]
        assert "persian gulf" in update["answer"]
        assert "Middle East Gulf (MEG)" in update["answer"]

    def test_a_model_that_never_mentions_it_cannot_suppress_it(self) -> None:
        """The whole reason this is not a prompt. The agent's own text says
        nothing about a substitution; the disclosure is there regardless."""
        record_notes((_meg(),))
        update = _output_run("Sohar, Salalah, Duqm and 65 others.")
        assert "no such value" in update["answer"]

    def test_a_model_inferred_substitution_is_labelled_as_one(self) -> None:
        """`127`'s hardest clause. If parametric knowledge bridged the word,
        the correct answer and the invented one came from the same mechanism —
        so a reader has to be told which."""
        record_notes((_meg("model_inference"),))
        answer = _output_run("There are 68 ports.")["answer"]
        assert "worked out for itself" in answer
        assert "Check it before relying on the answer" in answer

    def test_the_disclosure_reaches_the_card_and_the_chat_alike(self) -> None:
        """`_output` publishes `answer` and `outputs[node]` from one value on
        purpose — a disclosure on one surface and not the other is the
        blank-card defect this node already carries a comment about."""
        record_notes((_meg(),))
        update = _output_run("There are 68 ports.")
        assert update["outputs"]["out1"] == update["answer"]

    def test_it_enters_the_conversation_record(self) -> None:
        record_notes((_meg(),))
        update = _output_run("There are 68 ports.")
        assert "Middle East Gulf (MEG)" in update["messages"][0].content


class TestSilenceIsTheDefault:
    def test_a_run_that_substituted_nothing_says_nothing(self) -> None:
        """A disclosure on every answer trains a reader to skip disclosures."""
        update = _output_run("There are 68 ports.")
        assert update["answer"] == "There are 68 ports."

    def test_a_value_the_user_typed_exactly_is_not_a_substitution(self) -> None:
        record_notes(
            (
                Substitution(
                    user_term="Middle East Gulf (MEG)",
                    axis="load_shipping_region_v2",
                    canonical_value="Middle East Gulf (MEG)",
                    how_matched="exact",
                ),
            )
        )
        update = _output_run("There are 68 ports.")
        assert update["answer"] == "There are 68 ports."

    def test_the_same_substitution_twice_is_disclosed_once(self) -> None:
        record_notes((_meg(), _meg()))
        answer = _output_run("There are 68 ports.")["answer"]
        assert answer.count("persian gulf") == 1

    def test_a_second_output_does_not_repeat_it(self) -> None:
        """Taken, not read: a mount's output node and its parent's must not
        each hand the reader the same paragraph."""
        record_notes((_meg(),))
        first = _output_run("There are 68 ports.")["answer"]
        second = _output_run("There are 68 ports.")["answer"]
        assert "persian gulf" in first
        assert second == "There are 68 ports."
