"""The one visible example, pinned as a document contract.

`workflows/one-example/01-one-workflow.md`: the catalogue ships **one**
visible workflow — `chinook-assistant` — and everything else on disk is
infrastructure a reader never has to meet (the gateway, the architect). Three
earlier examples (`page-analytics`, `chinook-metrics-team`, and a *visible*
`chinook-nl-to-sql`) were deleted or hidden to get there, so these are the
tests that stop them growing back.

**One-chinook ticket 10 finished the job.** `chinook-nl-to-sql` is gone
entirely: the analyst is no longer a mounted package but the `data_query`
branch of this document, and its `tools/`, `data/`, `knowledge/`, `evals/`
and `tests/` moved into `workflows/chinook-assistant/`. So the pair of
assertions that used to read "the analyst is hidden but loadable" now reads
"the analyst is not a package at all", and the retry-loop tests below read
the same node ids out of the *one* document.

They are document tests, not model tests: every claim here is checkable from
`workflow.json` and the compiled plan, with no provider call, because the
thing being protected is the *shape* a reader sees on the canvas.
"""

from __future__ import annotations

import json
from pathlib import Path

from openstategraph.api.workflow_store import WorkflowStore
from openstategraph.compile.workflow_compiler import WorkflowCompiler

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / "workflows"

ASSISTANT = "chinook-assistant"


def document(slug: str) -> dict:
    return json.loads((WORKFLOWS / slug / "workflow.json").read_text())["document"]


def envelope(slug: str) -> dict:
    return json.loads((WORKFLOWS / slug / "workflow.json").read_text())


class TestExactlyOneVisibleWorkflow:
    """The whole point of the ticket: a catalogue of one."""

    def test_the_listing_shows_the_assistant_and_nothing_else(self) -> None:
        assert [s.slug for s in WorkflowStore(WORKFLOWS).list()] == [ASSISTANT]

    def test_the_deleted_examples_stay_deleted(self) -> None:
        for slug in ("page-analytics", "chinook-metrics-team", "chinook-nl-to-sql"):
            assert not (WORKFLOWS / slug).exists(), f"{slug} came back"

    def test_there_is_exactly_one_chinook_package(self) -> None:
        """The ticket, stated as a directory listing. A second Chinook package
        is the regression — not because two is many, but because the editor
        seeded the *other* one, which is why the owner spent a map's worth of
        sessions looking at a graph with no router in it."""
        chinook = sorted(p.name for p in WORKFLOWS.iterdir() if p.name.startswith("chinook"))
        assert chinook == [ASSISTANT]

    def test_the_one_package_owns_the_database_and_its_tools(self) -> None:
        package = WORKFLOWS / ASSISTANT
        assert (package / "data" / "Chinook_Sqlite.sqlite").is_file()
        assert (package / "tools" / "chinook.py").is_file()
        assert (package / "evals" / "chinook.eval.json").is_file()
        assert len(list((package / "knowledge").glob("*.md"))) == 11


