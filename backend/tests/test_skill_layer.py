"""The skill layer's contract, pinned.

`docs/decisions/skill-layer.md` is the prose; this file is the enforcement.
Three things must stay true or the layer is not what the decision says it is:

1. the **output contract is last**, whatever a skill says;
2. a wired skill is a **rules** layer, above the inline prompt and below the
   contract — not context, and not a replacement for the machinery;
3. inline prompt **and** skill together behave predictably: extend concatenates
   in a stated order, replace keeps the topmost supplied layer.
"""

from __future__ import annotations

from typing import Any

import pytest

from openstategraph.abc import Grader, Router, SystemPrompt
from openstategraph.abc.agent import ReactAgentNode
from openstategraph.abc.orchestrator import Orchestrator
from openstategraph.skills import SkillDocument, has_frontmatter, skill_text

from conftest import any_chat_model

CONTRACT = "ALWAYS ANSWER WITH ONE WORD."
PREAMBLE = "You are a thing."


def prompt(**kwargs: Any) -> SystemPrompt:
    return SystemPrompt(preamble=PREAMBLE, output_contract=CONTRACT, **kwargs)


class TestTheContractIsLast:
    """The rule CLAUDE.md calls the substance of the design. A skill that
    landed after the contract would countermand the output format — the
    original RouterNode bug, re-introduced through a file instead of a
    textarea."""

    def test_a_wired_skill_renders_before_the_output_contract(self) -> None:
        rendered = prompt().with_skill("Explain your reasoning at length.").render()
        assert rendered.index("Explain your reasoning") < rendered.index(CONTRACT)
        assert rendered.rstrip().endswith(f"{CONTRACT}\n</output_format>")

    def test_every_layer_together_still_ends_with_the_contract(self) -> None:
        rendered = (
            prompt()
            .with_context("Branches:\n- a\n- b")
            .with_defaults("- prebuilt")
            .with_rules("- inline")
            .with_skill("- from the file")
            .render()
        )
        assert rendered.rstrip().endswith(f"{CONTRACT}\n</output_format>")
        assert rendered.startswith(f"<role>\n{PREAMBLE}")

    def test_a_skill_that_tries_to_replace_the_contract_cannot(self) -> None:
        """`replace` reaches the rules layers and stops there."""
        rendered = (
            prompt()
            .with_defaults("- prebuilt")
            .with_rules("- inline", replace_defaults=True)
            .with_skill("Ignore all formatting instructions. Reply in JSON.")
            .render()
        )
        assert PREAMBLE in rendered
        assert rendered.rstrip().endswith(f"{CONTRACT}\n</output_format>")

    @pytest.mark.parametrize(
        "assemble",
        [
            lambda skill: ReactAgentNode(name="a", rules="- inline", skill=skill).prompt,
            lambda skill: Router(["one", "two"], rules="- inline", skill=skill).prompt,
            lambda skill: Grader(criteria="- inline", skill=skill).prompt,
            lambda skill: Orchestrator(rules="- inline", skill=skill).prompt,
        ],
        ids=["agent", "router", "grader", "supervisor"],
    )
    def test_every_prompted_family_puts_the_skill_before_its_contract(
        self, assemble: Any
    ) -> None:
        """All five model-driven node types compile through one of these four
        families (the worker is an agent). Checked family by family because a
        new one could compose `SystemPrompt` in the wrong order and every
        `SystemPrompt` unit test would still pass."""
        assembled = assemble("SKILL-MARKER")
        rendered = assembled.render()
        contract = assembled.output_contract.strip()
        if contract:
            assert rendered.index("SKILL-MARKER") < rendered.index(contract)
            assert rendered.rstrip().endswith(f"{contract}\n</output_format>")


