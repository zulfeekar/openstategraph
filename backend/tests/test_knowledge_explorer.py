"""The instructed explorer — the escalation ladder's bounded fallback.

Scripted models only (no live LLM): what is pinned is the wiring — which
sources qualify, that the write seam is the only write path, that the budget
holds and the instruction reaches the prompt. Whether a real model writes
good docs is a model evaluation, not a unit test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from openstategraph import prebuilt_mcp
from openstategraph.prebuilt_mcp import KEY_SERVER

from openstategraph.api.knowledge_build import run_build
from openstategraph.knowledge_builders import (
    BUILDERS,
    GENERATED_MARKER,
    marker_source,
)
from tests.test_prebuilt_mcp import fake_discovery, failing_discovery
from openstategraph.knowledge_explorer import (
    EXPLORER_TOPIC_CAP,
    AgenticKnowledgeBuilder,
    ExplorationReport,
    ExplorerKnowledgeBuilder,
    WriteTopicTool,
)


class ToolCallingScriptedModel(GenericFakeChatModel):
    """A fake chat model that can be bound to tools and answers a script of
    AIMessages — tool calls included — so `create_agent`'s real loop runs
    with no provider."""

    def __init__(self, messages: list[AIMessage]):
        super().__init__(messages=iter(messages))

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return self


def _save_workflow(root: Path, slug: str, document: dict[str, Any]) -> Path:
    package = root / slug
    package.mkdir(parents=True, exist_ok=True)
    (package / "workflow.json").write_text(json.dumps({"version": 1, "document": document}))
    return package


class TestQualification:
    """Discovery fires only on resolvable, plausibly-data-access tools."""

    def _tools_for(self, tmp_path: Path, node_types: list[str]) -> list[Any]:
        document = {
            "nodes": [
                {"id": f"n{i}", "type": t, "data": {}} for i, t in enumerate(node_types)
            ],
            "edges": [],
        }
        package = _save_workflow(tmp_path, "probe-flow", document)
        tools, _prov, _warn = ExplorerKnowledgeBuilder().study_tools(
            package, document, tmp_path
        )
        return tools

    def test_sql_email_knowledge_platform_and_architect_tools_never_qualify(
        self, tmp_path: Path
    ) -> None:
        tools = self._tools_for(
            tmp_path,
            [
                "tool.sql-query",
                "tool.chinook-execute-sql",
                "tool.email-send",
                "tool.knowledge-lookup",
                "tool.platform-ls",
                "tool.validate-workflow",
            ],
        )
        assert tools == []

    def test_web_tools_qualify_and_unresolvable_types_are_skipped(
        self, tmp_path: Path
    ) -> None:
        tools = self._tools_for(
            tmp_path, ["tool.web-search", "tool.imaginary-source", "tool.web-search"]
        )
        assert [t.name for t in tools] == ["web_search"]  # resolvable, deduped

    def test_no_qualifying_tools_means_the_exploration_never_starts(
        self, tmp_path: Path
    ) -> None:
        document = {"nodes": [{"id": "a", "type": "tool.sql-query", "data": {}}], "edges": []}
        package = _save_workflow(tmp_path, "sql-only", document)

        class ExplodingModel:
            def invoke(self, *_a: Any, **_k: Any) -> Any:
                raise AssertionError("the model must not be called with nothing to study")

        report = ExplorerKnowledgeBuilder().explore(package, document, tmp_path, ExplodingModel())
        assert not report.touched


class TestWriteSeam:
    """Invariant 1: the agent's one write capability is the store seam.

    Every tool here is built with a provenance, because since
    `production-ready` 12 a write with none is refused before any of these
    guards is reached — see `TestGrounding`. `GROUNDED` stands for "this
    exploration called something", which is the precondition each of these
    cases is varying *around*.
    """

    GROUNDED = staticmethod(lambda: ("tool web_search",))

    def test_write_topic_writes_a_marked_doc_with_the_explorer_as_owner(
        self, tmp_path: Path
    ) -> None:
        report = ExplorationReport()
        tool = WriteTopicTool(
            ExplorerKnowledgeBuilder(), tmp_path / "flow", report, provenance=self.GROUNDED
        )
        result = tool.run(topic="Weather API", content="weather-api — how to call it.")
        assert result.ok
        text = (tmp_path / "flow" / "knowledge" / "weather-api.md").read_text()
        assert text.startswith(GENERATED_MARKER)
        assert marker_source(text) == "explorer"
        assert report.written == ["weather-api"]

    def test_a_studied_tool_cannot_itself_become_the_topic(self, tmp_path: Path) -> None:
        """production-ready ticket 10, found live.

        A manual build on `concierge` produced `web-search-tool.md` — a
        document about *OpenAI's* Responses-API `web_search`, with an invented
        model name and invented limits, while the tool this repo wires is a
        keyless DuckDuckGo endpoint. Nothing was called; it was written from
        parametric memory and handed to agents as fact.

        The rule that catches it is narrow on purpose: a tool is a way to
        *reach* a corpus, never a corpus itself. Studying `web_search` can
        legitimately produce a topic about the workflow's domain — it must
        never produce a topic about `web_search`.
        """
        report = ExplorationReport()
        tool = WriteTopicTool(
            ExplorerKnowledgeBuilder(), tmp_path / "flow", report,
            provenance=lambda: ("tool web_search", "tool web_fetch"),
        )
        for topic in ("web-search-tool", "Web Search", "web_search", "web-fetch-api"):
            result = tool.run(topic=topic, content=f"{topic} — vendor docs.")
            assert not result.ok, f"{topic} should be refused"
            assert "not a topic" in str(result.error)
        assert report.written == []

    def test_the_domain_behind_a_studied_tool_is_still_writable(
        self, tmp_path: Path
    ) -> None:
        # The guard must not cost the explorer its actual job: a web tool used
        # to research a domain is exactly what it is for.
        report = ExplorationReport()
        tool = WriteTopicTool(
            ExplorerKnowledgeBuilder(), tmp_path / "flow", report,
            provenance=lambda: ("tool web_search",),
        )
        assert tool.run(topic="uk-vat-rates", content="uk-vat-rates — 20% standard.").ok
        assert report.written == ["uk-vat-rates"]

    def test_a_topic_owned_by_the_sql_builder_is_refused(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "flow" / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "orders.md").write_text(f"{GENERATED_MARKER} source=sql -->\nsql's doc\n")
        report = ExplorationReport()
        tool = WriteTopicTool(
            ExplorerKnowledgeBuilder(), tmp_path / "flow", report, provenance=self.GROUNDED
        )
        result = tool.run(topic="orders", content="orders — mine now.")
        assert not result.ok and "owned by the 'sql' builder" in str(result.error)
        assert report.collisions and "sql" in report.collisions[0]
        assert "sql's doc" in (knowledge / "orders.md").read_text()  # never last-write-wins

    def test_a_hand_authored_doc_is_refused_and_reported_skipped(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "flow" / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "wisdom.md").write_text("# wisdom\nhand-written\n")
        report = ExplorationReport()
        tool = WriteTopicTool(
            ExplorerKnowledgeBuilder(), tmp_path / "flow", report, provenance=self.GROUNDED
        )
        result = tool.run(topic="wisdom", content="wisdom — overwrite attempt.")
        assert not result.ok
        assert report.skipped == ["wisdom"]
        assert "hand-written" in (knowledge / "wisdom.md").read_text()

    def test_the_topic_budget_is_honored(self, tmp_path: Path) -> None:
        report = ExplorationReport()
        tool = WriteTopicTool(
            ExplorerKnowledgeBuilder(), tmp_path / "flow", report, topic_cap=2,
            provenance=self.GROUNDED,
        )
        assert tool.run(topic="one", content="one — a.").ok
        assert tool.run(topic="two", content="two — b.").ok
        third = tool.run(topic="three", content="three — c.")
        assert not third.ok and "budget" in str(third.error).lower()
        assert report.written == ["one", "two"]
        assert not (tmp_path / "flow" / "knowledge" / "three.md").exists()

    def test_a_traversal_shaped_topic_cannot_escape_the_jail(self, tmp_path: Path) -> None:
        report = ExplorationReport()
        tool = WriteTopicTool(
            ExplorerKnowledgeBuilder(), tmp_path / "flow", report, provenance=self.GROUNDED
        )
        result = tool.run(topic="../../evil", content="evil — nope.")
        # normalization turns separators into hyphens; the write stays inside
        assert result.ok
        assert (tmp_path / "flow" / "knowledge" / "evil.md").is_file()
        assert not (tmp_path / "evil.md").exists()


class TestPromptComposition:
    def test_the_instruction_reaches_the_prompt_between_context_and_contract(self) -> None:
        builder = ExplorerKnowledgeBuilder()
        prompt = builder.explorer_prompt(["web_search"], "focus on billing; fiscal year starts April")
        assert "focus on billing" in prompt
        assert "web_search" in prompt
        # the output contract stays LAST so it wins ties
        assert prompt.index("focus on billing") < prompt.index("did NOT cover")
        assert str(EXPLORER_TOPIC_CAP) in prompt

    def test_no_instruction_means_no_instruction_block(self) -> None:
        prompt = ExplorerKnowledgeBuilder().explorer_prompt(["web_search"], None)
        assert "Developer instruction" not in prompt


class TestScriptedLoop:
    """The real `create_agent` loop, driven by a scripted tool-calling model.

    Both scripts here **call the study tool before writing**, and until
    `production-ready` 12 neither did — they wrote a topic having called
    nothing, and asserted the resulting doc carried a provenance footer naming
    `web_search`. That is the fabricated-document shape the ticket is about,
    pinned as correct behaviour by the tests that were supposed to catch it.

    The search call is allowed to fail: `on_call` records the attempt either
    way, so these stay deterministic offline. What they pin is the loop and the
    report, not what a search engine says today.
    """

    def _document(self) -> dict[str, Any]:
        return {"nodes": [{"id": "w", "type": "tool.web-search", "data": {}}], "edges": []}

    def _looked(self) -> AIMessage:
        """The call that earns the write."""
        return AIMessage(
            content="",
            tool_calls=[{"name": "web_search", "args": {"query": "the domain"}, "id": "c-0"}],
        )

    def test_a_scripted_exploration_writes_topics_and_reports_the_uncovered(
        self, tmp_path: Path
    ) -> None:
        package = _save_workflow(tmp_path, "api-flow", self._document())
        model = ToolCallingScriptedModel(
            [
                self._looked(),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_topic",
                            "args": {
                                "topic": "search-source",
                                "content": "search-source — what the search tool answers.",
                            },
                            "id": "call-1",
                        }
                    ],
                ),
                AIMessage(content="NOT covered: rate limits and pagination."),
            ]
        )
        report = ExplorerKnowledgeBuilder().explore(package, self._document(), tmp_path, model)
        assert report.written == ["search-source"]
        assert report.uncovered == ["NOT covered: rate limits and pagination."]
        doc = (package / "knowledge" / "search-source.md").read_text()
        assert marker_source(doc) == "explorer"
        assert "Provenance" in doc and "web_search" in doc

    def test_run_build_folds_the_exploration_into_the_report(self, tmp_path: Path) -> None:
        package = _save_workflow(tmp_path, "api-flow", self._document())
        model = ToolCallingScriptedModel(
            [
                self._looked(),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_topic",
                            "args": {"topic": "search-source", "content": "search-source — s."},
                            "id": "call-1",
                        }
                    ],
                ),
                AIMessage(content="Everything covered."),
            ]
        )
        report = run_build(package, self._document(), model, tmp_path, source="explorer")
        assert report["written"] == ["search-source"]
        assert report["sources"]["explorer"]["uncovered"] == ["Everything covered."]

    def test_an_exploration_failure_is_a_warning_never_a_crash(self, tmp_path: Path) -> None:
        package = _save_workflow(tmp_path, "api-flow", self._document())

        class BrokenModel:
            def bind_tools(self, tools: Any, **kw: Any) -> Any:
                raise RuntimeError("provider down")

        report = ExplorerKnowledgeBuilder().explore(
            package, self._document(), tmp_path, BrokenModel()
        )
        assert report.written == []
        assert report.warnings and "provider down" in report.warnings[0]


class TestGrounding:
    """production-ready ticket 12 — the class behind ticket 10's instance.

    Ticket 10 caught one mechanical shape: a topic *named after* a tool. The
    document that started it had a wider defect, and it is the project's stated
    worst failure mode — *"a wrong sentence in `knowledge/` is not a
    hallucination any more, it is a fact the model was handed."* The explorer
    could write a document **without calling anything at all**, and the
    provenance footer that made the fabrication detectable said `web_search`
    anyway, because the explorer's provenance was the list of tools it was
    *offered*, computed before the agent ran.

    So there are two rules here and they are one seam:

    - provenance is **what was called**, never what was available;
    - a topic with no provenance is refused, because it is by definition a
      topic that could have been written without looking at anything.

    The second is the ticket's own operational test for parametric knowledge.
    """

    def _document(self, *types: str) -> dict[str, Any]:
        return {
            "nodes": [{"id": f"n{i}", "type": t, "data": {}} for i, t in enumerate(types)],
            "edges": [],
        }

    def test_a_topic_with_nothing_behind_it_is_refused(self, tmp_path: Path) -> None:
        report = ExplorationReport()
        tool = WriteTopicTool(ExplorerKnowledgeBuilder(), tmp_path / "flow", report)
        result = tool.run(topic="uk-vat-rates", content="uk-vat-rates — 20% standard.")
        assert not result.ok
        assert "call" in str(result.error).lower()
        assert report.written == []
        assert not (tmp_path / "flow" / "knowledge" / "uk-vat-rates.md").exists()

    def test_one_call_is_enough_to_earn_the_write(self, tmp_path: Path) -> None:
        """The rule is grounding, not caution — the explorer's real job must
        survive it. One genuine call and the domain topic goes through."""
        report = ExplorationReport()
        tool = WriteTopicTool(
            ExplorerKnowledgeBuilder(), tmp_path / "flow", report,
            provenance=lambda: ("tool web_search",),
        )
        assert tool.run(topic="uk-vat-rates", content="uk-vat-rates — 20% standard.").ok
        assert report.written == ["uk-vat-rates"]

    def test_a_model_that_calls_nothing_writes_no_topics(self, tmp_path: Path) -> None:
        """**The ticket's required test.** A scripted model that calls no study
        tool and goes straight for `write_topic` produces *no topics* — not a
        topic with a caveat. This is the exact shape of the run that produced
        `web-search-tool.md`."""
        document = self._document("tool.web-search")
        package = _save_workflow(tmp_path, "api-flow", document)
        model = ToolCallingScriptedModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_topic",
                            "args": {
                                "topic": "uk-vat-rates",
                                "content": "uk-vat-rates — the standard rate is 20%.",
                            },
                            "id": "call-1",
                        }
                    ],
                ),
                AIMessage(content="NOT covered: everything — I called nothing."),
            ]
        )
        report = ExplorerKnowledgeBuilder().explore(package, document, tmp_path, model)
        assert report.written == []
        assert not (package / "knowledge" / "uk-vat-rates.md").exists()

    def test_provenance_names_what_was_called_not_what_was_offered(
        self, tmp_path: Path
    ) -> None:
        """Two tools offered, one called. The footer names the one."""
        document = self._document("tool.web-search", "tool.web-fetch")
        package = _save_workflow(tmp_path, "api-flow", document)
        model = ToolCallingScriptedModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "web_search", "args": {"query": "uk vat"}, "id": "c-0"}
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_topic",
                            "args": {
                                "topic": "uk-vat-rates",
                                "content": "uk-vat-rates — the standard rate is 20%.",
                            },
                            "id": "c-1",
                        }
                    ],
                ),
                AIMessage(content="NOT covered: reduced rates."),
            ]
        )
        report = ExplorerKnowledgeBuilder().explore(package, document, tmp_path, model)
        assert report.written == ["uk-vat-rates"]
        doc = (package / "knowledge" / "uk-vat-rates.md").read_text()
        assert "web_search" in doc
        assert "web_fetch" not in doc

    def test_a_tool_that_was_offered_but_never_called_still_cannot_be_a_topic(
        self, tmp_path: Path
    ) -> None:
        """Ticket 10's guard must not weaken as a side effect of this one.

        It used to read the provenance tuple, which named every offered tool.
        Now that provenance means *called*, the guard reads the studied set
        instead — otherwise calling one tool would license writing vendor
        documentation about its neighbour."""
        report = ExplorationReport()
        tool = WriteTopicTool(
            ExplorerKnowledgeBuilder(), tmp_path / "flow", report,
            provenance=lambda: ("tool web_search",),
            studied=("web_search", "web_fetch"),
        )
        result = tool.run(topic="web-fetch-tool", content="web-fetch-tool — vendor docs.")
        assert not result.ok and "not a topic" in str(result.error)
        assert report.written == []


class TestRegistration:
    def test_the_agentic_builders_are_registered_after_the_mechanical_ones(self) -> None:
        kinds = [b.source_kind for b in BUILDERS]
        assert kinds.index("sql") < kinds.index("explorer")
        assert "codebase" in kinds
        assert isinstance(BUILDERS[kinds.index("explorer")], AgenticKnowledgeBuilder)


class TestAnMcpNodeContributesItsServersTools:
    """`organisms-first-class` 50 — the explorer bound the **singular** seam.

    `tool.mcp` is not on `EXPLORER_DENY_PREFIXES`, and one MCP server node
    stands for N tools discovered at bind time. Calling `as_langchain_tool()`
    over it handed the agent one tool that refuses when called, in place of
    the server's actual tools. The plural seam is the one the canvas binds
    through (`NodeRuntime._bind_tools`), and this pins that the explorer now
    binds it too — capability, warnings and provenance all intact.
    """

    def _document(self) -> dict[str, Any]:
        return {
            "nodes": [{"id": "m", "type": "tool.mcp", "data": {KEY_SERVER: "LangChain docs"}}],
            "edges": [],
        }

    def test_the_agent_is_bound_the_servers_tools_not_one_refusal(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search", "fetch"))
        document = self._document()
        package = _save_workflow(tmp_path, "mcp-flow", document)

        tools, _prov, warnings = ExplorerKnowledgeBuilder().study_tools(
            package, document, tmp_path
        )

        assert [t.name for t in tools] == ["search", "fetch"]
        assert warnings == []

    def test_a_bound_mcp_tool_actually_answers_instead_of_refusing(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """The inverse of the defect, at the only layer that can see it: the
        old binding produced a tool whose every call came back `Error: An MCP
        server node contributes its server's tools...`."""
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search"))
        document = self._document()
        package = _save_workflow(tmp_path, "mcp-flow", document)

        tools, _prov, _warn = ExplorerKnowledgeBuilder().study_tools(package, document, tmp_path)
        answer = tools[0].invoke({"q": "vat"})

        assert "is not itself one of them" not in str(answer)
        assert "ok" in str(answer)

    def test_calling_an_mcp_tool_earns_the_write_and_names_itself_in_the_footer(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Provenance survives the move. The plural seam takes no `on_call`,
        so the explorer records at its own boundary instead — and the footer
        must still name what was *called*, not what was offered."""
        monkeypatch.setattr(prebuilt_mcp, "_discover_tools", fake_discovery("search", "fetch"))
        document = self._document()
        package = _save_workflow(tmp_path, "mcp-flow", document)
        model = ToolCallingScriptedModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "search", "args": {"q": "vat"}, "id": "c-0"}],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_topic",
                            "args": {
                                "topic": "uk-vat-rates",
                                "content": "uk-vat-rates — the standard rate is 20%.",
                            },
                            "id": "c-1",
                        }
                    ],
                ),
                AIMessage(content="NOT covered: reduced rates."),
            ]
        )

        report = ExplorerKnowledgeBuilder().explore(package, document, tmp_path, model)

        assert report.written == ["uk-vat-rates"]
        doc = (package / "knowledge" / "uk-vat-rates.md").read_text()
        assert "search" in doc
        assert "fetch" not in doc

    def test_a_server_that_is_down_costs_one_capability_and_says_so(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """The plural seam's `warnings` sink is the channel the explorer
        already has — `explore` extends `report.warnings` with it."""
        monkeypatch.setattr(
            prebuilt_mcp, "_discover_tools", failing_discovery(httpx.ConnectError("refused"))
        )
        document = self._document()
        package = _save_workflow(tmp_path, "mcp-flow", document)

        tools, _prov, warnings = ExplorerKnowledgeBuilder().study_tools(
            package, document, tmp_path
        )

        assert tools == []
        assert warnings and "LangChain docs" in warnings[0]

    def test_a_non_mcp_tool_node_binds_exactly_as_before(self, tmp_path: Path) -> None:
        """The inverse that keeps the move honest: the default plural seam is
        the singular one with one element, and provenance still works."""
        document = {
            "nodes": [{"id": "w", "type": "tool.web-search", "data": {}}],
            "edges": [],
        }
        package = _save_workflow(tmp_path, "web-flow", document)

        tools, provenance, warnings = ExplorerKnowledgeBuilder().study_tools(
            package, document, tmp_path
        )

        assert [t.name for t in tools] == ["web_search"]
        assert warnings == []
        assert provenance() == ()
