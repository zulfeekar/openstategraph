"""The curated example, pinned as a document contract.

`.scratch/one-example/tickets/01-one-workflow.md`: `chinook-assistant` is the
worked example the owner asked for — a horizontal text-to-SQL workflow whose
router names five real intents, whose analyst retries until a grader passes,
and in which every node can be explained in one line. Three earlier examples
(`page-analytics`, `chinook-metrics-team`, and a *visible* `chinook-nl-to-sql`)
were deleted or folded in to get there, so these are the tests that stop them
growing back.

**One-chinook ticket 10 finished the job.** `chinook-nl-to-sql` is gone
entirely: the analyst is no longer a mounted package but the `data_query`
branch of this document, and its `tools/`, `data/`, `knowledge/`, `evals/`
and `tests/` moved into the assistant's package. So the pair of assertions
that used to read "the analyst is hidden but loadable" now reads "the analyst
is not a package at all", and the retry-loop tests below read the same node
ids out of the *one* document.

**The count of one is spent; the example it protected is not**
(workflow-gallery ticket 20). This file used to open by asserting that the
listing showed exactly one visible workflow, because when it was written the
catalogue *was* one. The owner ordered twenty permanent examples on
2026-08-14 and batch A landed five, so that assertion stopped describing a
regression and started describing the plan working. It is gone, along with
the note that composition was therefore invisible to a reader — batch C ships
visible mounts on purpose. What replaces a count is a sweep: *every* package
on disk validates and compiles clean, which is the property the count was a
one-package proxy for and which gets stronger, not falser, as the gallery
grows. Everything else here is unchanged and still reads the curated example.

They are document tests, not model tests: every claim here is checkable from
`workflow.json` and the compiled plan, with no provider call, because the
thing being protected is the *shape* a reader sees on the canvas.
"""

from __future__ import annotations

import json
from pathlib import Path

from openstategraph.api.workflow_store import WorkflowStore, validate_package
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.workflows_root import workflows_root

REPO = Path(__file__).resolve().parents[2]

ASSISTANT = "chinook-assistant"

MOUNT_TYPES = ("workflow.subgraph", "team.workflow")


def homes() -> tuple[Path, ...]:
    """Where a shipped package may live — asked, never spelled inline.

    `workflows_root()` is the project's own answer to that question (env →
    config file → checkout → cwd) and is the only home that exists today. The
    other two are the homes gallery ticket 07 is choosing between when the
    examples stop being *staged* in `workflows/` and start shipping in the
    wheel. Searching a directory that does not exist costs one `is_dir()`, and
    it means a relocation that changes nothing this file guards is a one-line
    edit here rather than thirty red assertions.
    """
    return (
        workflows_root(),
        REPO / "examples",
        REPO / "backend" / "openstategraph" / "examples",
    )


def packages() -> list[Path]:
    """Every package directory, in every home, by slug. First home wins."""
    found: dict[str, Path] = {}
    for home in homes():
        if not home.is_dir():
            continue
        for manifest in sorted(home.glob("*/workflow.json")):
            found.setdefault(manifest.parent.name, manifest.parent)
    return [found[slug] for slug in sorted(found)]


def package(slug: str) -> Path:
    for home in homes():
        if (home / slug / "workflow.json").is_file():
            return home / slug
    raise AssertionError(f"no package {slug!r} in any of {[str(h) for h in homes()]}")


def document(slug: str) -> dict:
    return json.loads((package(slug) / "workflow.json").read_text())["document"]


def mounts(doc: dict) -> set[str]:
    return {n["data"]["workflow"] for n in doc["nodes"] if n["type"] in MOUNT_TYPES}