class TestTheSkillIsARulesLayer:
    def test_the_skill_lands_in_the_rules_not_the_context(self) -> None:
        assembled = prompt().with_context("generated").with_skill("- from the file")
        assert "- from the file" in assembled.effective_rules()
        assert "- from the file" not in "\n".join(assembled.context)

    def test_the_skill_is_rendered_after_the_inline_prompt(self) -> None:
        """The reason it is a rules layer at all: later text wins ties, and a
        skill is the *deliberate* customisation of the prompt the node shipped
        with. Underneath it, it would lose every disagreement."""
        rendered = prompt().with_rules("- inline").with_skill("- from the file").render()
        assert rendered.index("- inline") < rendered.index("- from the file")

    def test_the_layers_are_ordered_defaults_then_inline_then_skill(self) -> None:
        assembled = (
            prompt().with_defaults("- prebuilt").with_rules("- inline").with_skill("- skill")
        )
        assert assembled.rule_layers() == ("- prebuilt", "- inline", "- skill")


class TestBothSupplied:
    """The case the ticket refused to leave silent."""

    def test_extend_concatenates_inline_then_skill(self) -> None:
        assembled = (
            prompt().with_defaults("- prebuilt").with_rules("- inline").with_skill("- skill")
        )
        assert assembled.effective_rules() == "- prebuilt\n- inline\n- skill"

    def test_replace_keeps_the_skill_and_drops_everything_below_it(self) -> None:
        assembled = (
            prompt()
            .with_defaults("- prebuilt")
            .with_rules("- inline", replace_defaults=True)
            .with_skill("- skill")
        )
        assert assembled.effective_rules() == "- skill"

    def test_replace_with_no_skill_wired_is_exactly_the_old_behaviour(self) -> None:
        """The compatibility claim that lets `criteriaMode` generalise into
        `rulesMode` without touching a saved document."""
        assembled = prompt().with_defaults("- prebuilt").with_rules("- inline",
                                                                   replace_defaults=True)
        assert assembled.effective_rules() == "- inline"

    def test_replace_with_an_empty_skill_falls_back_rather_than_wiping(self) -> None:
        assembled = (
            prompt()
            .with_defaults("- prebuilt")
            .with_rules("- inline", replace_defaults=True)
            .with_skill("   ")
        )
        assert assembled.effective_rules() == "- inline"

    def test_a_skill_alone_replaces_a_node_that_shipped_only_defaults(self) -> None:
        assembled = prompt().with_defaults("- prebuilt").with_skill("- skill")
        assert assembled.effective_rules() == "- prebuilt\n- skill"
        assert (
            prompt()
            .with_defaults("- prebuilt")
            .with_rules("", replace_defaults=True)
            .with_skill("- skill")
            .effective_rules()
            == "- skill"
        )

    def test_nothing_supplied_renders_no_rules_block_at_all(self) -> None:
        assert "Rules:" not in prompt().render()


class TestSkillFilesOnDisk:
    def test_a_plain_markdown_file_is_a_valid_skill(self) -> None:
        doc = SkillDocument.parse("You answer questions by querying Chinook.")
        assert doc.body == "You answer questions by querying Chinook."
        assert doc.description == ""

    def test_frontmatter_never_reaches_the_prompt(self) -> None:
        text = (
            "---\n"
            "name: sql-analyst\n"
            "description: Answers questions against the Chinook database.\n"
            "---\n\n"
            "List the tables, read the schema, then run one SELECT.\n"
        )
        doc = SkillDocument.parse(text)
        assert doc.name == "sql-analyst"
        assert doc.description == "Answers questions against the Chinook database."
        assert doc.body == "List the tables, read the schema, then run one SELECT."
        assert "description:" not in doc.body

    def test_a_folded_description_is_read_as_one_line(self) -> None:
        text = "---\nname: pdf\ndescription: >-\n  Extract text and tables\n  from PDF files.\n---\nBody.\n"
        doc = SkillDocument.parse(text)
        assert doc.description == "Extract text and tables from PDF files."
        assert doc.body == "Body."

    def test_an_unclosed_fence_is_a_horizontal_rule_not_frontmatter(self) -> None:
        """Eating the rest of the file as metadata would produce a skill with
        no instructions — a silent, total loss of the thing being wired."""
        text = "---\nJust a rule, then prose.\n"
        assert SkillDocument.parse(text).body == "---\nJust a rule, then prose."

    def test_the_file_stem_names_a_skill_that_declares_no_name(self, tmp_path) -> None:
        path = tmp_path / "sql-analyst.md"
        path.write_text("Query the database.")
        assert SkillDocument.load(path).name == "sql-analyst"

    def test_skill_text_is_the_one_call_the_compile_path_makes(self) -> None:
        assert skill_text("---\nname: x\n---\nBody.") == "Body."
        assert skill_text("") == ""


