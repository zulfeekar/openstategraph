"""The in-built patrol — `kanban-patrol/07`'s missing prerequisite.

`07` assumed a patrol function already existed and wrote the async/SSE
machinery around it. There was no patrol function at all — no deterministic
read-classify-file loop, sync or async. This is that loop: no model
required, reusing `run_findings()` and `kanban_store` exactly as they are,
never a second implementation of either.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openstategraph.kanban_store import kanban_store_path, read_card
from openstategraph.patrol import classify_finding, run_patrol
from openstategraph.run_findings import NODE_FAILURE, REDUNDANT_TOOL_CALL, UNSTABLE_TOOL_RESULT, RunFinding


def _finding(name: str, **overrides: Any) -> RunFinding:
    fields: dict[str, Any] = {
        "name": name,
        "thread_id": "thread-1",
        "workflow_slug": "demo",
        "tool": "some_tool",
        "arguments": "{}",
        "calls": 2,
        "distinct_results": 1,
        "checkpoints": ["cp-0", "cp-1"],
        "thread_tool_calls": 2,
    }
    fields.update(overrides)
    return RunFinding(**fields)


class TestClassifyFinding:
    """One deterministic mapping, per finding type — no model, no judgment
    call left to chance. Every one cites its own evidence in the reason,
    never a plausible-sounding elaboration — `atom-forge`'s own rule."""

    def test_redundant_tool_call_is_a_task_gap(self) -> None:
        c = classify_finding(_finding(REDUNDANT_TOOL_CALL, tool="chinook_list_tables", calls=2))

        assert c.kind == "task"
        assert c.category == "gap"
        assert "chinook_list_tables" in c.reason
        assert "2" in c.reason

    def test_more_repeats_is_higher_priority(self) -> None:
        low = classify_finding(_finding(REDUNDANT_TOOL_CALL, calls=2))
        med = classify_finding(_finding(REDUNDANT_TOOL_CALL, calls=3))
        high = classify_finding(_finding(REDUNDANT_TOOL_CALL, calls=5))

        assert (low.priority, med.priority, high.priority) == ("low", "med", "high")

    def test_a_sequential_repeat_reads_like_it_always_has(self) -> None:
        """`distinct_namespaces=1` — one node, called `calls` times in a row.
        `kanban-patrol/13`'s first bucket: real repetition, wording unchanged."""
        c = classify_finding(
            _finding(
                REDUNDANT_TOOL_CALL,
                tool="sql_list_tables",
                calls=19,
                distinct_namespaces=1,
            )
        )

        assert "19" in c.reason
        assert "sql_list_tables" in c.reason
        assert "fan-out" not in c.reason
        assert "worker" not in c.reason
        assert c.priority == "high"

    def test_pure_fan_out_reads_differently_and_is_not_called_repetition(self) -> None:
        """`distinct_namespaces == calls` — every call from its own worker.
        `kanban-patrol/13`'s whole point: this is not the same finding as a
        sequential repeat and must not read like one."""
        c = classify_finding(
            _finding(
                REDUNDANT_TOOL_CALL,
                tool="sql_list_tables",
                calls=19,
                distinct_namespaces=19,
            )
        )

        assert "worker" in c.reason
        assert "fan-out" in c.reason
        assert "19" in c.reason
        # The remedy named is a shared lookup across workers, not a tool note.
        assert "shared" in c.reason
        assert "no loop to fix" in c.reason

    def test_the_two_extremes_produce_genuinely_different_text(self) -> None:
        sequential = classify_finding(
            _finding(REDUNDANT_TOOL_CALL, tool="sql_list_tables", calls=19, distinct_namespaces=1)
        )
        fanout = classify_finding(
            _finding(REDUNDANT_TOOL_CALL, tool="sql_list_tables", calls=19, distinct_namespaces=19)
        )

        assert sequential.reason != fanout.reason
        assert sequential.title != fanout.title

    def test_pure_fan_out_is_filed_lower_than_the_same_count_would_be_if_sequential(
        self,
    ) -> None:
        """Same `calls=19` — `_redundant_tool_call_priority` alone would call
        this `high`. Pure fan-out is not the same kind of waste, so it isn't."""
        sequential = classify_finding(
            _finding(REDUNDANT_TOOL_CALL, calls=19, distinct_namespaces=1)
        )
        fanout = classify_finding(
            _finding(REDUNDANT_TOOL_CALL, calls=19, distinct_namespaces=19)
        )

        assert sequential.priority == "high"
        assert fanout.priority == "low"

    def test_a_mix_of_fan_out_and_real_repetition_says_both_honestly(self) -> None:
        """`1 < distinct_namespaces < calls` — some fan-out, some real
        repetition inside at least one namespace. Neither canned sentence
        fits, so both counts are named rather than one being picked."""
        c = classify_finding(
            _finding(
                REDUNDANT_TOOL_CALL,
                tool="sql_list_tables",
                calls=19,
                distinct_namespaces=3,
            )
        )

        assert "19" in c.reason
        assert "3" in c.reason
        assert "fan-out" in c.reason

    def test_unstable_tool_result_is_a_grilling_a_human_must_look_at(self) -> None:
        c = classify_finding(_finding(UNSTABLE_TOOL_RESULT, tool="flaky_tool", distinct_results=2))

        assert c.kind == "grilling"
        assert "flaky_tool" in c.reason
        assert "2" in c.reason

    def test_node_failure_is_a_bug_always_high_priority(self) -> None:
        c = classify_finding(
            _finding(NODE_FAILURE, tool="checkout", arguments="no credential — set ANTHROPIC_API_KEY")
        )

        assert c.kind == "bug"
        assert c.category == "bug"
        assert c.priority == "high"
        assert "checkout" in c.reason
        assert "ANTHROPIC_API_KEY" in c.reason

    def test_the_title_is_the_symptom_never_the_fix(self) -> None:
        c = classify_finding(_finding(NODE_FAILURE, tool="checkout"))

        assert "fix" not in c.title.lower()
        assert "add" not in c.title.lower()
        assert "checkout" in c.title


