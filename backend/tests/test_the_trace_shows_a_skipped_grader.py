"""A grader that skipped its model call says so on the wire (`production-ready` 92).

`BaseGrader.grade` has two paths. `deterministic_checks` rejects an empty
candidate, or one beginning `Error`/`Traceback`/`Exception`, and returns
**before** `self.model.invoke` is reached — 0.021 ms, measured against a model
that raises if touched. A judged verdict costs 719-2024 ms on a live run.

The trace rendered both identically. Ticket 84 was filed because of exactly
that: three grader rows at `0 ms` had one available reading, "the timer is
broken", and it cost a session plus a live model run to establish that the
timer was right and no model had ever been called. 84 fixed how the *duration*
prints; this is about what the row says *happened*.

**Both paths in one test, deliberately.** A test that only asserts a `check`
marker survives serialisation would stay green against a frame that carries the
same marker on every grader row — which is a trace a reader still cannot read.
So each test below drives a deterministic rejection *and* a judged verdict and
asserts the two frames differ.

`Verdict.failed_check` has named the check since the field was added; it
travelled nowhere. `_grader` dropped it when writing `verdicts`, so neither the
`update` frame a trace is built from nor the `interrupt` frame a reviewer reads
had ever seen it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from openstategraph.api.streaming import FRAME_FIELDS, _stream_run
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

from test_human_approval import _fake_model, edge, node


def graded_document(*, max_attempts: int = 1) -> dict[str, Any]:
    """in -> draft -[candidate]-> grader -[pass]-> out; grader -[revise]-> draft"""
    return {
        "version": 1,
        "name": "graded",
        "nodes": [
            node("in1", "input.text"),
            node("draft1", "agent.llm"),
            node("grader1", "route.grader", criteria="No hedging.", maxAttempts=max_attempts),
            node("out1", "output.formatted"),
        ],
        "edges": [
            edge("in1", "text", "draft1", "prompt"),
            edge("draft1", "result", "grader1", "candidate"),
            edge("grader1", "pass", "out1", "result"),
            edge("grader1", "revise", "draft1", "feedback"),
        ],
    }


def grader_frame(document: dict[str, Any], *answers: str, thread_id: str) -> dict[str, Any]:
    """The `update` frame the grader node emitted, as a client receives it."""
    runtime = NodeRuntime(model=_fake_model(*answers))
    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    graph = compiler.build(
        document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
    )
    names = {safe_name(n): n for n in plan.nodes}
    frames = list(
        _stream_run(
            graph,
            {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
            {"configurable": {"thread_id": thread_id}},
            plan,
            names,
            runtime,
            thread_id,
        )
    )
    for frame in frames:
        if not frame.startswith("event: update\n"):
            continue
        payload = json.loads(frame.split("data: ", 1)[1])
        if payload.get("node") == "grader1":
            return payload
    raise AssertionError(f"no grader frame in {frames}")


#: An answer whose first word trips `deterministic_checks` — the grader returns
#: before `self.model.invoke`, so the fake model is never asked for a verdict
#: and one answer is enough for the whole run.
TRANSPORTED_ERROR = "Error: connection refused"


class TestTheTwoPathsAreDistinguishable:
    def test_a_deterministic_rejection_names_its_check_and_a_judgement_does_not(self) -> None:
        skipped = grader_frame(graded_document(), TRANSPORTED_ERROR, thread_id="t92-skip")
        judged = grader_frame(
            graded_document(), "A firm answer.", "PASS", thread_id="t92-judged"
        )

        # The measurement this ticket exists for: before the fix these two
        # dicts differed only in `output`, which is the candidate text and says
        # nothing about what the grader did.
        assert skipped != judged
        assert skipped["check"] == "error"
        assert "check" not in judged

    def test_the_reason_travels_with_the_check_so_a_row_can_be_written(self) -> None:
        skipped = grader_frame(graded_document(), TRANSPORTED_ERROR, thread_id="t92-reason")
        judged = grader_frame(
            graded_document(), "A firm answer.", "PASS", thread_id="t92-reason-ok"
        )
        assert "connection refused" in skipped["reason"]
        assert "reason" not in judged

    def test_an_empty_candidate_names_a_different_check_than_a_transported_error(self) -> None:
        """The marker is the check that fired, not a single "was deterministic" flag."""
        empty = grader_frame(graded_document(), "   ", thread_id="t92-empty")
        error = grader_frame(graded_document(), TRANSPORTED_ERROR, thread_id="t92-error")
        assert empty["check"] == "empty"
        assert error["check"] == "error"

    def test_the_frame_contract_declares_the_field(self) -> None:
        """`FRAME_FIELDS` is what `docs/openapi.json` publishes to a client."""
        assert "check" in FRAME_FIELDS["update"]
        assert "reason" in FRAME_FIELDS["update"]
        assert "check" in FRAME_FIELDS["interrupt"]


#: The clause every surface uses for the one fact this ticket adds. Three
#: surfaces render it — the editor's trace row, the editor's approval card and
#: `/chat`'s approval box — in three languages, and `/chat`'s copy of the
#: verdict sentence is a hand-kept second spelling of `graderVerdictLine.ts`
#: that predates this ticket. One judgement described three ways is the drift
#: this pins; the duplication itself is filed as `production-ready/94`.
CLAUSE = "without a model call"

REPO = Path(__file__).resolve().parents[2]


class TestEveryDoorSaysTheSameThing:
    def test_the_three_surfaces_share_one_clause(self) -> None:
        for relative in (
            "src/view/ask/graderCheckLine.ts",
            "src/view/ask/graderVerdictLine.ts",
            "backend/openstategraph/api/static/chat.html",
        ):
            source = (REPO / relative).read_text(encoding="utf-8")
            assert CLAUSE in source, f"{relative} does not carry the clause"

    def test_chat_reads_the_field_the_stream_actually_sends(self) -> None:
        """A clause spelled into the page against a field name nobody emits."""
        page = (REPO / "backend/openstategraph/api/static/chat.html").read_text(
            encoding="utf-8"
        )
        assert 'd.check' in page
        assert "check" in FRAME_FIELDS["interrupt"]
