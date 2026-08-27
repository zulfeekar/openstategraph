"""The person at the gate is told what the grader thought (`workflow-gallery` 32).

Grade-then-gate is the natural shape for anything a person signs off, and
`support-triage` is the first gallery example to draw it. The interrupt frame
a client received was `{threadId, node, message, candidate}` — the gate's own
field and the text — while the grader that had just judged that exact text had
written a verdict *and* a reason, and neither reached the reviewer.

**These assertions are on the SSE frame, not on a helper.** The defect lives in
what a client receives, and `FRAME_FIELDS` whitelists what `_stream_run` may
emit — so a fix that put the verdict into state, or into the `interrupt()`
payload alone, and stopped there would leave a helper-level test green and the
reviewer no better informed.

Two decisions this pins:

- **Which grader**, when several are upstream: the candidate's *immediate*
  producer, which is how `_upstream_text` already picks the candidate itself.
  Anything else would caption one text with another text's judgement.
- **The real verdict, not the branch label.** A grader at its attempt cap
  writes `pass` to `decisions` for an answer it rejected. The frame reports
  what the grader *thought* (`revise`), which is the whole reason the reviewer
  is being asked.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from conftest import drive_fold  # noqa: E402

from openstategraph.api.streaming import FRAME_FIELDS, _stream_run
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

from test_human_approval import _fake_model, edge, node

GATE_MESSAGE = "This reply goes to a customer under your name."


def graded_gate_document(*, max_attempts: int = 2) -> dict[str, Any]:
    """in -> draft -[candidate]-> grader -[pass]-> gate; grader -[revise]-> draft"""
    return {
        "version": 1,
        "name": "grade-then-gate",
        "nodes": [
            node("in1", "input.text"),
            node("draft1", "agent.llm"),
            node(
                "grader1",
                "route.grader",
                criteria="No hedging phrases.",
                maxAttempts=max_attempts,
            ),
            node("gate1", "human.approval", message=GATE_MESSAGE),
            node("out1", "output.formatted"),
            node("hold1", "output.formatted"),
        ],
        "edges": [
            edge("in1", "text", "draft1", "prompt"),
            edge("draft1", "result", "grader1", "candidate"),
            edge("grader1", "pass", "gate1", "candidate"),
            edge("grader1", "revise", "draft1", "feedback"),
            edge("gate1", "approved", "out1", "result"),
            edge("gate1", "rejected", "hold1", "result"),
        ],
    }


def ungraded_gate_document() -> dict[str, Any]:
    """in -> draft -> gate. No grader anywhere: the omission case."""
    return {
        "version": 1,
        "name": "gate-only",
        "nodes": [
            node("in1", "input.text"),
            node("draft1", "agent.llm"),
            node("gate1", "human.approval", message=GATE_MESSAGE),
            node("out1", "output.formatted"),
            node("hold1", "output.formatted"),
        ],
        "edges": [
            edge("in1", "text", "draft1", "prompt"),
            edge("draft1", "result", "gate1", "candidate"),
            edge("gate1", "approved", "out1", "result"),
            edge("gate1", "rejected", "hold1", "result"),
        ],
    }


def interrupt_frame(
    document: dict[str, Any], *answers: str, thread_id: str = "t-32", attempts: int = 0
) -> dict[str, Any]:
    """Drive the document to its pause and return the frame a client receives."""
    runtime = NodeRuntime(model=_fake_model(*answers))
    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    graph = compiler.build(
        document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
    )
    names = {safe_name(n): n for n in plan.nodes}
    config = {"configurable": {"thread_id": thread_id}}
    frames = list(
        drive_fold(_stream_run(
            graph,
            {"question": "the invoice is wrong", "attempts": attempts, "decisions": {}, "outputs": {}},
            config,
            plan,
            names,
            runtime,
            thread_id,
        ))
    )
    last = frames[-1]
    assert last.startswith("event: interrupt\n"), last
    return json.loads(last.split("data: ", 1)[1])


class TestTheFrameCarriesTheVerdict:
    def test_a_pass_reaches_the_reviewer_with_its_reason(self) -> None:
        frame = interrupt_frame(
            graded_gate_document(),
            "I will issue a corrected invoice today.",
            "PASS",
            thread_id="t-32-pass",
        )
        assert frame["candidate"] == "I will issue a corrected invoice today."
        assert frame["verdict"] == "pass"
        assert frame["reason"]

    def test_a_forced_pass_reports_what_the_grader_thought_not_the_branch(self) -> None:
        """At the cap the branch is `pass`; the judgement was `revise`.

        `decisions` holds `pass` here because the compiler dispatches on that
        label. A frame built from `decisions` would tell the reviewer the
        machine approved an answer it rejected — gallery ticket 22's hazard,
        arriving at the one surface where a person acts on it.
        """
        frame = interrupt_frame(
            graded_gate_document(max_attempts=1),
            "I'll refund it if appropriate.",
            "FAIL\n'if appropriate' is a hedge and the rubric forbids holding phrases.",
            thread_id="t-32-forced",
            attempts=1,
        )
        assert frame["verdict"] == "revise"
        assert "hedge" in frame["reason"]

    def test_a_gate_with_no_grader_upstream_omits_both_keys(self) -> None:
        frame = interrupt_frame(
            ungraded_gate_document(), "A draft nobody judged.", thread_id="t-32-none"
        )
        assert frame["candidate"] == "A draft nobody judged."
        assert "verdict" not in frame
        assert "reason" not in frame

    def test_the_frame_contract_declares_the_two_new_fields(self) -> None:
        """`FRAME_FIELDS` is what `docs/openapi.json` publishes to a client."""
        assert "verdict" in FRAME_FIELDS["interrupt"]
        assert "reason" in FRAME_FIELDS["interrupt"]


class TestItSurvivesAResume:
    """A gate is by definition a run that pauses and resumes.

    So a verdict that only works on the first segment would be a fix that does
    not work where the feature lives. The shape below puts a gate *before* the
    graded one: the second pause happens inside `/api/runs/resume`'s call, and
    its frame is built by the same fold from the same checkpointed state.
    """

    @staticmethod
    def two_gate_document() -> dict[str, Any]:
        """in -> gate0 -[approved]-> draft -> grader -[pass]-> gate1"""
        return {
            "version": 1,
            "name": "gate-then-grade-then-gate",
            "nodes": [
                node("in1", "input.text"),
                node("gate0", "human.approval", message="Start drafting?"),
                node("draft1", "agent.llm"),
                node("grader1", "route.grader", criteria="No hedging phrases.", maxAttempts=2),
                node("gate1", "human.approval", message=GATE_MESSAGE),
                node("out1", "output.formatted"),
                node("hold0", "output.formatted"),
                node("hold1", "output.formatted"),
            ],
            "edges": [
                edge("in1", "text", "gate0", "candidate"),
                edge("gate0", "approved", "draft1", "prompt"),
                edge("gate0", "rejected", "hold0", "result"),
                edge("draft1", "result", "grader1", "candidate"),
                edge("grader1", "pass", "gate1", "candidate"),
                edge("grader1", "revise", "draft1", "feedback"),
                edge("gate1", "approved", "out1", "result"),
                edge("gate1", "rejected", "hold1", "result"),
            ],
        }

    def test_the_second_pause_of_a_resumed_run_carries_the_verdict(self) -> None:
        from langgraph.types import Command

        document = self.two_gate_document()
        runtime = NodeRuntime(model=_fake_model("A corrected invoice is on its way.", "PASS"))
        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        graph = compiler.build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        names = {safe_name(n): n for n in plan.nodes}
        thread_id = "t-32-resume"
        config = {"configurable": {"thread_id": thread_id}}

        first = list(
            drive_fold(_stream_run(
                graph,
                {"question": "the invoice is wrong", "attempts": 0, "decisions": {}, "outputs": {}},
                config,
                plan,
                names,
                runtime,
                thread_id,
            ))
        )
        opening = json.loads(first[-1].split("data: ", 1)[1])
        assert opening["node"] == "gate0"
        # Nothing has judged anything yet, so there is nothing to report.
        assert "verdict" not in opening

        second = list(
            drive_fold(_stream_run(
                graph,
                Command(resume={"decision": "approve"}),
                config,
                plan,
                names,
                runtime,
                thread_id,
            ))
        )
        paused = json.loads(second[-1].split("data: ", 1)[1])
        assert paused["node"] == "gate1"
        assert paused["verdict"] == "pass"
        assert paused["reason"]


class TestTheCustomerSurfaceShowsIt:
    """`chat.html` is a dependency-free page with no test runner of its own.

    Source assertions, for the reason `test_terminal_frame.py` records: the
    alternative is a browser, and the claim being made here is small — that the
    page reads the two fields the frame now carries and does not draw a line
    when it carries neither.
    """

    @staticmethod
    def _source() -> str:
        from pathlib import Path

        return (
            Path(__file__).resolve().parents[1]
            / "openstategraph"
            / "api"
            / "static"
            / "chat.html"
        ).read_text()

    def test_the_approval_card_reads_the_verdict_and_its_reason(self) -> None:
        source = self._source()
        assert "d.verdict" in source
        assert "d.reason" in source
        assert "hitl__verdict" in source

    def test_it_draws_nothing_when_there_is_no_verdict(self) -> None:
        """Absence is a value: no grader judged it, not "the grader said nothing".

        This used to assert the bytes of the page's own ternary — a shape a
        formatter could move and a rule the page no longer owns. Since
        `production-ready` 94 the sentence has one spelling, generated into the
        page from `src/view/ask/graderVerdictLine.ts`, so the rule is asserted
        where it is written and the drift is gated by
        `test_one_graders_sentence.py`. What is still worth asserting *here* is
        that the page draws the paragraph only when there is a sentence to put
        in it.
        """
        source = self._source()
        assert 'verdictLine ? `<p class="hitl__verdict">' in source

    def test_the_sentence_is_the_one_the_editor_says(self) -> None:
        """One judgement, two doors, one spelling (`production-ready` 94)."""
        source = self._source()
        assert "graderVerdictLine({" in source
        assert "GENERATED-BEGIN graderVerdictLine" in source
