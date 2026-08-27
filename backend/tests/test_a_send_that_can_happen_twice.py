"""launch-readiness 121 — a capability that acts outside the run, run twice.

`workflows/support-triage` binds three `tool.email-send` to `a-account`, and
`a-account` sits inside `router1 -> a-account -> grader1 -> router1`. Two
independent mechanisms re-enter that node and neither carries any memory of
what it already did:

- **Retry.** `workflow_compiler.build` gives every node
  `RetryPolicy(max_attempts=3)` through `set_node_defaults`. LangGraph's own
  words for what that does: *"A retry policy automatically re-runs a failed
  node attempt"* — the whole node body, so a send that succeeded before a
  later failure inside the same attempt is performed again.
- **The revision loop.** A grader asking for a revision after the mail went
  out gets a second mail, bounded only by the step budget.

And `gate1` — a `human.approval` reading *"Approve to send it"* — sits
**downstream** of the only send capability, so the mail is gone before a
person is asked. That is LangGraph's documented hazard read at graph scale:
*"Place side effects after `interrupt` calls"* / *"Separate side effects into
separate nodes when possible"* (docs-langchain, Interrupts; installed
`langgraph 1.2.10`).

**Both findings are reports, not failures.** Their condition rests on a
*conservative assumption* about an undeclared tool rather than on an observed
fact, and `8bda508`'s rule is that a report may not move an exit code. That is
the whole bargain of conservative-by-default: it earns the right to be loud by
never being fatal.

**The narrowness is the load-bearing half**, exactly as it is for
`STALE_TOOL_DENIAL`. A read-only node inside a cycle is *correct*, and a
finding that fires on it is one a developer learns to skip.
"""

from __future__ import annotations

from typing import Any

from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult
from openstategraph.api.services import WorkflowServices
from openstategraph.compile.diagnostics import REPORT_ONLY, Finding
from openstategraph.compile.side_effects import (
    DEFAULT_MAX_ATTEMPTS,
    acts_outside_the_run,
    max_attempts,
    reaches_itself,
    repetition_clause,
    upstream_of,
)
from openstategraph.compile.workflow_compiler import WorkflowCompiler


# ------------------------------------------------------------------ #
# How OSG knows a tool acts outside the run
# ------------------------------------------------------------------ #


class TestAnUndeclaredToolLandsOnTheSafeSide:
    """The ticket's open question, answered conservatively and pinned.

    A naming convention (`tool.email-send`, `tool.slack-send`) would be wrong
    the first time somebody writes `tool.notify-oncall`, and wrong *silently*
    and in the unsafe direction — which is the shape of the defect this ticket
    is about. So the declaration is a flag on the tool ladder, additive
    (`async-first/04`'s rule for Tier-1), and its default is the safe answer.
    """

    def test_a_tool_that_says_nothing_is_treated_as_acting(self) -> None:
        class SaysNothing(BaseTool):
            name = "says_nothing"
            description = ""
            Args = NoArgs

            def _execute(self, args: Any) -> ToolResult:
                return ToolResult()

        assert acts_outside_the_run(SaysNothing())

    def test_a_tool_that_declares_itself_read_only_is_believed(self) -> None:
        class OnlyReads(BaseTool):
            name = "only_reads"
            description = ""
            Args = NoArgs
            side_effecting = False

            def _execute(self, args: Any) -> ToolResult:
                return ToolResult()

        assert not acts_outside_the_run(OnlyReads())

    def test_an_object_that_is_not_ours_at_all_is_treated_as_acting(self) -> None:
        """A registry may hold something that never inherited from `BaseTool`
        — the `ITool` protocol exists precisely so it can. It gets the same
        safe answer, from `getattr`'s default rather than from a class body."""
        assert acts_outside_the_run(object())

    def test_the_shipped_senders_and_the_shipped_readers(self) -> None:
        from openstategraph.prebuilt_email import EmailSendTool
        from openstategraph.prebuilt_mcp import McpTool
        from openstategraph.prebuilt_sql import SqlQueryTool
        from openstategraph.prebuilt_web import WebFetchTool

        assert acts_outside_the_run(EmailSendTool())
        # A stranger's server, whose tools are discovered at bind time and
        # could be anything. The strongest case for the conservative default:
        # nothing here can know, so nothing here may guess "read-only".
        assert McpTool.side_effecting is True
        assert not acts_outside_the_run(SqlQueryTool())
        assert not acts_outside_the_run(WebFetchTool())


# ------------------------------------------------------------------ #
# The two mechanisms, alone
# ------------------------------------------------------------------ #


