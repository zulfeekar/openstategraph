"""`launch-readiness/154`: the grader judged a document the reader never gets.

`route.grader` judges `_upstream_text(state, upstream)` — the producing node's
raw text — and `127`'s disclosure is appended afterwards, by
`compile/node_runtime._output`. So a grader whose criterion is *"did the answer
state which sense it used?"* was judging a document that did not yet contain
the sentence the reader would actually see.

Measured on `cpl-mcp`: the run's answer ended with

    You asked for "persian gulf". This data holds no such value, so the answer
    above is for Middle East Gulf (MEG) on
    `cargoflow_latest.load_shipping_region_v2` — a synonym this data declares
    for it.

and the grader never saw that line. On a covered term the disclosure is
unconditional, so a model that happens to be silent costs a full revise lap —
70-90 s on that package — to obtain a sentence the reader was going to get
anyway. Three live runs all passed, so this was never observed; it is reachable
by construction.

## Why it is not "just give the grader the notes"

`take_notes()` **drains**. `_output` calls it once and renders what it gets, so
a grader that took the notes first would empty the rail and **delete the
reader's disclosure** — trading a wasted lap for the defect `127` exists to
close. So the grader *peeks*, and the two consumers are different verbs on one
bucket rather than two readings of one verb.

## And it is context, never candidate

The disclosure is not spliced into the text being judged. It is a generated
**Context** section — the layer of the prompt the machinery owns — so the
answer the workflow publishes is unchanged, the revise feedback carries only
the grader's own sentence, and nothing invites the model to write the paragraph
itself.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from conftest import RespondingModel  # noqa: E402

from openstategraph.abc import tool_notes  # noqa: E402
from openstategraph.abc.tool_notes import (  # noqa: E402
    Substitution,
    peek_notes,
    record_notes,
    take_notes,
)
from openstategraph.compile.node_runtime import NodeRuntime  # noqa: E402
from openstategraph.compile.workflow_compiler import CompiledPlan  # noqa: E402

THREAD = "154-thread"

DOCUMENT: dict[str, Any] = {
    "nodes": [
        {"id": "a1", "type": "agent.llm", "data": {}},
        {
            "id": "g1",
            "type": "route.grader",
            "data": {"criteria": "The answer must say which sense of the term it used.",
                     "maxAttempts": 2},
        },
        {"id": "out1", "type": "output.formatted", "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "a1", "portId": "result"},
            "target": {"nodeId": "g1", "portId": "candidate"},
        }
    ],
}

CANDIDATE = "There are 68 ports."


@pytest.fixture(autouse=True)
def _a_run_to_record_against(monkeypatch: pytest.MonkeyPatch) -> Any:
    take_notes(THREAD)
    monkeypatch.setattr(tool_notes, "_current_thread", lambda: THREAD)
    yield
    take_notes(THREAD)


def _meg() -> Substitution:
    return Substitution(
        user_term="persian gulf",
        axis="load_shipping_region_v2",
        canonical_value="Middle East Gulf (MEG)",
        how_matched="declared_synonym",
    )


def _grade(reply: str = "PASS\nit says which sense it used") -> tuple[dict[str, Any], str]:
    """Run the grader node, and hand back what it decided and what it was told."""
    model = RespondingModel([], default=reply)
    runtime = NodeRuntime(model=model)
    plan = CompiledPlan(
        nodes=["a1", "g1", "out1"],
        edges=[("a1", "g1")],
        conditional={"g1": {"pass": "out1", "revise": "a1"}},
    )
    run = runtime.factory(DOCUMENT)("g1", DOCUMENT["nodes"][1], plan)
    outcome = run({"outputs": {"a1": CANDIDATE}, "question": "ports in the persian gulf",
                   "revisions": {}})
    # `_grader.run` is `async def` (`async-first/14`) and `install_doors` gives
    # it a sync twin; which one a caller gets depends on the door, so this
    # accepts either rather than pinning a detail the ticket is not about.
    update = asyncio.run(outcome) if inspect.isawaitable(outcome) else outcome
    return update, model.calls[0]


def _publish() -> str:
    """What `_output` then hands the reader."""
    runtime = NodeRuntime(model=None)
    document = {
        "nodes": [
            {"id": "g1", "type": "route.grader", "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "g1", "portId": "pass"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }
    plan = CompiledPlan(nodes=["g1", "out1"], edges=[("g1", "out1")], conditional={})
    run = runtime.factory(document)("out1", document["nodes"][1], plan)
    return run({"outputs": {"g1": CANDIDATE}, "answer": "", "question": "q"})["answer"]


class TestTheGraderIsToldWhatTheReaderWillGet:
    def test_the_disclosure_is_in_the_prompt_it_judges_against(self) -> None:
        record_notes((_meg(),))
        _, prompt = _grade()
        assert "Middle East Gulf (MEG)" in prompt
        assert "a synonym this data declares for it" in prompt

    def test_it_is_told_the_answer_need_not_repeat_it(self) -> None:
        """Otherwise the grader is being shown text and left to guess whose it
        is — and the obvious guess is that the candidate already said it."""
        record_notes((_meg(),))
        _, prompt = _grade()
        assert "does not have to repeat it" in prompt

    def test_it_arrives_as_context_and_not_as_the_candidate(self) -> None:
        record_notes((_meg(),))
        update, prompt = _grade()
        head, _, tail = prompt.partition("</context>")
        assert "Middle East Gulf (MEG)" in head
        # The text under judgement is still exactly what the producer wrote.
        assert update["outputs"]["g1"] == CANDIDATE
        assert "Middle East Gulf (MEG)" not in tail

    def test_a_rejection_carries_only_the_graders_own_sentence(self) -> None:
        record_notes((_meg(),))
        update, _ = _grade("FAIL\nname the ports, not just the count")
        assert update["feedback"] == "name the ports, not just the count"
        assert "Middle East Gulf" not in update["feedback"]


class TestTheReadersDisclosureSurvivesBeingRead:
    def test_peeking_does_not_drain_the_rail(self) -> None:
        record_notes((_meg(),))
        assert peek_notes(THREAD)
        assert peek_notes(THREAD)
        assert take_notes(THREAD)

    def test_the_reader_still_gets_it_after_a_grader_has_seen_it(self) -> None:
        """The whole reason this is a peek. A grader that *took* the notes
        would have deleted the reader's disclosure — `127`'s defect, caused by
        the fix for `154`."""
        record_notes((_meg(),))
        _grade()
        assert "This data holds no such value" in _publish()

    def test_every_lap_of_a_revision_loop_still_leaves_it_there(self) -> None:
        record_notes((_meg(),))
        _grade("FAIL\ntry again")
        _grade("FAIL\ntry again")
        _grade()
        assert "This data holds no such value" in _publish()


class TestSilenceIsStillTheDefault:
    def test_a_run_with_nothing_recorded_adds_no_section(self) -> None:
        _, prompt = _grade()
        assert "does not have to repeat it" not in prompt

    def test_a_substitution_that_changed_nothing_adds_no_section(self) -> None:
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
        _, prompt = _grade()
        assert "does not have to repeat it" not in prompt
