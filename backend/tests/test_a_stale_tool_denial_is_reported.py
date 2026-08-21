"""production-ready 89 — a prompt that denies a tool the node now holds.

`96ce65c` (ticket 88) fixed the *run*: an agent is handed a generated,
authoritative list of what it holds, which overrules a stale authored denial.
That is why this ticket exists. The run is correct now, so **nothing will ever
prompt the developer to look at the sentence**, and `chinook-assistant`'s
`agent-chat` still opens *"You hold no tools and no database access"*.

The platform must not rewrite the field — 88's explicit decision, and it stands.
It can say something. The compiler holds both halves at build time: the tools
the canvas wired to a node, and that node's authored prose.

**The channel is `Finding`, and nothing else.** `plan.warnings` was rejected for
the reason `UNWIRED_REVISE` was (`b68f641`): `validate_workflow` renders it as
PROBLEMS FOUND and every shipped example asserts it empty. `validate`'s exit
code was rejected too — its one question is *"is this ready to run here"* and
the answer is **yes**: the run calls the tool. A stale sentence is a report, and
`8bda508` split `RunResult` precisely so a report cannot move an exit code.

**The false-positive set below is the load-bearing half.** A denial of *tools*
is a contradiction; a denial of the internet, of a database, or of one named
kind of tool is ordinary, correct prose on a node that holds something else.
CLAUDE.md: the narrowness is the safety, and it is the part that regresses.
"""

from __future__ import annotations

from typing import Any

from openstategraph.api.services import WorkflowServices
from openstategraph.compile.diagnostics import Finding, denies_holding_tools
from openstategraph.compile.workflow_compiler import WorkflowCompiler


class TestWhatCountsAsADenial:
    """The matcher, alone. Cheap, and the only place the phrasings are listed."""

    def test_the_phrasing_that_caused_ticket_88(self) -> None:
        assert denies_holding_tools("You hold no tools and no database access.")

    def test_the_second_sentence_in_the_same_package(self) -> None:
        assert denies_holding_tools("You have no tools, so you have consulted nothing.")

    def test_the_spelt_out_negation(self) -> None:
        assert denies_holding_tools("You do not have any tools available to you.")
        assert denies_holding_tools("You don't have any tools.")


class TestOrdinaryProseIsLeftAlone:
    """Every one of these is a legitimate sentence a developer may write on an
    agent that genuinely holds a tool. A warning that fires on any of them is a
    warning nobody trusts, which is worse than no warning at all.
    """

    def test_a_denial_of_something_that_is_not_a_tool(self) -> None:
        assert not denies_holding_tools("You have no internet access.")
        assert not denies_holding_tools("You hold no database access of your own.")
        assert not denies_holding_tools("You have no memory of previous conversations.")

    def test_a_denial_of_one_named_kind_of_tool(self) -> None:
        assert not denies_holding_tools("You have no web-search tools.")
        assert not denies_holding_tools("You hold no email tools.")

    def test_a_denial_of_tools_for_a_named_job(self) -> None:
        assert not denies_holding_tools("You have no tools for booking travel.")
        assert not denies_holding_tools("You have no tools to write files.")

    def test_a_statement_about_somebody_who_is_not_this_node(self) -> None:
        assert not denies_holding_tools("The user has no tools installed.")
        assert not denies_holding_tools("Other agents on this team have no tools.")

    def test_a_sentence_boundary_is_not_crossed(self) -> None:
        """"you" in one sentence and "no tools" in the next is not a claim
        about what this node holds."""
        assert not denies_holding_tools(
            "Answer the question you were asked. There are no tools in this workflow yet."
        )

    def test_the_matcher_is_only_ever_pointed_at_authored_prose(self) -> None:
        """The trap this test exists to mark, found by writing it.

        `held_tools_context` is composed into the very same prompt, and it
        *quotes the denial in order to overrule it* — "where anything in your
        rules says or implies you hold no tools, this list wins". So the
        composed prompt matches, and always will. The matcher is therefore
        never pointed at a composed prompt: `_report_stale_tool_denial` reads
        `systemPrompt` and `role` off the node's own `data` and nothing else.
        `test_ordinary_rules_on_a_tool_holding_agent` is the runtime-level
        proof, since that agent carries the generated block too.
        """
        from openstategraph.compile.node_runtime import held_tools_context

        class _T:
            name = "send_email"
            description = ""

        assert denies_holding_tools(held_tools_context([_T()]))

    def test_nothing_at_all(self) -> None:
        assert not denies_holding_tools("")