def _plan(document: dict[str, Any]) -> Any:
    return WorkflowCompiler().plan(document)


class TestWhatCountsAsRunningItAgain:
    def test_the_graph_wide_default_is_more_than_one_attempt(self) -> None:
        assert DEFAULT_MAX_ATTEMPTS > 1
        assert max_attempts({}) == DEFAULT_MAX_ATTEMPTS
        assert max_attempts({"maxRetries": ""}) == DEFAULT_MAX_ATTEMPTS

    def test_the_off_switch_is_the_cards_own_field(self) -> None:
        """`maxRetries` on the node's card is what `_node_overrides` turns into
        a per-node `RetryPolicy`, and LangGraph's rule is that a per-node value
        wins over `set_node_defaults`. So it is a real fix, and the finding has
        to stop when it is applied — otherwise it is advice nobody can take."""
        assert max_attempts({"maxRetries": "1"}) == 1
        assert max_attempts({"maxRetries": 5}) == 5

    def test_a_node_with_no_way_back_to_itself(self) -> None:
        assert not reaches_itself("a1", _plan(_straight_line()))

    def test_a_node_a_grader_routes_back_to(self) -> None:
        assert reaches_itself("a1", _plan(_loop(tool_type="tool.email-send")))

    def test_the_clause_names_the_mechanism_that_applies(self) -> None:
        assert "3" in repetition_clause(3, cyclic=False)
        assert "leads back" in repetition_clause(1, cyclic=True)
        both = repetition_clause(3, cyclic=True)
        assert "3" in both and "leads back" in both
        # One attempt and no cycle is a node that runs once. Nothing to say.
        assert repetition_clause(1, cyclic=False) == ""

    def test_upstream_is_transitive_and_survives_a_cycle(self) -> None:
        found = upstream_of("gate1", _plan(_support_triage_shape()))
        assert {"grader1", "router1", "a1", "in1"} <= found
        assert "gate1" not in found


# ------------------------------------------------------------------ #
# Documents
# ------------------------------------------------------------------ #