class TestTheRouterIsTheDiagram:
    """Five intents, and each branch lands somewhere a reader can name."""

    def test_it_routes_the_five_intents_the_owner_asked_for(self) -> None:
        router = next(n for n in document(ASSISTANT)["nodes"] if n["type"] == "route.classifier")
        assert [b["name"] for b in router["data"]["branches"]] == [
            "data_query",
            "greeting",
            "off_topic",
            "general_knowledge",
            "web_lookup",
        ]

    def test_there_is_no_follow_up_branch(self) -> None:
        """Ticket 11's finding, pinned so it is not re-added on the next report
        of the symptom. The follow-up defect was a missing `thread_id`, not a
        missing branch, and a `follow_up` branch would need a destination able
        to answer any prior intent — a node with no honest job."""
        router = next(n for n in document(ASSISTANT)["nodes"] if n["type"] == "route.classifier")
        assert "follow_up" not in {b["name"] for b in router["data"]["branches"]}

    def test_every_branch_reaches_one_of_three_destinations(self) -> None:
        doc = document(ASSISTANT)
        plan = WorkflowCompiler().plan(doc)
        by_id = {n["id"]: n for n in doc["nodes"]}
        destinations = plan.conditional["router1"]
        assert destinations == {
            "b-data": "agent-sql",
            "b-greeting": "agent-chat",
            "b-offtopic": "agent-chat",
            "b-general": "agent-chat",
            "b-web": "agent-web",
        }
        # …and the three destinations are the three kinds of answer this
        # example exists to show: query it, converse, look it up. Before
        # ticket 10 the first was a `workflow.subgraph` onto a second package;
        # it is the same agent, now inline.
        assert by_id["agent-sql"]["type"] == "agent.llm"
        assert by_id["agent-chat"]["type"] == "agent.llm"
        assert by_id["agent-web"]["type"] == "agent.llm"

    def test_the_rules_name_all_five_intents_so_the_card_reads(self) -> None:
        router = next(n for n in document(ASSISTANT)["nodes"] if n["type"] == "route.classifier")
        rules = router["data"]["rules"]
        for intent in ("data_query", "greeting", "off_topic", "general_knowledge", "web_lookup"):
            assert intent in rules

    def test_it_compiles_clean(self) -> None:
        plan = WorkflowCompiler().plan(document(ASSISTANT))
        assert plan.warnings == []
        assert plan.entry == ["in1"] and plan.exits == ["out1"]


class TestNoNodeIsUnexplainable:
    """ "Every node must earn its place" as an executable ceiling."""

    def test_the_visible_example_is_thirteen_nodes(self) -> None:
        doc = document(ASSISTANT)
        assert sorted(n["id"] for n in doc["nodes"]) == [
            "agent-chat",
            "agent-sql",
            "agent-web",
            "grader-sql",
            "in1",
            "out1",
            "router1",
            "skill-sql",
            "t-fetch",
            "t-search",
            "tool-schema",
            "tool-sql",
            "tool-tables",
        ]

    def test_nothing_is_mounted_any_more(self) -> None:
        """The ticket's headline, and its accepted cost: one document, and no
        *visible* example of composition. `concierge` still mounts, which
        `TestCompositionIsStillDemonstratedSomewhere` below checks."""
        types = {n["type"] for n in document(ASSISTANT)["nodes"]}
        assert "workflow.subgraph" not in types
        assert "team.workflow" not in types

    def test_there_is_no_supervisor_anywhere_in_the_example(self) -> None:
        """The Team-vs-Workflow decision, pinned: one worker role does not
        buy a planner. A supervisor reappearing here is the regression."""
        types = {n["type"] for n in document(ASSISTANT)["nodes"]}
        assert "orchestrate.supervisor" not in types
        assert "orchestrate.worker" not in types

    def test_each_agent_holds_only_the_tools_its_branch_needs(self) -> None:
        doc = document(ASSISTANT)
        plan = WorkflowCompiler().plan(doc)
        by_id = {n["id"]: n for n in doc["nodes"]}
        assert set(plan.tool_bindings) == {"agent-sql", "agent-web"}
        assert {by_id[t]["type"] for t in plan.tool_bindings["agent-web"]} == {
            "tool.web-search",
            "tool.web-fetch",
        }
        assert {by_id[t]["type"] for t in plan.tool_bindings["agent-sql"]} == {
            "tool.chinook-get-all-tables",
            "tool.chinook-get-schema",
            "tool.chinook-execute-sql",
        }
        # The Front Desk holds nothing, which is what makes "never invent a
        # figure" enforceable rather than hopeful.
        assert "agent-chat" not in plan.tool_bindings


class TestTheAnalystIsTheRetryLoop:
    """Owner item (3): a data scientist, a grader that verifies, a retry —
    now inline rather than behind a mount."""

    def test_the_grader_passes_forward_and_revises_backward(self) -> None:
        plan = WorkflowCompiler().plan(document(ASSISTANT))
        assert plan.conditional["grader-sql"] == {"pass": "out1", "revise": "agent-sql"}

    def test_the_loop_is_bounded(self) -> None:
        grader = next(n for n in document(ASSISTANT)["nodes"] if n["type"] == "route.grader")
        assert int(grader["data"]["maxAttempts"]) >= 2

    def test_formatting_is_the_output_node_not_a_report_join(self) -> None:
        """`function.format_report` reads `worker_results`, which a graph with
        no orchestrator never writes — dropping one in after the grader would
        have replaced the answer with "_No results._". The Markdown output
        node is the format step."""
        types = {n["type"] for n in document(ASSISTANT)["nodes"]}
        assert "function.format_report" not in types
        assert "output.formatted" in types


