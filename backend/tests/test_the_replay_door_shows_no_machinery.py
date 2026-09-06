"""A past run showed the customer the ```suggestion fence. The live one does not.

`memory-and-replay` 38. `api/audience.py` promises, in as many words, that *a
customer's answer cannot contain one*. True on the live door — `split_suggestion`
runs on every run before the audience is consulted. False in **History**, where
`api/threads.py` reads `channel_values` straight out of the checkpointer and
renders them, and the checkpointed `answer` keeps its fence on purpose so the
transport can route it to the developer channel.

Not a regression: a door opened after the rule was written, and the rule was
never carried through it.

The second half of this file is the part that matters longer. `split_suggestion`
is safe to run over arbitrary channel values only because it is narrow — both
`nodeType` and `attachTo`, or nothing — and this product prints JSON as prose
constantly: SQL rows, and `workflow-architect` answering with an entire workflow
document. A fix that strips a little too eagerly is the next bug, not the end of
this one.
"""

from __future__ import annotations

from openstategraph.api import threads as thread_queries

FENCED = (
    "# Morning brief\n\n### task-1\nI can't retrieve the exact text from "
    "https://example.com because this workflow lacks a tool for fetching a page.\n\n"
    '```suggestion\n{"nodeType": "none", "attachTo": "worker-web", "port": "tools", '
    '"label": "Web page fetch", "reason": "missing tool to fetch full page content"}\n```'
)

BARE = (
    "I don't have a tool that can retrieve real-time information.\n"
    '{"nodeType": "tool.web-search", "attachTo": "agent-world", "port": "tools"}'
)


class _Checkpoint:
    """The shape `api/threads.py` reads: a checkpoint tuple, nothing more."""

    def __init__(self, values: dict, metadata: dict | None = None) -> None:
        self.config = {"configurable": {"thread_id": "run-1"}}
        self.checkpoint = {"id": "cp-1", "ts": "2026-08-20T06:33:06+00:00", "channel_values": values}
        self.metadata = metadata or {"step": 3, "source": "loop", "workflow_slug": "morning-brief"}
        self.pending_writes = ()


class TestTheMachineryDoesNotSurviveIntoHistory:
    def test_the_summarys_answer_is_the_prose_only(self) -> None:
        summary = thread_queries._summarize(
            "run-1", _Checkpoint({"question": "q", "answer": FENCED}), steps=40
        )
        assert "nodeType" not in summary.answer
        assert "```suggestion" not in summary.answer
        assert "I can't retrieve the exact text" in summary.answer

    def test_every_rendered_channel_value_is_stripped_not_just_the_answer(self) -> None:
        """`outputs` and `worker_results` carry the same text under other keys."""
        step = thread_queries._step(
            _Checkpoint({"answer": FENCED, "outputs": {"join1": FENCED}})
        )
        assert all("nodeType" not in value for value in step.values.values())

    def test_an_unfenced_object_goes_too(self) -> None:
        """`every-workflow-green` 15's shape. The fence was never the point."""
        step = thread_queries._step(_Checkpoint({"answer": BARE}))
        assert "nodeType" not in step.values["answer"]
        assert "real-time information" in step.values["answer"]

    def test_a_value_that_is_only_machinery_reads_as_the_customer_sentence(self) -> None:
        """Not an empty cell — the same sentence the live door would have shown."""
        from openstategraph.developer_channel import NO_PROSE

        step = thread_queries._step(
            _Checkpoint({"answer": '```suggestion\n{"nodeType": "none", "attachTo": "w"}\n```'})
        )
        assert step.values["answer"] == NO_PROSE


class TestItDoesNotStripWhatIsActuallyTheAnswer:
    """The narrowness is the safety, and it is the part that regresses."""

    def test_a_sql_result_row_is_left_alone(self) -> None:
        rows = '[{"Artist": "Iron Maiden", "Tracks": 213}, {"Artist": "U2", "Tracks": 135}]'
        step = thread_queries._step(_Checkpoint({"answer": rows}))
        assert step.values["answer"] == rows

    def test_a_whole_workflow_document_is_left_alone(self) -> None:
        """`workflow-architect` answers with one of these. It is the deliverable."""
        document = (
            '{"version": 3, "name": "Draft", "nodes": [{"id": "in1", "type": "input.text"}], '
            '"edges": []}'
        )
        step = thread_queries._step(_Checkpoint({"answer": document}))
        assert step.values["answer"] == document

    def test_an_object_carrying_only_one_of_the_two_keys_is_left_alone(self) -> None:
        prose = 'The node it added was {"nodeType": "tool.web-search"} and nothing more.'
        step = thread_queries._step(_Checkpoint({"answer": prose}))
        assert step.values["answer"] == prose


class TestTheStripHappensBeforeTheCap:
    """A truncated fence is worse than a whole one — it cannot even be parsed."""

    def test_a_long_answer_keeps_its_prose_and_loses_its_fence(self, monkeypatch) -> None:
        monkeypatch.setattr(thread_queries, "_VALUE_LIMIT", 800)
        long_prose = "The handbook says the release checklist has seven items. " * 12
        step = thread_queries._step(_Checkpoint({"answer": long_prose + "\n\n" + FENCED}))
        value = step.values["answer"]
        assert "nodeType" not in value
        assert value.startswith("The handbook says")
