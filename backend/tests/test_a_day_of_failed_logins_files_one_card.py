"""A run whose every tool call was refused the same way — `osg-agent-experience/74`.

The try project's warehouse refused every SQL call for a day
(`HYT00 Login timeout expired`, traced afterwards to an expired client
secret). The runs were recorded. The patrol read them and filed nothing, and
the orchestrator found it by hand.

**Measured before it was fixed, and the answer decided the shape.** Of the
three candidate causes the ticket named, it was the first: the patrol had no
finding kind for it. `REDUNDANT_TOOL_CALL` and `UNSTABLE_TOOL_RESULT` group
by `(tool, normalised arguments)` and need the *same* call twice, so three
different SELECTs group into nothing; `NODE_FAILURE` reads the compiler's
failure marker out of `outputs[node_id]`, and a node whose tool returned
`Error: …` did not fail — it produced text. The judge is ruled out by
construction: `every_tool_call_failed` returns a revise *reason*, writes no
state, and is invisible to a reader of the checkpoints.

The worse half is pinned here too: with three **identical** failing calls the
old detector did fire, as a `REDUNDANT_TOOL_CALL` whose card reads *"real
cost, no error, fix is a tool note"*. A day of failed logins filed as waste,
with the words "no error" in it, is worse than the silence.

The unit of the card is the **refusal**, not the thread. Forty runs against
one expired secret are one problem, and `02`'s per-thread key would have
filed forty cards for it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from openstategraph.api.audience import Audience
from openstategraph.kanban_store import kanban_store_path
from kanban_by_path import read_card
from openstategraph.patrol import classify_finding, refusal_task_id, run_patrol
from openstategraph.run_findings import (
    EVERY_TOOL_CALL_FAILED,
    REDUNDANT_TOOL_CALL,
    refusal_key,
    run_findings,
)
from openstategraph.run_sinks import RunRecord

#: The real thing, from the day it happened. Our own `ToolResult.failure`
#: prose (`abc/tool.TOOL_FAILURE_PREFIX`), with the driver's own words after
#: it, and a second line so the "first line" rule has something to cut.
TIMEOUT = (
    "Error: ('HYT00', '[HYT00] [Microsoft][ODBC Driver 18 for SQL Server]"
    "Login timeout expired (0) (SQLDriverConnect)')\n"
    "No rows were read."
)

#: What Azure AD answered once `73` stopped asking the driver to do the login.
EXPIRED_SECRET = (
    "Error: Azure AD refused the service principal: invalid_client — "
    "AADSTS7000222: The provided client secret keys for app "
    "'0000' are expired. No query was sent."
)


class _Stub:
    def __init__(self, thread: str, step: int, messages: list[Any]) -> None:
        self.config = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
        self.checkpoint = {
            "id": f"{thread}-cp-{step}",
            "ts": f"2026-09-05T09:{step:02d}:00+00:00",
            "channel_values": {"messages": list(messages)},
            "updated_channels": ["messages"],
        }
        self.metadata = {"step": step, "source": "loop", "workflow_slug": "cpl-analyst"}
        self.pending_writes = ()


class _Saver:
    """A checkpointer holding several conversations, answering per thread.

    The one-thread stand-ins elsewhere hand back everything they hold; this
    ticket's whole subject is one refusal seen across many threads, so a saver
    that ignores the thread it was asked for would merge them into one.
    """

    def __init__(self, tuples: list[Any]) -> None:
        self._tuples = list(reversed(tuples))

    def list(self, config: Any, *, limit: int = 200) -> list[Any]:
        wanted = (config or {}).get("configurable", {}).get("thread_id")
        chosen = [
            stub
            for stub in self._tuples
            if wanted is None
            or stub.config["configurable"]["thread_id"] == wanted
        ]
        return chosen[:limit]


def _thread(thread: str, calls: list[tuple[str, dict[str, Any], str]]) -> list[Any]:
    messages: list[Any] = []
    tuples: list[Any] = []
    for index, (name, args, answer) in enumerate(calls):
        call_id = f"{thread}-c{index}"
        messages = [
            *messages,
            AIMessage(
                content="",
                tool_calls=[
                    {"id": call_id, "name": name, "args": args, "type": "tool_call"}
                ],
            ),
        ]
        tuples.append(_Stub(thread, index * 2, messages))
        messages = [*messages, ToolMessage(content=answer, tool_call_id=call_id, name=name)]
        tuples.append(_Stub(thread, index * 2 + 1, messages))
    return tuples


def _refused(thread: str, error: str = TIMEOUT) -> list[Any]:
    """Three `mssql_query` calls, three different statements, one refusal."""
    return _thread(
        thread,
        [
            ("mssql_query", {"query": "SELECT TOP 5 * FROM Well"}, error),
            ("mssql_query", {"query": "SELECT COUNT(*) FROM Wellbore"}, error),
            ("mssql_query", {"query": "SELECT name FROM sys.tables"}, error),
        ],
    )


def _healthy(thread: str) -> list[Any]:
    return _thread(
        thread,
        [
            ("mssql_query", {"query": "SELECT TOP 5 * FROM Well"}, "5 rows"),
            ("mssql_query", {"query": "SELECT COUNT(*) FROM Wellbore"}, "1 row: 4211"),
        ],
    )


def _record(thread: str, **overrides: Any) -> RunRecord:
    fields: dict[str, Any] = {
        "kind": "run",
        "at": "2026-09-05T09:41:00+02:00",
        "workflow_slug": "cpl-analyst",
        "thread_id": thread,
        "seconds": 61.0,
        "attempts": 1,
    }
    fields.update(overrides)
    return RunRecord(**fields)


class TestTheFinding:
    """The kind that did not exist — read off the calls, not off a judgement."""

    def test_three_different_statements_one_refusal_is_one_finding(self) -> None:
        found = run_findings(
            [_Saver(_refused("t1"))], [_record("t1")], audience=Audience.DEVELOPER
        )

        assert [f.name for f in found] == [EVERY_TOOL_CALL_FAILED]
        finding = found[0]
        assert finding.tool == "mssql_query"
        assert finding.calls == 3
        # The key: the refusal's first line, never the whole body — the second
        # line varies between calls in the field and would split one problem
        # into several.
        assert finding.arguments == refusal_key(TIMEOUT)
        assert "Login timeout expired" in finding.arguments
        assert "No rows were read" not in finding.arguments

    def test_a_healthy_run_produces_nothing(self) -> None:
        found = run_findings(
            [_Saver(_healthy("t2"))], [_record("t2")], audience=Audience.DEVELOPER
        )

        assert found == []

    def test_one_call_that_came_back_clears_the_whole_thread(self) -> None:
        """`RunSummary.every_call_failed`'s own conjunction, one layer along:
        a run that got an answer from anything is not a run with no answers."""
        tuples = _thread(
            "t3",
            [
                ("mssql_query", {"query": "SELECT 1"}, TIMEOUT),
                ("mssql_query", {"query": "SELECT 2"}, "1 row: 1"),
            ],
        )

        found = run_findings([_Saver(tuples)], [_record("t3")], audience=Audience.DEVELOPER)

        assert [f.name for f in found] == []

    def test_two_different_refusals_are_not_one_refusal(self) -> None:
        """Strict in trusting. *Every* call failed, but not *the same way* —
        that is a run with two problems, and this kind claims one."""
        tuples = _thread(
            "t4",
            [
                ("mssql_query", {"query": "SELECT 1"}, TIMEOUT),
                ("mssql_query", {"query": "SELECT 2"}, EXPIRED_SECRET),
            ],
        )

        found = run_findings([_Saver(tuples)], [_record("t4")], audience=Audience.DEVELOPER)

        assert [f.name for f in found] == []

    def test_a_thread_of_nothing_but_unanswered_calls_says_nothing(self) -> None:
        """`""` means no answer was stored, not that none arrived
        (`ThreadToolCall.result`). Reading it as a refusal would accuse a run
        that was merely stopped."""
        tuples = _thread("t5", [("mssql_query", {"query": "SELECT 1"}, "")])

        found = run_findings([_Saver(tuples)], [_record("t5")], audience=Audience.DEVELOPER)

        assert [f.name for f in found] == []

    def test_an_unanswered_call_is_passed_over_not_counted_against(self) -> None:
        """The other direction, and it is the one the read's own bound makes
        real: `run_findings` keeps the newest `limit` checkpoints, so a
        conversation can arrive here with a request whose answer was cut off.
        Refusing the finding for that would be the silence this ticket is
        about. The unanswered call is passed over — `calls` counts the calls
        that came back, so the card never claims more than it read."""
        tuples = _thread(
            "t5b",
            [
                ("mssql_query", {"query": "SELECT 1"}, TIMEOUT),
                ("mssql_query", {"query": "SELECT 2"}, ""),
            ],
        )

        found = run_findings([_Saver(tuples)], [_record("t5b")], audience=Audience.DEVELOPER)

        assert [f.name for f in found] == [EVERY_TOOL_CALL_FAILED]
        assert found[0].calls == 1

    def test_identical_failing_calls_are_not_reported_as_waste(self) -> None:
        """The worse half of the defect. Before this ticket these three
        grouped into a `REDUNDANT_TOOL_CALL` whose card says *"real cost, no
        error, fix is a tool note"* — a day of failed logins filed as waste."""
        tuples = _thread(
            "t6",
            [("mssql_query", {"query": "SELECT 1"}, TIMEOUT) for _ in range(3)],
        )

        found = run_findings([_Saver(tuples)], [_record("t6")], audience=Audience.DEVELOPER)

        assert [f.name for f in found] == [EVERY_TOOL_CALL_FAILED]
        assert REDUNDANT_TOOL_CALL not in {f.name for f in found}


