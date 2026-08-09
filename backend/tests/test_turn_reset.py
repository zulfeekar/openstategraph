"""Turn-boundary reset: a checkpointed thread keeps the conversation, not the scratch.

Found live in /chat: turn 1's `outputs` (a research report) survived into
turn 2 via the thread checkpointer, and the output node replayed it as the
answer to "how did you get this answer?". Reducers can only add, so the
input node emits a RESET marker each reducer understands.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import (
    RESET,
    NodeRuntime,
    RunState,
    keep_latest_nonempty,
    keep_max,
    merge_decisions,
)


class TestReducersUnderstandReset:
    def test_merge_drops_stale_entries_on_reset(self) -> None:
        assert merge_decisions({"old": "stale"}, {RESET: "", "in1": "hi"}) == {"in1": "hi"}

    def test_merge_still_merges_without_the_marker(self) -> None:
        assert merge_decisions({"a": "1"}, {"b": "2"}) == {"a": "1", "b": "2"}

    def test_keep_latest_nonempty_clears_on_reset(self) -> None:
        assert keep_latest_nonempty("previous answer", RESET) == ""

    def test_keep_latest_nonempty_still_refuses_plain_empty(self) -> None:
        assert keep_latest_nonempty("previous answer", "") == "previous answer"

    def test_keep_max_zeroes_on_a_negative_reset_write(self) -> None:
        assert keep_max(3, -1) == 0

    def test_keep_max_still_keeps_the_maximum(self) -> None:
        assert keep_max(2, 1) == 2


class TestInputNodeEmitsTheBoundary:
    def test_input_resets_every_scratch_channel(self) -> None:
        runtime = NodeRuntime(model=None)
        run = runtime._input("in1", {"id": "in1", "type": "input.text", "data": {}}, None)
        update = run(RunState(question="turn two"))  # type: ignore[typeddict-item]
        assert update["outputs"][RESET] == ""
        assert update["outputs"]["in1"] == "turn two"
        assert update["decisions"] == {RESET: ""}
        assert update["answer"] == RESET
        assert update["feedback"] == RESET
        assert update["attempts"] == -1

    def test_the_conversation_channel_is_not_reset(self) -> None:
        runtime = NodeRuntime(model=None)
        run = runtime._input("in1", {"id": "in1", "type": "input.text", "data": {}}, None)
        update = run(RunState(question="turn two"))  # type: ignore[typeddict-item]
        # messages may be appended to, never wiped
        assert RESET not in str(update.get("messages", ""))