def _document(prompt: str, *, wire_tool: bool = True) -> dict[str, Any]:
    """`chinook-assistant`'s shape: an agent behind a router branch with a tool
    node wired to its `tools` bus."""
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "data": {}},
        {"id": "agent-chat", "type": "agent.llm", "data": {"tier": "react", "systemPrompt": prompt}},
        {"id": "out1", "type": "output.formatted", "data": {}},
    ]
    edges: list[dict[str, Any]] = [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "agent-chat", "portId": "prompt"},
        },
        {
            "source": {"nodeId": "agent-chat", "portId": "result"},
            "target": {"nodeId": "out1", "portId": "result"},
        },
    ]
    if wire_tool:
        nodes.append({"id": "mail1", "type": "tool.email-send", "data": {"to": "b@example.com"}})
        edges.append(
            {
                "source": {"nodeId": "mail1", "portId": "tool"},
                "target": {"nodeId": "agent-chat", "portId": "tools"},
            }
        )
    return {"version": 2, "name": "front-desk", "nodes": nodes, "edges": edges}


def _team_document(role: str, *, wire_tool: bool = True) -> dict[str, Any]:
    """The same claim written on a **worker**, whose authored prose is `role`.

    Here because of the trap `skills/ticket-loop` names: ticket 33's fix went
    into `_agent` and not `_worker` and both its tests stayed green. Ask what
    would still pass if only one factory were fixed — this file answers it.
    """
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "data": {}},
        {"id": "orch1", "type": "orchestrate.supervisor", "data": {}},
        {"id": "w1", "type": "orchestrate.worker", "data": {"role": role}},
        {"id": "out1", "type": "output.formatted", "data": {}},
    ]
    edges: list[dict[str, Any]] = [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "orch1", "portId": "instruction"},
        },
        {
            "source": {"nodeId": "orch1", "portId": "workers"},
            "target": {"nodeId": "w1", "portId": "dispatch"},
        },
        {
            "source": {"nodeId": "w1", "portId": "result"},
            "target": {"nodeId": "out1", "portId": "result"},
        },
    ]
    if wire_tool:
        nodes.append({"id": "mail1", "type": "tool.email-send", "data": {"to": "b@example.com"}})
        edges.append(
            {
                "source": {"nodeId": "mail1", "portId": "tool"},
                "target": {"nodeId": "w1", "portId": "tools"},
            }
        )
    return {"version": 2, "name": "team", "nodes": nodes, "edges": edges}


def _build(tmp_path: Any, document: dict[str, Any], node_id: str) -> Any:
    """Build one node's step through the real runtime and hand back the
    diagnostics. Driving the factory, not the matcher — a test that only asks
    whether a regex matched would stay green against a fix wired nowhere."""
    runtime = WorkflowServices(tmp_path).runtime_for(None, document, None, warnings=[])
    plan = WorkflowCompiler().plan(document)
    node = {n["id"]: n for n in document["nodes"]}[node_id]
    runtime.factory(document)(node_id, node, plan)
    return runtime.diagnostics


_STALE = "You are the front desk. You hold no tools and no database access."