# --- End-to-end: a real thread, through the real checkpoint-reading path ---
# Same fixture shape `test_the_same_call_twice_is_two_findings.py` already
# uses — a hand-rolled saver, not a mock of `run_findings` itself, so this
# proves the whole read-classify-file loop, not just the classifier.

from langchain_core.messages import AIMessage, ToolMessage

from openstategraph.run_sinks import RunRecord

THREAD = "run-patrol-1"


class _Stub:
    def __init__(self, step: int, messages: list[Any]) -> None:
        self.config = {"configurable": {"thread_id": THREAD, "checkpoint_ns": ""}}
        self.checkpoint = {
            "id": f"cp-{step}",
            "ts": f"2026-09-01T16:0{step}:00+00:00",
            "channel_values": {"messages": list(messages)},
            "updated_channels": ["messages"],
        }
        self.metadata = {"step": step, "source": "loop", "workflow_slug": "demo"}
        self.pending_writes = ()


class _Saver:
    def __init__(self, tuples: list[Any]) -> None:
        self._tuples = list(reversed(tuples))

    def list(self, config: Any, *, limit: int = 200) -> list[Any]:
        return self._tuples[:limit]


def _call(call_id: str, name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args, "type": "tool_call"}])


def _answer(call_id: str, name: str, text: str) -> ToolMessage:
    return ToolMessage(content=text, tool_call_id=call_id, name=name)


def _redundant_thread() -> list[Any]:
    """One tool, called twice, identical result — a real `REDUNDANT_TOOL_CALL`."""
    messages: list[Any] = []
    tuples: list[Any] = []
    for step in range(2):
        messages = [*messages, _call(f"c{step}", "list_tables", {})]
        tuples.append(_Stub(step * 2, messages))
        messages = [*messages, _answer(f"c{step}", "list_tables", "same result")]
        tuples.append(_Stub(step * 2 + 1, messages))
    return tuples


def _run_record() -> RunRecord:
    return RunRecord(
        kind="run", at="2026-09-01T16:09:46+02:00", workflow_slug="demo",
        thread_id=THREAD, seconds=1.0, attempts=1,
    )


class TestRunPatrolEndToEnd:
    def test_a_real_finding_becomes_a_real_card(self, tmp_path: Path) -> None:
        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=[_Saver(_redundant_thread())],
            records=[_run_record()],
        )

        assert result.filed == [f"proj-x:{THREAD}"]
        assert result.total_findings == 1

        db = kanban_store_path(tmp_path / "workflows")
        card = read_card(db, f"proj-x:{THREAD}")
        assert card.kind == "task"
        assert "list_tables" in card.priority_reason

    def test_a_second_run_skips_the_already_filed_card(self, tmp_path: Path) -> None:
        root = tmp_path / "workflows"
        run_patrol(project_id="proj-x", workflows_root=root, savers=[_Saver(_redundant_thread())], records=[_run_record()])

        second = run_patrol(project_id="proj-x", workflows_root=root, savers=[_Saver(_redundant_thread())], records=[_run_record()])

        assert second.filed == []
        assert second.skipped == [f"proj-x:{THREAD}"]

    def test_a_card_already_attended_is_never_reclassified(self, tmp_path: Path) -> None:
        """`02`'s own rule: once a card leaves `unattended`, a re-patrol
        must never touch it again, even with new evidence."""
        from openstategraph.kanban_store import Stage, set_stage

        root = tmp_path / "workflows"
        run_patrol(project_id="proj-x", workflows_root=root, savers=[_Saver(_redundant_thread())], records=[_run_record()])
        db = kanban_store_path(root)
        set_stage(db, f"proj-x:{THREAD}", Stage.ATTENDED, actor="alice")

        run_patrol(project_id="proj-x", workflows_root=root, savers=[_Saver(_redundant_thread())], records=[_run_record()])

        card = read_card(db, f"proj-x:{THREAD}")
        assert card.stage is Stage.ATTENDED
        assert card.actor == "alice"

    def test_no_findings_is_an_empty_result_not_an_error(self, tmp_path: Path) -> None:
        result = run_patrol(project_id="proj-x", workflows_root=tmp_path / "workflows", savers=[_Saver([])], records=[])

        assert result.filed == []
        assert result.total_findings == 0
