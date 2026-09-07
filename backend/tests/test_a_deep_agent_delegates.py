"""A deep agent declares its own workers, and they actually run —
`organisms-first-class/84`.

The trap this file is written against is named in the ticket: *a test that
`subagents=` was passed is exactly the test that would pass against `skills=`'s
silent nothing*. `docs/decisions/deep-agent-slots.md` measured `skills=` loading
a real directory into `(No skills available)` with no error anywhere. So the
headline test here does not inspect a kwarg. It compiles a document, runs it
with a scripted model that calls `task`, and asserts that the **declared
subagent's own prompt reached a model** and that its answer came back to the
parent as a `ToolMessage`.

The two isolation sentences are asserted together, because apart they read as a
contradiction: the subagent never sees the parent's messages or graph state,
**and** the run's context crosses into the subagent's tools unchanged.

Every model below is a fake, so this proves what is assembled and what a tool
returns — never how a real model decides to delegate. It used to say "no
provider credential exists here", and that was false: `.env` holds working
keys and the belief came from an instrument that could not check
(`providers-and-credentials/12`). The unproven half has since been measured —
five live runs on `anthropic:claude-haiku-4-5`, five correct delegations,
`docs/decisions/live-model-verification-2026-08-23.md` — which is a record of
one evening rather than something this file can assert, so the scripted proof
below stays exactly as it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan, WorkflowCompiler

from conftest import drive_node
from openstategraph.compile.subagents import (
    subagent_declaration_problems,
    subagent_specs,
)

pytest.importorskip("deepagents")

from langchain.tools import ToolRuntime, tool


@dataclass
class Ctx:
    """A run context schema, for the crossing half of the isolation pair."""

    tenant: str = ""


#: What the subagent's tool saw. Module level because a `@tool` defined inside
#: a function cannot resolve its own annotations — pydantic evaluates them in
#: the module namespace and raises `NameError: ToolRuntime` from a closure.
_CROSSED: list[str] = []


@tool
def whoami(runtime: ToolRuntime[Ctx]) -> str:
    """Report the tenant this run was started for."""
    _CROSSED.append(runtime.context.tenant)
    return f"tenant={runtime.context.tenant}"


PARENT_MARKER = "PARENT RULES MARKER"
SUB_MARKER = "RESEARCHER RULES MARKER"


class ScriptedModel(GenericFakeChatModel):
    """Answers by which system prompt it was handed, and records every call.

    Order-independent on purpose: a parent turn and a subagent turn are two
    different agents' model calls, and asserting on a queue would make the test
    depend on scheduling rather than on behaviour.
    """

    seen: list[list[tuple[str, str]]] = []

    def __init__(self) -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "seen", [])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self

    def _generate(self, messages: Any, *args: Any, **kwargs: Any) -> ChatResult:
        turn = [(type(m).__name__, str(m.content)) for m in messages]
        self.seen.append(turn)
        text = "\n".join(content for _, content in turn)
        if SUB_MARKER in text:
            return _reply(AIMessage(content="RESEARCHER ANSWER: 42"))
        if any(kind == "ToolMessage" for kind, _ in turn):
            return _reply(AIMessage(content="the researcher said 42"))
        return _reply(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {"description": "find it", "subagent_type": "researcher"},
                        "id": "call-1",
                    }
                ],
            )
        )


def _reply(message: AIMessage) -> ChatResult:
    return ChatResult(generations=[ChatGeneration(message=message)])


def _agent_data(**extra: Any) -> dict[str, Any]:
    return {
        "tier": "deep",
        "systemPrompt": PARENT_MARKER,
        "summarize": False,
        "subagents": [
            {
                "id": "sa1",
                "name": "researcher",
                "description": "Looks facts up and reports one number.",
                "systemPrompt": SUB_MARKER,
            }
        ],
        **extra,
    }


def _run_agent(data: dict[str, Any], model: ScriptedModel) -> dict[str, Any]:
    runtime = NodeRuntime(model=model)
    node = {"id": "a1", "type": "agent.llm", "data": data}
    run = runtime._agent("a1", node, CompiledPlan())
    return drive_node(run, RunState(question="what is the answer?"))  # type: ignore[typeddict-item]


class TestADeclaredSubagentRuns:
    def test_the_declared_worker_runs_and_answers_through_a_tool_message(self) -> None:
        model = ScriptedModel()
        result = _run_agent(_agent_data(), model)

        # The subagent's own prompt reached a model — the thing a kwarg
        # assertion cannot tell apart from `skills=`'s silent nothing.
        sub_turns = [
            turn
            for turn in model.seen
            if any(SUB_MARKER in content for _, content in turn)
        ]
        assert sub_turns, "the declared subagent's prompt never reached a model"

        # And its answer came back to the parent as a ToolMessage.
        parent_tail = model.seen[-1]
        assert ("ToolMessage", "RESEARCHER ANSWER: 42") in parent_tail
        assert "42" in result["outputs"]["a1"]

    def test_the_parents_own_rules_still_reach_the_parent_and_not_the_worker(
        self,
    ) -> None:
        model = ScriptedModel()
        _run_agent(_agent_data(), model)
        sub_turns = [
            turn for turn in model.seen if any(SUB_MARKER in c for _, c in turn)
        ]
        assert sub_turns
        for turn in sub_turns:
            assert not any(PARENT_MARKER in content for _, content in turn)


class TestIsolationAndContextBothHold:
    """The two sentences that look contradictory and are both true."""

    def test_a_subagent_never_sees_the_parents_message_history(self) -> None:
        model = ScriptedModel()
        runtime = NodeRuntime(model=model)
        node = {"id": "a1", "type": "agent.llm", "data": _agent_data()}
        run = runtime._agent("a1", node, CompiledPlan())
        drive_node(run, RunState(question="PARENT SECRET TURN"))  # type: ignore[typeddict-item]

        sub_turns = [
            turn for turn in model.seen if any(SUB_MARKER in c for _, c in turn)
        ]
        assert sub_turns
        for turn in sub_turns:
            assert not any("PARENT SECRET TURN" in content for _, content in turn)

    def test_run_context_still_crosses_into_a_subagents_tool(self) -> None:
        """`a86b4d8`, re-measured on the subagent path.

        Library-level, because the crossing is the library's: a document-level
        assertion would prove the same thing through more machinery and would
        go red for reasons that are not this.
        """
        from deepagents import create_deep_agent

        _CROSSED.clear()
        class Delegating(GenericFakeChatModel):
            def bind_tools(self, tools: Any, **kwargs: Any) -> "Delegating":
                return self

        replies = iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {"description": "who", "subagent_type": "researcher"},
                            "id": "c1",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "whoami", "args": {}, "id": "c2"}],
                ),
                AIMessage(content="sub done"),
                AIMessage(content="parent done"),
            ]
        )
        agent = create_deep_agent(
            Delegating(messages=replies),
            tools=[whoami],
            subagents=subagent_specs(_agent_data()),
            context_schema=Ctx,
        )
        agent.invoke({"messages": [{"role": "user", "content": "hi"}]}, context=Ctx(tenant="acme"))
        assert _CROSSED == ["acme"]


class TestNothingElseMoved:
    def test_a_deep_agent_with_no_declaration_passes_no_subagents(self) -> None:
        """Byte-identical to before the ticket: the kwarg is absent, not empty.

        `create_deep_agent` treats `subagents=[]` and `subagents=None` the same
        today, but that is the library's choice and not ours to depend on.
        """
        import openstategraph.abc.agent as agent_module

        seen: list[dict[str, Any]] = []

        class Recording(agent_module.DeepAgentNode):
            def build(self) -> None:
                seen.append({"subagents": self.subagents})
                return None

        original = agent_module.agent_node_for_tier
        try:
            agent_module.agent_node_for_tier = (
                lambda tier: Recording if tier == "deep" else agent_module.ReactAgentNode
            )
            _run_agent({"tier": "deep", "summarize": False}, ScriptedModel())
        finally:
            agent_module.agent_node_for_tier = original
        assert seen == [{"subagents": []}]

    def test_a_react_tier_agent_is_unaffected(self) -> None:
        model = ScriptedModel()
        result = _run_agent({"tier": "react", "systemPrompt": PARENT_MARKER, "summarize": False}, model)
        assert not any(
            any(SUB_MARKER in content for _, content in turn) for turn in model.seen
        )
        assert "outputs" in result


class TestADeclarationTheRuntimeCannotDeliverIsSaidOutLoud:
    """`plan.warnings` — the channel `validate` prints and exits non-zero on."""

    @staticmethod
    def _plan_warnings(node_data: dict[str, Any]) -> list[str]:
        document = {
            "version": 1,
            "name": "d",
            "nodes": [{"id": "a1", "type": "agent.llm", "data": node_data}],
            "edges": [],
        }
        return WorkflowCompiler().plan(document).warnings

    def test_a_subagent_on_a_react_tier_is_a_problem_not_a_silent_drop(self) -> None:
        warnings = self._plan_warnings(_agent_data(tier="react"))
        assert any("only the deep agent runtime" in w for w in warnings)

    def test_a_row_missing_its_three_strings_is_named(self) -> None:
        warnings = self._plan_warnings(
            {"tier": "deep", "subagents": [{"id": "x", "name": "researcher"}]}
        )
        assert any(
            "a description" in w and "a system prompt" in w and "researcher" in w
            for w in warnings
        )

    def test_a_repeated_name_is_named(self) -> None:
        data = _agent_data()
        data["subagents"] = data["subagents"] + [dict(data["subagents"][0], id="sa2")]
        warnings = self._plan_warnings(data)
        assert any("repeats a name" in w for w in warnings)

    def test_a_malformed_row_is_dropped_rather_than_repaired(self) -> None:
        specs = subagent_specs(
            {"subagents": [{"name": "a"}, {"name": "b", "description": "d", "systemPrompt": "p"}]}
        )
        assert [s["name"] for s in specs] == ["b"]

    def test_a_document_with_no_declaration_says_nothing(self) -> None:
        assert subagent_declaration_problems(
            {"nodes": [{"id": "a1", "type": "agent.llm", "data": {"tier": "deep"}}]}
        ) == []


class TestToolsPerSubagent:
    def test_inherit_omits_the_key_and_none_passes_an_empty_list(self) -> None:
        inherit = subagent_specs(
            {"subagents": [{"name": "n", "description": "d", "systemPrompt": "p"}]}
        )
        assert "tools" not in inherit[0]
        none = subagent_specs(
            {
                "subagents": [
                    {"name": "n", "description": "d", "systemPrompt": "p", "tools": "none"}
                ]
            }
        )
        assert none[0]["tools"] == []
