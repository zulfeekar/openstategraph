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
from openstategraph import patrol as patrol_module
from openstategraph.patrol import (
    PATROL_SESSION_PREFIX,
    card_session_id,
    classify_finding,
    run_patrol,
)
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

    def test_a_thread_whose_card_is_finished_is_excluded_from_the_next_patrol(
        self, tmp_path: Path
    ) -> None:
        """`kanban-patrol/22`: a card worked to `finished` leaves its own
        resolution work sitting in the same thread. The next patrol still
        *reads* that thread's finding — `total_findings` counts it — but
        files nothing, because the thread's `task_id` is already taken.

        The narrower `attended` case above is not this one: a resolved card
        is the end of the ladder, and it is the stage a re-file would be
        most damaging at.
        """
        from openstategraph.kanban_store import Stage, set_stage

        root = tmp_path / "workflows"
        run_patrol(project_id="proj-x", workflows_root=root, savers=[_Saver(_redundant_thread())], records=[_run_record()])
        db = kanban_store_path(root)
        task_id = f"proj-x:{THREAD}"
        set_stage(db, task_id, Stage.ATTENDED, actor="alice")
        set_stage(db, task_id, Stage.RED, actor="alice", test_id="tests/test_x.py::test_y", reason="reproduced")
        set_stage(db, task_id, Stage.GREEN, actor="alice", test_id="tests/test_x.py::test_y")
        set_stage(db, task_id, Stage.FINISHED, actor="alice", commit="deadbee")
        assert read_card(db, task_id).stage is Stage.FINISHED

        second = run_patrol(
            project_id="proj-x",
            workflows_root=root,
            savers=[_Saver(_redundant_thread())],
            records=[_run_record()],
        )

        assert second.filed == []
        assert second.skipped == [task_id]
        # The finding is still read and counted — the exclusion is about
        # filing, never about pretending the thread produced nothing.
        assert second.total_findings == 1

        card = read_card(db, task_id)
        assert card.stage is Stage.FINISHED
        assert card.actor == "alice"

    def test_no_findings_is_an_empty_result_not_an_error(self, tmp_path: Path) -> None:
        result = run_patrol(project_id="proj-x", workflows_root=tmp_path / "workflows", savers=[_Saver([])], records=[])

        assert result.filed == []
        assert result.total_findings == 0


# --- The self-reference exclusion — `kanban-patrol/08` -----------------------
# A patrol that reads *every* recorded thread eventually reads the threads its
# own work produced: an agent attending card X asks the workflow a question to
# reproduce the defect, and that question is a run, in a thread, with findings
# of its own. `02`'s dedup key does not save it — that thread is genuinely new,
# so the next patrol files a card about the work done on the last card.
#
# The rule names such runs by something the run **already records**: the
# `session_id` on `RunRecord`. A run made while working a card carries
# `card:<task_id>`; a run made by a patrol driver carries `patrol:<whatever>`.
# Nothing about the store changed — no column, no migration — because the field
# that says *which sitting this run belongs to* is the field that already
# exists, and an agent working a card is a sitting.


class TestTheSelfReferenceExclusion:
    def test_a_run_marked_as_card_work_is_not_filed(self, tmp_path: Path) -> None:
        """The whole ticket, in one assertion: the thread an agent produced
        while working card `proj-x:other` never becomes a card of its own."""
        marked = _run_record().model_copy(
            update={"session_id": card_session_id("proj-x:other")}
        )

        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=[_Saver(_redundant_thread())],
            records=[marked],
        )

        assert result.filed == []
        assert result.excluded == [THREAD]
        # Not read at all, and that is the difference from `22`'s skip: a
        # filed card's thread is still *read* and counted, because the
        # evidence is real and only the filing is a duplicate. This thread's
        # evidence is the patrol's own reflection, so counting it would put a
        # number on the board that means nothing.
        assert result.total_findings == 0

    def test_a_run_marked_as_patrol_work_is_not_filed(self, tmp_path: Path) -> None:
        marked = _run_record().model_copy(
            update={"session_id": f"{PATROL_SESSION_PREFIX}2026-09-04"}
        )

        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=[_Saver(_redundant_thread())],
            records=[marked],
        )

        assert result.filed == []
        assert result.excluded == [THREAD]

    def test_an_unmarked_run_is_still_filed(self, tmp_path: Path) -> None:
        """The exclusion is narrow. Ordinary traffic — every run this product
        has ever recorded, all of which carry an empty or a browser-minted
        `session_id` — is untouched by it."""
        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=[_Saver(_redundant_thread())],
            records=[_run_record().model_copy(update={"session_id": "tab-9f2a"})],
        )

        assert result.filed == [f"proj-x:{THREAD}"]
        assert result.excluded == []

    def test_one_marked_run_excludes_the_whole_thread(self, tmp_path: Path) -> None:
        """A thread is one conversation. If any turn in it was made while
        working a card, the calls in it were made *for* that work — the
        message channel is cumulative, so a later unmarked turn had the
        marked turn's tool results in front of it and a `REDUNDANT_TOOL_CALL`
        across the two is the agent's own repetition. Excluding the thread is
        the conservative direction: the cost of a wrong exclusion is one card
        nobody files, the cost of a wrong inclusion is the board filling with
        its own shadow."""
        rows = [
            _run_record().model_copy(update={"session_id": ""}),
            _run_record().model_copy(update={"session_id": card_session_id("proj-x:other")}),
        ]

        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=[_Saver(_redundant_thread())],
            records=rows,
        )

        assert result.filed == []
        assert result.excluded == [THREAD]

    def test_the_prefix_is_matched_at_the_start_never_anywhere(self, tmp_path: Path) -> None:
        """A session called `wildcard:7` is not card work, and a substring
        match would have said it was."""
        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=[_Saver(_redundant_thread())],
            records=[_run_record().model_copy(update={"session_id": "wildcard:7"})],
        )

        assert result.filed == [f"proj-x:{THREAD}"]