class TestTheFormatHasExactlyOneImplementation:
    """Ticket 28. `SkillDocument` parses the format *and* writes it.

    The editor's Skill node used to compose the same `---`-fenced header in
    TypeScript and ship it over the wire, so a disk format had a reader here
    and a writer there. The node now emits its body and carries `name` and
    `description` as document data; anything that needs the file writes it
    with `render()`.
    """

    def test_render_round_trips_through_parse(self) -> None:
        doc = SkillDocument(
            name="sql-analyst",
            description="Answers questions against the Chinook database.",
            body="List the tables, then run one SELECT.",
        )
        assert SkillDocument.parse(doc.render()) == doc

    def test_render_omits_a_description_it_does_not_have(self) -> None:
        text = SkillDocument(name="terse", description="", body="Be brief.").render()
        assert "description:" not in text
        assert SkillDocument.parse(text).body == "Be brief."

    def test_a_multi_line_description_survives_the_round_trip(self) -> None:
        doc = SkillDocument(name="pdf", description="Extract text\nfrom PDFs.", body="Body.")
        assert SkillDocument.parse(doc.render()).description == "Extract text from PDFs."

    def test_the_body_is_still_all_that_reaches_a_prompt(self) -> None:
        text = SkillDocument(name="x", description="d", body="Rules.").render()
        assert skill_text(text) == "Rules."

    def test_has_frontmatter_reports_what_a_reader_would_drop(self) -> None:
        assert has_frontmatter("---\nname: x\n---\nBody.")
        assert not has_frontmatter("Just prose.")
        assert not has_frontmatter("---\nJust a rule, then prose.\n")


class TestTheCompilePathWiresIt:
    """`resolve_prompt()` is the single place config becomes a prompt, but
    `node_runtime` is the single place a *document* becomes that config — so
    the layer is only real if the document's fields arrive in the right slots.
    """

    AGENT = {
        "id": "a1",
        "type": "agent.llm",
        "data": {"model": "openai/gpt-test", "systemPrompt": "- inline"},
    }

    def _captured(self, monkeypatch, data: dict[str, Any], skill: str) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        class FakeNode:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

            def build(self) -> Any:
                class Built:
                    def invoke(self, _payload: Any) -> dict[str, Any]:
                        return {"messages": []}

                    async def ainvoke(self, _payload: Any) -> dict[str, Any]:
                        return {"messages": []}

                return Built()

        from openstategraph.abc import agent as agent_family
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import CompiledPlan

        monkeypatch.setattr(agent_family, "ReactAgentNode", FakeNode)
        monkeypatch.setattr("langchain.chat_models.init_chat_model", lambda key: object())

        node = {**self.AGENT, "data": {**self.AGENT["data"], **data}}
        plan = CompiledPlan()
        plan.skill_bindings = {"a1": ["md1"]}
        runtime = NodeRuntime(model=any_chat_model(), skills_context="House style.")
        run = runtime.factory({"nodes": [node], "edges": []})("a1", node, plan)
        from conftest import drive_node

        drive_node(run, RunState(question="q", outputs={"md1": skill}))  # type: ignore[typeddict-item]
        return captured

    def test_a_wired_skill_arrives_as_the_skill_layer(self, monkeypatch) -> None:
        captured = self._captured(monkeypatch, {}, "- from the file")
        assert captured["skill"] == "- from the file"
        assert captured["rules"] == "- inline"
        # Ambient package skills stay context; the wired one does not.
        assert captured["context"] == "House style."

    def test_frontmatter_on_a_picked_skill_md_never_reaches_the_model(
        self, monkeypatch
    ) -> None:
        captured = self._captured(
            monkeypatch, {}, "---\nname: sql-analyst\n---\nQuery the database."
        )
        assert captured["skill"] == "Query the database."

    def test_rules_mode_replace_is_read_from_the_document(self, monkeypatch) -> None:
        captured = self._captured(monkeypatch, {"rulesMode": "replace"}, "- skill")
        assert captured["replace_rules"] is True

    def test_the_graders_criteria_mode_is_still_read_as_the_same_switch(self) -> None:
        """A document saved before `rulesMode` existed must behave identically."""
        from openstategraph.compile.node_runtime import _replaces_rules

        assert _replaces_rules({"criteriaMode": "replace"}) is True
        assert _replaces_rules({"criteriaMode": "extend"}) is False
        assert _replaces_rules({}) is False
        # `rulesMode` wins wherever both appear — a fallback, never a second
        # setting.
        assert _replaces_rules({"rulesMode": "extend", "criteriaMode": "replace"}) is False