def _agent(node_id: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": "agent.llm", "data": {"systemPrompt": "Answer.", **data}}


def _wire(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _straight_line(tool_type: str = "tool.email-send") -> dict[str, Any]:
    """in -> agent -> out, with one capability on the agent's `tools` bus."""
    return {
        "version": 2,
        "name": "straight",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            _agent("a1"),
            {"id": "t1", "type": tool_type, "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            _wire("in1", "text", "a1", "prompt"),
            _wire("t1", "tool", "a1", "tools"),
            _wire("a1", "result", "out1", "result"),
        ],
    }


def _loop(*, tool_type: str, **agent_data: Any) -> dict[str, Any]:
    """The evaluator-optimizer shape: a grader routes `revise` back to the
    agent, which is a cycle the agent is inside."""
    return {
        "version": 2,
        "name": "loop",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            _agent("a1", **agent_data),
            {"id": "t1", "type": tool_type, "data": {}},
            {"id": "g1", "type": "route.grader", "data": {"criteria": "- Be right."}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            _wire("in1", "text", "a1", "prompt"),
            _wire("t1", "tool", "a1", "tools"),
            _wire("a1", "result", "g1", "candidate"),
            _wire("g1", "revise", "a1", "feedback"),
            _wire("g1", "pass", "out1", "result"),
        ],
    }


def _support_triage_shape() -> dict[str, Any]:
    """`workflows/support-triage`, reduced to the three facts that matter: a
    send capability on an agent, a revision loop the agent is inside, and an
    approval gate below all of it."""
    return {
        "version": 2,
        "name": "triage",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {
                "id": "router1",
                "type": "route.classifier",
                "data": {
                    "branches": [{"id": "b-account", "name": "account"}],
                    "fallback": "account",
                    "rules": "account: everything.",
                },
            },
            _agent("a1"),
            {"id": "mail1", "type": "tool.email-send", "data": {"to": "c@example.com"}},
            {"id": "grader1", "type": "route.grader", "data": {"criteria": "- Be right."}},
            {
                "id": "gate1",
                "type": "human.approval",
                "data": {"message": "This reply goes to a customer. Approve to send it."},
            },
            {"id": "out-sent", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            _wire("in1", "text", "router1", "question"),
            _wire("router1", "branch:b-account", "a1", "prompt"),
            _wire("mail1", "tool", "a1", "tools"),
            _wire("a1", "result", "grader1", "candidate"),
            _wire("grader1", "revise", "router1", "feedback"),
            _wire("grader1", "pass", "gate1", "candidate"),
            _wire("gate1", "approved", "out-sent", "result"),
        ],
    }


def _build(tmp_path: Any, document: dict[str, Any], node_id: str) -> Any:
    """Build one node's step through the real runtime and hand back the
    diagnostics — the factory, never the helper. A test that only asked
    whether a walk returned True would stay green against a fix wired
    nowhere (`test_a_stale_tool_denial_is_reported`'s rule)."""
    runtime = WorkflowServices(tmp_path).runtime_for(None, document, None, warnings=[])
    plan = WorkflowCompiler().plan(document)
    node = {n["id"]: n for n in document["nodes"]}[node_id]
    runtime.factory(document)(node_id, node, plan)
    return runtime.diagnostics


# ------------------------------------------------------------------ #
# Finding 1 — a capability that acts, re-entered
# ------------------------------------------------------------------ #


class TestTheDeveloperIsToldTheSendCanRepeat:
    def test_retry_alone_is_enough_and_is_named(self, tmp_path: Any) -> None:
        diagnostics = _build(tmp_path, _straight_line(), "a1")
        (subjects,) = diagnostics.subjects(Finding.REPEATED_SIDE_EFFECT)
        assert subjects[0] == "a1"
        assert subjects[1] == "tool.email-send"
        assert "3" in subjects[2]
        assert "leads back" not in subjects[2]

    def test_a_cycle_is_named_as_the_other_mechanism(self, tmp_path: Any) -> None:
        """Both apply on this document, and they have different fixes — so one
        sentence has to carry both rather than the reader guessing which."""
        diagnostics = _build(tmp_path, _loop(tool_type="tool.email-send"), "a1")
        (subjects,) = diagnostics.subjects(Finding.REPEATED_SIDE_EFFECT)
        assert "3" in subjects[2]
        assert "leads back" in subjects[2]

    def test_the_cycle_still_speaks_when_retry_is_turned_off(self, tmp_path: Any) -> None:
        """The trap the ticket names: lowering `maxRetries` is not a fix for
        the loop, and a finding that went quiet here would say it was."""
        diagnostics = _build(
            tmp_path, _loop(tool_type="tool.email-send", maxRetries="1"), "a1"
        )
        (subjects,) = diagnostics.subjects(Finding.REPEATED_SIDE_EFFECT)
        assert subjects[2] == repetition_clause(1, cyclic=True)

    def test_the_sentence_names_the_node_the_capability_and_the_fix(
        self, tmp_path: Any
    ) -> None:
        diagnostics = _build(tmp_path, _straight_line(), "a1")
        sentence = "\n".join(diagnostics.warnings())
        assert '"a1"' in sentence
        assert "tool.email-send" in sentence
        assert "Max retries" in sentence
        assert "side_effecting" in sentence

    def test_three_copies_of_one_capability_say_it_once(self, tmp_path: Any) -> None:
        """`support-triage` wires three `tool.email-send` nodes to one agent.
        Three identical sentences is the noise `absorb`'s slug key was written
        to avoid, reached here by keying the subject on the *type*."""
        document = _straight_line()
        for n in (2, 3):
            document["nodes"].append(
                {"id": f"t{n}", "type": "tool.email-send", "data": {}}
            )
            document["edges"].append(_wire(f"t{n}", "tool", "a1", "tools"))
        diagnostics = _build(tmp_path, document, "a1")
        assert len(diagnostics.subjects(Finding.REPEATED_SIDE_EFFECT)) == 1


class TestTheOrdinaryGraphIsLeftAlone:
    """The half that decides whether anybody reads the other half."""

    def test_a_read_only_capability_inside_a_cycle(self, tmp_path: Any) -> None:
        """The evaluator-optimizer pattern over a database is *the* shape this
        product exists to draw. A warning on it is a warning on everything."""
        diagnostics = _build(tmp_path, _loop(tool_type="tool.sql-query"), "a1")
        assert not diagnostics.any(Finding.REPEATED_SIDE_EFFECT)

    def test_an_agent_with_no_capability_at_all(self, tmp_path: Any) -> None:
        document = _loop(tool_type="tool.sql-query")
        document["nodes"] = [n for n in document["nodes"] if n["id"] != "t1"]
        document["edges"] = [
            e for e in document["edges"] if e["source"]["nodeId"] != "t1"
        ]
        diagnostics = _build(tmp_path, document, "a1")
        assert not diagnostics.any(Finding.REPEATED_SIDE_EFFECT)

    def test_a_send_that_runs_exactly_once(self, tmp_path: Any) -> None:
        """One attempt, no cycle — the arrangement the finding is asking for.
        It has to go quiet, or the advice is not advice."""
        diagnostics = _build(tmp_path, _straight_line_once(), "a1")
        assert not diagnostics.any(Finding.REPEATED_SIDE_EFFECT)

    def test_an_unresolved_capability_is_not_invented(self, tmp_path: Any) -> None:
        """Nothing bound, so nothing can act. `UNRESOLVED_TOOL` already says
        the true thing about this document."""
        diagnostics = _build(tmp_path, _straight_line("tool.not-a-real-thing"), "a1")
        assert not diagnostics.any(Finding.REPEATED_SIDE_EFFECT)


def _straight_line_once() -> dict[str, Any]:
    document = _straight_line()
    for node in document["nodes"]:
        if node["id"] == "a1":
            node["data"]["maxRetries"] = "1"
    return document


# ------------------------------------------------------------------ #
# Finding 2 — a gate that does not gate
# ------------------------------------------------------------------ #


class TestAnApprovalBelowTheAction:
    def test_support_triages_own_shape(self, tmp_path: Any) -> None:
        diagnostics = _build(tmp_path, _support_triage_shape(), "gate1")
        assert diagnostics.subjects(Finding.APPROVAL_COMES_TOO_LATE) == [
            ("gate1", "a1", "tool.email-send")
        ]

    def test_the_sentence_says_what_approving_actually_changes(
        self, tmp_path: Any
    ) -> None:
        diagnostics = _build(tmp_path, _support_triage_shape(), "gate1")
        sentence = "\n".join(diagnostics.warnings())
        assert '"gate1"' in sentence and '"a1"' in sentence
        assert "already" in sentence

    def test_the_gate_above_the_capability_is_the_correct_drawing(
        self, tmp_path: Any
    ) -> None:
        """LangGraph's own advice, at graph scale: *"Place side effects after
        `interrupt` calls"*. A document that took it must go quiet."""
        document = _gate_above_the_send()
        diagnostics = _build(tmp_path, document, "gate1")
        assert not diagnostics.any(Finding.APPROVAL_COMES_TOO_LATE)

    def test_a_read_only_capability_above_a_gate(self, tmp_path: Any) -> None:
        document = _support_triage_shape()
        for node in document["nodes"]:
            if node["id"] == "mail1":
                node["type"] = "tool.sql-query"
        diagnostics = _build(tmp_path, document, "gate1")
        assert not diagnostics.any(Finding.APPROVAL_COMES_TOO_LATE)


def _gate_above_the_send() -> dict[str, Any]:
    """in -> draft -> gate -> sender(with the mail tool) -> out."""
    return {
        "version": 2,
        "name": "gated",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            _agent("draft1", maxRetries="1"),
            {
                "id": "gate1",
                "type": "human.approval",
                "data": {"message": "Approve to send it."},
            },
            _agent("send1", maxRetries="1"),
            {"id": "mail1", "type": "tool.email-send", "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            _wire("in1", "text", "draft1", "prompt"),
            _wire("draft1", "result", "gate1", "candidate"),
            _wire("gate1", "approved", "send1", "prompt"),
            _wire("mail1", "tool", "send1", "tools"),
            _wire("send1", "result", "out1", "result"),
        ],
    }


# ------------------------------------------------------------------ #
# Which side of the exit code
# ------------------------------------------------------------------ #


class TestBothAreReportsAndNotFailures:
    """A conservative guess may not fail somebody's build.

    `UNGUARDED_EXIT` is the nearest failure-side neighbour and the contrast is
    the argument: it is reachable only from an inconsistency the author drew
    **twice** — a policy, and then a path around it — and `workflow-gallery`
    61 settled it with a run that disclosed an address. These two rest on a
    *default* about a tool nobody declared, and an adopter whose read-only
    tool predates the flag would exit 1 on a graph that is correct.
    """

    def test_membership(self) -> None:
        assert Finding.REPEATED_SIDE_EFFECT in REPORT_ONLY
        assert Finding.APPROVAL_COMES_TOO_LATE in REPORT_ONLY

    def test_neither_reaches_failure_warnings(self, tmp_path: Any) -> None:
        diagnostics = _build(tmp_path, _support_triage_shape(), "gate1")
        _build(tmp_path, _support_triage_shape(), "a1")
        assert diagnostics.failure_warnings() == []
        assert diagnostics.warnings() != []

    def test_neither_moves_validate(self, tmp_path: Any) -> None:
        from openstategraph.validation import validate_document

        assert validate_document(_support_triage_shape()) == (True, [])
        assert WorkflowCompiler().plan(_support_triage_shape()).warnings == []