class TestTheCuratedExampleIsStillOnDisk:
    """What the one-example map actually cared about: this example, present,
    complete and coherent. Not how many neighbours it has."""

    def test_the_assistant_is_offered_to_a_customer(self) -> None:
        """Visible, not hidden. It was the whole listing once; now it is the
        row that must never go missing from it."""
        store = WorkflowStore(package(ASSISTANT).parent)
        assert ASSISTANT in [s.slug for s in store.list()]

    def test_the_deleted_examples_stay_deleted(self) -> None:
        for slug in ("page-analytics", "chinook-metrics-team", "chinook-nl-to-sql"):
            for home in homes():
                assert not (home / slug).exists(), f"{slug} came back in {home}"

    def test_there_is_exactly_one_chinook_package(self) -> None:
        """Not a count of the gallery — a count of *Chinooks*. A second one is
        the regression, not because two is many, but because the editor seeded
        the *other* one, which is why the owner spent a map's worth of sessions
        looking at a graph with no router in it. The twenty keep this clear:
        the catalogue's own SQL example is `sql-qa`, over the generic
        `prebuilt_sql` atoms, precisely so it is not a second Chinook."""
        chinook = sorted(p.name for p in packages() if p.name.startswith("chinook"))
        assert chinook == [ASSISTANT]

    def test_the_package_owns_the_database_and_its_tools(self) -> None:
        assistant = package(ASSISTANT)
        assert (assistant / "data" / "Chinook_Sqlite.sqlite").is_file()
        assert (assistant / "tools" / "chinook.py").is_file()
        assert (assistant / "evals" / "chinook.eval.json").is_file()
        assert len(list((assistant / "knowledge").glob("*.md"))) == 11


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
        `AbstractAgentNode.PROMPT.default_rules`, which is the "works with nothing
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
        for pkg in packages():
            assert "criteriaMode" not in (pkg / "workflow.json").read_text(), pkg
        grammar = (package("workflow-architect") / "skills" / "document-grammar.md").read_text()
        assert "rulesMode" in grammar
        assert 'Never emit "criteriaMode"' in grammar


class TestCompositionIsStillDemonstratedSomewhere:
    """The gateway is the composition example, checked rather than assumed.

    Its companion assertion — "no *visible* workflow demonstrates a mount",
    the recorded cost of collapsing to one example — is deleted, not moved.
    Batch C of the gallery ships nested mounts and a package mounted twice
    with different overrides, deliberately visible, so that sentence now
    describes a gap being closed rather than a regression."""

    def test_the_gateway_still_mounts_two_workflows(self) -> None:
        assert mounts(document("concierge")) == {ASSISTANT, "workflow-architect"}


class TestNothingElseStillPointsAtTheDeletedExamples:
    def test_every_mount_names_a_package_that_exists(self) -> None:
        """Was the concierge alone, because the concierge was the only thing
        that mounted. Stated over every package it keeps its original job —
        nothing still points at a deleted example — and picks up a new one:
        a gallery example cannot ship a mount onto a slug nobody wrote."""
        for pkg in packages():
            for slug in mounts(document(pkg.name)):
                assert (pkg.parent / slug / "workflow.json").is_file(), f"{pkg.name} → {slug}"

    def test_the_gateways_knowledge_store_has_no_orphan_docs(self) -> None:
        concierge = package("concierge")
        for doc_path in (concierge / "knowledge").glob("*.md"):
            assert (concierge.parent / doc_path.stem).is_dir(), f"{doc_path.name} routes nowhere"


class TestEveryPackageStandsUpOnItsOwn:
    """What replaces the count of one.

    The old assertion said "the listing is exactly `[chinook-assistant]`",
    which read as a statement about the *catalogue* but was doing duty as a
    statement about *quality*: nothing half-built had been left lying in the
    workflows directory. The catalogue claim is now false by owner decision;
    the quality claim is the one worth keeping, and unlike a count it gets
    harder to satisfy — never easier — as the twenty land."""

    def test_the_sweep_is_not_vacuous(self) -> None:
        found = [p.name for p in packages()]
        assert ASSISTANT in found
        assert len(found) > 1, "the gallery lost its packages, or homes() lost the gallery"

    def test_every_package_satisfies_the_package_contract(self) -> None:
        for pkg in packages():
            errors = [f for f in validate_package(pkg) if f.startswith("error:")]
            assert errors == [], f"{pkg.name}: {errors}"

    def test_every_package_compiles_with_no_warnings(self) -> None:
        """A warning is the compiler saying it could not make sense of
        something a reader can see. An example that ships one teaches it."""
        for pkg in packages():
            plan = WorkflowCompiler().plan(document(pkg.name))
            assert plan.warnings == [], f"{pkg.name}: {plan.warnings}"
            assert plan.entry, f"{pkg.name} has no entry node"
            assert plan.exits, f"{pkg.name} has no exit node"