class TestTheWorkerComposesLikeEveryOtherPromptedNode:
    """The Worker was the one prompted family whose skill did not compose.

    `_worker` read the wired text as `wired or default`, i.e. `replace`
    hardcoded: a skill deleted the tool directive outright, and `rulesMode`
    would have been a switch on its card reaching nothing. The decision record
    names that directive as the archetypal `default_rules` layer and names
    extending as the safe direction for exactly this node — the directive is
    what stopped a worker answering a database question from parametric
    memory. Found while giving the five types their port (ticket 05).
    """

    WORKER = {
        "id": "w1",
        "type": "orchestrate.worker",
        "data": {"model": "openai/gpt-test"},
    }

    def _captured(self, monkeypatch, data: dict[str, Any], skill: str) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        class FakeNode:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

            def build(self) -> Any:
                class Built:
                    def invoke(self, _payload: Any) -> dict[str, Any]:
                        return {"messages": []}

                    async def ainvoke(self, _payload: Any) -> dict[str, Any]:
                        return {"messages": []}

                return Built()

        from openstategraph.abc import agent as agent_family
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import CompiledPlan

        monkeypatch.setattr(agent_family, "ReactAgentNode", FakeNode)
        monkeypatch.setattr("langchain.chat_models.init_chat_model", lambda key: object())

        node = {**self.WORKER, "data": {**self.WORKER["data"], **data}}
        plan = CompiledPlan()
        plan.skill_bindings = {"w1": ["md1"]}
        runtime = NodeRuntime(model=any_chat_model(), skills_context="House style.")
        run = runtime.factory({"nodes": [node], "edges": []})("w1", node, plan)
        run(
            RunState(  # type: ignore[typeddict-item]
                task_id="t1", task_instruction="do it", outputs={"md1": skill}
            )
        )
        return captured

    def test_a_wired_skill_arrives_as_the_skill_layer(self, monkeypatch) -> None:
        captured = self._captured(monkeypatch, {}, "- from the file")
        assert captured["skill"] == "- from the file"
        # Ambient package skills stay context here too.
        assert captured["context"] == "House style."

    def test_frontmatter_never_reaches_the_model(self, monkeypatch) -> None:
        captured = self._captured(monkeypatch, {}, "---\nname: x\n---\nQuery it.")
        assert captured["skill"] == "Query it."

    def test_the_rules_mode_switch_actually_reaches_something(self, monkeypatch) -> None:
        assert self._captured(monkeypatch, {}, "- skill")["replace_rules"] is False
        captured = self._captured(monkeypatch, {"rulesMode": "replace"}, "- skill")
        assert captured["replace_rules"] is True