class TestTheCard:
    """One card, and what it is allowed to say."""

    def test_the_story_quotes_the_refusal_and_names_the_type_and_the_variables(
        self,
    ) -> None:
        from openstategraph.mssql_connection import AAD_VARS, PART_VARS

        found = run_findings(
            [_Saver(_refused("t1"))], [_record("t1")], audience=Audience.DEVELOPER
        )
        classification = classify_finding(found[0])

        assert classification.kind == "bug"
        assert classification.priority == "high"
        assert "Login timeout expired" in classification.reason
        # The tool *type*, resolved from the registry rather than restated.
        assert "tool.mssql-query" in classification.reason
        for name in (*PART_VARS, *AAD_VARS):
            assert name in classification.reason

    def test_no_value_of_any_variable_is_ever_printed(self) -> None:
        """Names only. The card is a board row, and a board row is read by
        whoever opens the board."""
        found = run_findings(
            [_Saver(_refused("t1", EXPIRED_SECRET))],
            [_record("t1")],
            audience=Audience.DEVELOPER,
        )
        classification = classify_finding(found[0])

        text = f"{classification.reason} {classification.title}"
        assert "os.environ" not in text
        # The one secret shaped thing in the refusal is the app id Azure AD
        # echoed back, and the classifier adds nothing of its own.
        assert text.count("AADSTS7000222") >= 1

    def test_the_aad_code_is_named_when_azure_ad_supplied_one(self) -> None:
        """`73` made the real cause reachable — an expired secret answers with
        a code. A card that has one and does not print it wastes it.

        Asserted as *named*, not as *present*: the reason quotes the whole
        refusal, so a code buried in that quote satisfies `in` while the
        classifier does nothing at all. It has to say the code is the cause.
        """
        found = run_findings(
            [_Saver(_refused("t1", EXPIRED_SECRET))],
            [_record("t1")],
            audience=Audience.DEVELOPER,
        )
        reason = classify_finding(found[0]).reason

        assert reason.count("AADSTS7000222") == 2
        assert "Azure AD named the cause itself" in reason

    def test_a_refusal_with_no_aad_code_says_nothing_about_one(self) -> None:
        found = run_findings(
            [_Saver(_refused("t1"))], [_record("t1")], audience=Audience.DEVELOPER
        )

        assert "AADSTS" not in classify_finding(found[0]).reason

    def test_the_title_is_the_symptom_never_the_fix(self) -> None:
        found = run_findings(
            [_Saver(_refused("t1"))], [_record("t1")], audience=Audience.DEVELOPER
        )
        title = classify_finding(found[0]).title

        assert "mssql_query" in title
        assert "fix" not in title.lower()
        assert "set " not in title.lower()