class TestTheRulesLayersAreWhereTheDocumentSaysTheyAre:
    """Ticket 06's bar, absorbed into 10: the example's domain prose lives in
    a wired skill file, and a node with no skill wired still works."""

    def test_the_analysts_rules_arrive_over_the_skill_port(self) -> None:
        doc = document(ASSISTANT)
        by_id = {n["id"]: n for n in doc["nodes"]}
        assert by_id["skill-sql"]["type"] == "input.markdown"
        wired = {
            (e["source"]["nodeId"], e["source"]["portId"], e["target"]["portId"])
            for e in doc["edges"]
            if e["target"]["nodeId"] == "agent-sql"
        }
        assert ("skill-sql", "skill", "skill") in wired

    def test_the_analyst_carries_no_inline_prompt_of_its_own(self) -> None:
        """The proof that the skill layer is load-bearing. It is also the
        proof in the other direction: unwire it and the agent falls back to
        `AbstractAgentNode.DEFAULT_RULES`, which is the "works with nothing
        configured" bar the owner set."""
        analyst = next(n for n in document(ASSISTANT)["nodes"] if n["id"] == "agent-sql")
        assert not str(analyst["data"].get("systemPrompt", "")).strip()

    def test_the_skill_body_is_the_sql_procedure(self) -> None:
        skill = next(n for n in document(ASSISTANT)["nodes"] if n["id"] == "skill-sql")
        body = skill["data"]["instruction"]
        assert skill["data"]["filename"].endswith(".md")
        for token in ("chinook_list_tables", "chinook_get_table_schema", "chinook_execute_sql"):
            assert token in body

    def test_no_shipped_document_still_spells_the_mode_criteriamode(self) -> None:
        """The deprecated spelling, swept. Left in place it would ride into
        every workflow the Architect generates, because its grammar file
        taught the model to emit it."""
        for path in WORKFLOWS.rglob("workflow.json"):
            assert "criteriaMode" not in path.read_text(), path
        grammar = (WORKFLOWS / "workflow-architect" / "skills" / "document-grammar.md").read_text()
        assert "rulesMode" in grammar
        assert 'Never emit "criteriaMode"' in grammar


class TestCompositionIsStillDemonstratedSomewhere:
    """The accepted cost of the collapse, checked rather than assumed."""

    def test_the_gateway_still_mounts_two_workflows(self) -> None:
        doc = document("concierge")
        mounts = {
            n["data"]["workflow"]
            for n in doc["nodes"]
            if n["type"] in ("workflow.subgraph", "team.workflow")
        }
        assert mounts == {ASSISTANT, "workflow-architect"}

    def test_no_visible_workflow_demonstrates_a_mount(self) -> None:
        """Stated as a test so nobody has to rediscover it. Every mount this
        repository ships now sits inside a `hidden: true` package, so a reader
        who opens only the visible example never meets composition. That is
        the recorded cost of the collapse, not an oversight."""
        for slug in (s.slug for s in WorkflowStore(WORKFLOWS).list()):
            types = {n["type"] for n in document(slug)["nodes"]}
            assert not types & {"workflow.subgraph", "team.workflow"}


class TestNothingElseStillPointsAtTheDeletedExamples:
    def test_the_concierge_routes_to_packages_that_exist(self) -> None:
        doc = document("concierge")
        for node in doc["nodes"]:
            if node["type"] in ("workflow.subgraph", "team.workflow"):
                slug = node["data"]["workflow"]
                assert (WORKFLOWS / slug / "workflow.json").is_file(), slug

    def test_the_gateways_knowledge_store_has_no_orphan_docs(self) -> None:
        for doc_path in (WORKFLOWS / "concierge" / "knowledge").glob("*.md"):
            assert (WORKFLOWS / doc_path.stem).is_dir(), f"{doc_path.name} routes nowhere"