class TestThePatrolRecordsNoRunsOfItsOwn:
    """One half of the trap is answered by construction, and this pins it
    rather than leaving it to be rediscovered.

    `run_patrol` reads. It asks no model, opens no run loop, and writes no
    `RunRecord` — so the patrol's *own* execution leaves nothing for a later
    patrol to read, and the `patrol:` prefix above exists for a **driver** (a
    coding agent following the bundled skill file, or `05`'s model-driven
    classifier if it ever lands) rather than for this function.

    The day `run_patrol` grows a model call, this test goes red and whoever
    added it has to mark its own runs.
    """

    def test_a_patrol_writes_no_run_rows(self, tmp_path: Path) -> None:
        from openstategraph.run_sinks import read_runs, run_store_path

        root = tmp_path / "workflows"
        run_patrol(
            project_id="proj-x",
            workflows_root=root,
            savers=[_Saver(_redundant_thread())],
            records=[_run_record()],
        )

        assert read_runs(run_store_path(root)) == []

    def test_the_module_reaches_no_run_door(self) -> None:
        text = Path(patrol_module.__file__).read_text()

        for forbidden in ("run_turn", "invoke_run", "RunLoop", "build_chat_model"):
            assert forbidden not in text, (
                f"`patrol.py` reached {forbidden!r}. A patrol that executes something "
                "records a run a later patrol will read — mark it with "
                "`PATROL_SESSION_PREFIX` and rewrite this test."
            )


class TestEveryDoorCanSetTheMarker:
    """A marker only one door can set excludes only that door's runs.

    Three producers reach the run store while somebody is working the board:
    a shell-attached agent running `openstategraph run`, an agent driving this
    product over MCP, and the editor. The first two are the ones that work
    cards, so both must be able to name the sitting they are in.
    """

    def test_the_cli_run_command_accepts_a_session(self) -> None:
        from openstategraph.cli import build_parser

        args = build_parser().parse_args(
            ["run", "pkg", "hello", "--session-id", card_session_id("proj-x:t1")]
        )

        assert args.session_id == "card:proj-x:t1"

    def test_the_cli_hands_it_to_ask(self, monkeypatch: Any) -> None:
        """Parsed and dropped is the failure mode a parser test cannot see."""
        import openstategraph.cli as cli

        seen: dict[str, Any] = {}

        class _Workflow:
            # `osg-agent-experience/48`: the CLI door asks the loaded workflow
            # whether this machine can serve the model it will reach. A stand-in
            # for `CompiledWorkflow` has to answer it, and the honest answer for
            # a fake that never calls a model is False.
            needs_a_provider = False

            slug = "demo"
            document: dict[str, Any] = {}

            def ask(self, question: str, **kwargs: Any) -> Any:
                seen.update(kwargs)
                raise SystemExit(0)

        monkeypatch.setattr(cli, "_load", lambda args: _Workflow())
        monkeypatch.setattr(
            "openstategraph.compile.run_context.coerce_context_flags",
            lambda document, supplied, slug: {},
        )
        args = build = cli.build_parser().parse_args(
            ["run", "pkg", "hello", "--session-id", "card:proj-x:t1"]
        )
        del build
        try:
            cli.cmd_run(args)
        except SystemExit:
            pass

        assert seen.get("session_id") == "card:proj-x:t1"

    def test_the_mcp_run_door_accepts_a_session(self, tmp_path: Path) -> None:
        import asyncio

        from openstategraph.api.services import WorkflowServices
        from openstategraph.mcp_server import build_mcp_server

        server = build_mcp_server(WorkflowServices(workflows_root=tmp_path))

        tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        properties = tools["run_workflow"].inputSchema.get("properties", {})

        assert "session_id" in properties, (
            "An agent working a card over MCP cannot name the sitting its runs "
            "belong to, so the exclusion above sees none of them."
        )