class TestOneCardAcrossManyRuns:
    """Forty runs against one expired secret are one problem."""

    def test_forty_threads_one_refusal_is_one_card_with_the_count(
        self, tmp_path: Path
    ) -> None:
        threads = [f"t{n}" for n in range(40)]
        savers = [_Saver(sum((_refused(t) for t in threads), []))]

        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=savers,
            records=[_record(t) for t in threads],
        )

        assert result.filed == [refusal_task_id("proj-x", refusal_key(TIMEOUT))]

        card = read_card(kanban_store_path(tmp_path / "workflows"), result.filed[0])
        assert card.kind == "bug"
        assert "40" in card.priority_reason

    def test_the_key_is_the_refusal_so_two_refusals_are_two_cards(
        self, tmp_path: Path
    ) -> None:
        savers = [_Saver(_refused("t1") + _refused("t2", EXPIRED_SECRET))]

        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=savers,
            records=[_record("t1"), _record("t2")],
        )

        assert sorted(result.filed) == sorted(
            [
                refusal_task_id("proj-x", refusal_key(TIMEOUT)),
                refusal_task_id("proj-x", refusal_key(EXPIRED_SECRET)),
            ]
        )

    def test_a_healthy_run_files_nothing(self, tmp_path: Path) -> None:
        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=[_Saver(_healthy("t2"))],
            records=[_record("t2")],
        )

        assert result.filed == []

    def test_a_second_patrol_files_nothing_new(self, tmp_path: Path) -> None:
        root = tmp_path / "workflows"
        kwargs: dict[str, Any] = {
            "project_id": "proj-x",
            "workflows_root": root,
            "savers": [_Saver(_refused("t1"))],
            "records": [_record("t1")],
        }
        first = run_patrol(**kwargs)

        second = run_patrol(**kwargs)

        assert first.filed == [refusal_task_id("proj-x", refusal_key(TIMEOUT))]
        assert second.filed == []
        assert second.skipped == first.filed

    def test_a_later_run_of_the_same_refusal_files_nothing_new(
        self, tmp_path: Path
    ) -> None:
        """`02`'s rule holds across the new key too: the card exists, so the
        thirty-ninth run of the same expired secret adds no row."""
        root = tmp_path / "workflows"
        run_patrol(
            project_id="proj-x",
            workflows_root=root,
            savers=[_Saver(_refused("t1"))],
            records=[_record("t1")],
        )

        second = run_patrol(
            project_id="proj-x",
            workflows_root=root,
            savers=[_Saver(_refused("t1") + _refused("t2"))],
            records=[_record("t1"), _record("t2")],
        )

        assert second.filed == []

    def test_the_task_id_carries_a_digest_of_the_refusal_not_the_refusal(self) -> None:
        """A `task_id` is a key in a store and appears in URLs; a driver's
        error message is prose with quotes and newlines in it."""
        task_id = refusal_task_id("proj-x", refusal_key(TIMEOUT))

        assert task_id.startswith("proj-x:refusal:")
        assert " " not in task_id
        digest = hashlib.sha256(refusal_key(TIMEOUT).encode("utf-8")).hexdigest()[:12]
        assert task_id.endswith(digest)

    def test_the_marked_thread_exclusion_still_applies(self, tmp_path: Path) -> None:
        """`08`: a run an agent made while working a card is the patrol's own
        reflection, whichever kind its findings are."""
        from openstategraph.patrol import card_session_id

        result = run_patrol(
            project_id="proj-x",
            workflows_root=tmp_path / "workflows",
            savers=[_Saver(_refused("t1"))],
            records=[_record("t1", session_id=card_session_id("proj-x:other"))],
        )

        assert result.filed == []
        assert result.excluded == ["t1"]


class TestTheSkillSheetNamesTheKind:
    """A driver following the sheet has to know this kind exists."""

    def test_the_bundled_sheet_names_it(self) -> None:
        sheet = (
            Path(__file__).resolve().parents[1]
            / "openstategraph/agent_skills/kanban-patrol/SKILL.md"
        )

        assert EVERY_TOOL_CALL_FAILED in sheet.read_text()
