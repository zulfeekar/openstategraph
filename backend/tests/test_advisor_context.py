"""The editor advisor: a capability gap the agent can name, and the editor can fix.

The product rule this pins: when a run in the *editor's* Ask panel cannot
answer because the workflow lacks a tool, the agent says so and emits a
``suggestion`` fence the editor turns into a real, wired node. Three things
have to hold for that to be safe:

1. the extra context actually reaches the agent — and carries *that* agent's
   own node id, since a wrong ``attachTo`` is the one error the editor cannot
   recover from;
2. it is **off** unless asked for, which is what keeps the customer `/chat`
   surface from ever being told to propose edits.

Those two are below. The third — that developer guidance cannot *reach* a
customer even when a model emits it anyway — moved to
``tests/test_audience_boundary.py`` with the boundary itself, because it is a
claim about the transport rather than about the prompt, and proving it needs
the real endpoint rather than a schema.
"""

from __future__ import annotations

import openstategraph.abc.agent as agent_module
from openstategraph.abc.agent import ReactAgentNode
from openstategraph.api.registries import suggestible_tool_catalog
from openstategraph.compile.node_runtime import NodeRuntime, RunState, RuntimeServices
from openstategraph.compile.workflow_compiler import CompiledPlan

from conftest import any_chat_model, drive_node


class TestTheCatalogue:
    def test_it_lists_web_search_with_its_own_description(self) -> None:
        from openstategraph.prebuilt_web import WEB_TOOLS

        registry = {tool.node_type: tool for tool in WEB_TOOLS}
        catalog = suggestible_tool_catalog(registry)
        line = next(l for l in catalog.splitlines() if l.startswith("- tool.web-search"))
        # The tool's own `description` — the same text the model sees once the
        # tool is bound — never a second hand-kept summary that could drift.
        assert "—" in line and len(line) > len("- tool.web-search — ")

    def test_it_omits_tools_a_suggestion_could_not_place_unconfigured(self) -> None:
        """A `tool.chinook-*` node is bound to one bundled database, so
        offering it as a fix for an arbitrary gap would wire a node that
        answers nothing."""
        catalog = suggestible_tool_catalog(
            {"tool.chinook-execute-sql": object(), "tool.web-search": object()}
        )
        assert "tool.chinook-execute-sql" not in catalog
        assert "tool.web-search" in catalog


class _RecordingNode(ReactAgentNode):
    """Records construction instead of building — no model, no network."""

    built: list["_RecordingNode"] = []

    def build(self):
        _RecordingNode.built.append(self)
        return None


def _prompt_for(**services_kwargs: object) -> str:
    _RecordingNode.built.clear()
    runtime = NodeRuntime(services=RuntimeServices(model=any_chat_model(), **services_kwargs))  # type: ignore[arg-type]
    node = {"id": "agent-analyst", "type": "agent.llm", "data": {"systemPrompt": "Be terse."}}
    run = runtime._agent("agent-analyst", node, CompiledPlan())
    drive_node(run, RunState(question="q"))  # type: ignore[typeddict-item]
    (built,) = _RecordingNode.built
    return built.resolve_prompt() or ""


class TestTheContextReachesTheAgent:
    def test_without_the_flag_no_advisor_text_is_composed(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda tier: _RecordingNode)
        prompt = _prompt_for()
        assert "```suggestion" not in prompt

    def test_with_a_catalogue_the_agent_is_told_how_to_suggest(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda tier: _RecordingNode)
        prompt = _prompt_for(advisor_catalog="- tool.web-search — searches the web")
        assert "```suggestion" in prompt
        assert "- tool.web-search — searches the web" in prompt

    def test_attach_to_is_prefilled_with_this_agents_own_node_id(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda tier: _RecordingNode)
        prompt = _prompt_for(advisor_catalog="- tool.web-search — searches the web")
        assert '"attachTo": "agent-analyst"' in prompt

    def test_the_sentence_before_the_block_is_stated_as_required(self, monkeypatch) -> None:
        """Ticket 22: *"say so briefly, then emit exactly one fenced block"*
        read as one instruction with an optional first half, and a model that
        emitted only the block left a run whose answer was the empty string
        once the fence was split out of it.

        The prompt layer is where a reply's *shape* is asked for, so this is
        where "the prose is not optional" belongs — `split_suggestion`'s floor
        is the guarantee, and this is what makes it almost never needed."""
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda tier: _RecordingNode)
        prompt = _prompt_for(advisor_catalog="- tool.web-search — searches the web")
        instruction = prompt.split("```suggestion")[0]
        assert "never the block alone" in instruction

    def test_it_lands_in_context_above_the_developers_rules(self, monkeypatch) -> None:
        """The fence is *context*, not rules and not a contract change.

        `SystemPrompt` renders context, then rules, then the locked output
        contract — so proving the advisor block sits above the authored rules
        proves it also sits above the contract, whatever that contract later
        grows into. Order is the substance here: machinery must stay last."""
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda tier: _RecordingNode)
        prompt = _prompt_for(advisor_catalog="- tool.web-search — searches the web")
        assert prompt.index("```suggestion") < prompt.index("Be terse.")