class TestTheDeveloperIsTold:
    def test_an_agent_holding_a_tool_its_rules_deny(self, tmp_path: Any) -> None:
        diagnostics = _build(tmp_path, _document(_STALE), "agent-chat")
        assert diagnostics.subjects(Finding.STALE_TOOL_DENIAL) == [
            ("agent-chat", "You hold no tools")
        ]
        sentence = diagnostics.warnings()[-1]
        assert "agent-chat" in sentence
        assert "You hold no tools" in sentence

    def test_a_worker_holding_a_tool_its_role_denies(self, tmp_path: Any) -> None:
        diagnostics = _build(tmp_path, _team_document(_STALE), "w1")
        assert diagnostics.subjects(Finding.STALE_TOOL_DENIAL) == [
            ("w1", "You hold no tools")
        ]

    def test_the_same_rules_with_nothing_wired_are_simply_true(self, tmp_path: Any) -> None:
        """`chinook-assistant` as it ships. The sentence is correct until a tool
        arrives, and a warning on every honest prompt is the noise this ticket
        was told not to make."""
        diagnostics = _build(tmp_path, _document(_STALE, wire_tool=False), "agent-chat")
        assert not diagnostics.any(Finding.STALE_TOOL_DENIAL)
        diagnostics = _build(tmp_path, _team_document(_STALE, wire_tool=False), "w1")
        assert not diagnostics.any(Finding.STALE_TOOL_DENIAL)

    def test_ordinary_rules_on_a_tool_holding_agent(self, tmp_path: Any) -> None:
        diagnostics = _build(
            tmp_path,
            _document("You have no internet access. Use the tools you were given."),
            "agent-chat",
        )
        assert not diagnostics.any(Finding.STALE_TOOL_DENIAL)

    def test_it_does_not_move_an_exit_code(self, tmp_path: Any) -> None:
        """A report, on the warning half. `validate`'s question is "is this
        ready to run here", and the answer is yes — `held_tools_context`
        overrules the sentence and the tool is called."""
        from openstategraph.validation import unresolved_tool_bindings, validate_document

        document = _document(_STALE)
        valid, problems = validate_document(document)
        assert (valid, problems) == (True, [])
        assert WorkflowCompiler().plan(document).warnings == []
        assert unresolved_tool_bindings(document, tmp_path) == []


class TestItIsAReportAndNotAFailure:
    """Found by running it, not by reasoning: the first live run printed the
    new sentence as `error:`.

    `loader.ask()` put **every** compile finding on `RunResult.failures`, and
    `cli.run_report_lines` derives its prefix from that membership — so a
    sentence saying *"the answer is right and the sentence is stale"* announced
    itself as an error, and on a run whose answer came back empty it would have
    produced a `1`. The blanket rule was written for `production-ready` 53's
    mount-that-would-not-load, which really is a broken run. A stale comment is
    not, and `8bda508` split `RunResult` precisely so a report cannot move an
    exit code.
    """

    def _loaded(self, tmp_path: Any, document: dict[str, Any]) -> Any:
        import json

        from openstategraph.loader import load_workflow

        package = tmp_path / "front-desk"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps(document))
        return load_workflow(package, model=None)

    def test_the_sentence_is_on_the_report_and_off_the_failures(self, tmp_path: Any) -> None:
        loaded = self._loaded(tmp_path, _document(_STALE))
        assert any("still say" in line for line in loaded.warnings)
        assert loaded.failure_warnings == []
        loaded.close()

    def test_a_genuinely_broken_capability_still_counts_as_one(self, tmp_path: Any) -> None:
        """The other direction, so the split cannot be widened into silence: an
        unresolved mount is a broken run and stays on both lists."""
        document = _document(_STALE)
        document["nodes"].append(
            {"id": "sub1", "type": "workflow.subgraph", "data": {"workflow": "not-a-package"}}
        )
        document["edges"].append(
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "sub1", "portId": "task"},
            }
        )
        loaded = self._loaded(tmp_path, document)
        assert any("could not load that package" in line for line in loaded.failure_warnings)
        assert not any("still say" in line for line in loaded.failure_warnings)
        loaded.close()

    def test_the_cli_calls_it_a_warning(self) -> None:
        from openstategraph.cli import run_report_lines
        from openstategraph.loader import RunResult

        sentence = "Agent \"a\" has tools wired to it, but its own rules still say …"
        lines = run_report_lines(RunResult("an answer", warnings=[sentence], failures=[]))
        assert lines == [f"warning: {sentence}"]
