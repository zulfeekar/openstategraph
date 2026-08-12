"""A skill emits its skill. It does not emit the user's question.

Reported live: a Skill node wired to the architect, reading *"when the user
asks something, first greet HELLO ZULU then continue"*, had no effect at all.

The cause was one builder doing two jobs. `_input` seeds
``state["question"] or configured`` — correct for the node that *starts* a run,
and catastrophic for one that does not. Every `input.markdown` and
`input.skill` in every document emitted **the question** on its `skill` port,
so no wired skill's text ever reached a model. Measured before the fix:

    input.skill(instructions="…greet HELLO ZULU…")  →  "What is a router?"

Two further consequences, both silent, both fixed by the same split:

* the skill node ran the **turn boundary reset** (`answer`, `attempts`,
  `decisions`, the fan-out channels) a second time, mid-graph;
* it appended its text to `messages` as a `HumanMessage`, recording the user's
  question twice in the conversation.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import CompiledPlan


def _run(node_type: str, data: dict[str, Any], question: str = "What is a router?") -> dict[str, Any]:
    document = {"nodes": [{"id": "n1", "type": node_type, "data": data}], "edges": []}
    plan = CompiledPlan(nodes=["n1"], edges=[], conditional={})
    runner = NodeRuntime(model=None).factory(document)("n1", document["nodes"][0], plan)
    return runner({"question": question, "messages": []})


SKILL = "When the user asks something, first greet HELLO ZULU then continue."


class TestASkillSourceHoldsStill:
    def test_a_skill_emits_its_own_text(self) -> None:
        update = _run("input.skill", {"skillName": "testskill", "instructions": SKILL})
        assert update["outputs"]["n1"] == SKILL

    def test_a_markdown_instruction_emits_its_own_text(self) -> None:
        update = _run("input.markdown", {"instruction": "Always answer in one sentence."})
        assert update["outputs"]["n1"] == "Always answer in one sentence."

    def test_a_picked_file_falls_back_to_its_content(self) -> None:
        # `input.markdown` carries the picked file's body in `content` and the
        # editable override in `instruction`; the override wins when present.
        assert _run("input.markdown", {"content": "from the file"})["outputs"]["n1"] == (
            "from the file"
        )

    def test_the_question_never_becomes_the_skill(self) -> None:
        """The defect itself, stated as the rule it broke."""
        update = _run("input.skill", {"instructions": SKILL}, question="What is a router?")
        assert "What is a router?" not in update["outputs"]["n1"]

    def test_it_does_not_reset_the_turn(self) -> None:
        # The turn boundary belongs to the entry, once. A second reset
        # mid-graph discards decisions and attempts the run is still using.
        update = _run("input.skill", {"instructions": SKILL})
        for owned_by_the_entry in ("answer", "attempts", "decisions", "feedback"):
            assert owned_by_the_entry not in update

    def test_it_does_not_log_a_second_user_message(self) -> None:
        assert "messages" not in _run("input.skill", {"instructions": SKILL})


class TestTheEntryStillCarriesTheRun:
    def test_the_question_wins_over_a_saved_prompt(self) -> None:
        """Unchanged, and the reason `_input` reads the question at all: a
        saved workflow answers *this* run, not the prompt typed when it was
        saved."""
        assert _run("input.text", {"prompt": "saved prompt"})["outputs"]["n1"] == (
            "What is a router?"
        )

    def test_it_falls_back_to_the_saved_prompt_when_no_question_is_asked(self) -> None:
        assert _run("input.text", {"prompt": "saved prompt"}, question="")["outputs"]["n1"] == (
            "saved prompt"
        )

    def test_it_still_owns_the_turn_boundary(self) -> None:
        update = _run("input.text", {"prompt": ""})
        assert "answer" in update and "attempts" in update and "decisions" in update
        assert update["messages"], "the entry records this user turn"
