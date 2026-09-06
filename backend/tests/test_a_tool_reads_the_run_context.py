"""A tool reads what the caller supplied — `organisms-first-class/73`.

Step 7 of the seven in `docs/decisions/runtime-context.md`, and the last read
door. 71 gave a node `run_context()`; 72 gave a prompt a generated **Context**
section behind a per-field opt-in. This closes the chain at the one reader the
opt-in exists *for*: a run-context field is where an API handle goes, and a
handle has to be able to reach a tool without a model ever seeing it.

**Measured before anything was built, because the ticket's brief was wrong
twice.** `langgraph.runtime.get_runtime()` already works from inside
`BaseTool._execute` — our `as_langchain_tool` wrapper runs inside the agent
node, and the runtime is a contextvar, not an injected parameter — so
`run_context()` was reachable from a tool the day 71 landed. What was missing
was a *promised* name to reach it by: `openstategraph.compile` is Tier 2, and
a tool author following `docs/stability.md` had nothing to import.

**So the accessor is a module-level Tier 1 name, not a member on `BaseTool`.**
The brief asked for a member "mirroring `prebuilt_session._configurable()`" —
and that method no longer exists: ticket 68 (`bf74daa`) deleted it and made it
the module-level `run_identity()`. Followed faithfully, the mirror points at a
module function. Three further reasons, in the order they weigh:

- `5549a1b` priced exactly this move and rejected it — a member on `BaseTool`
  is a published Tier 1 surface every future tool author must read and answer.
- `ITool` is a `Protocol` on purpose, so a tool need not subclass `BaseTool`;
  a member on the base serves only the subclasses.
- The three seams a tool already reaches are all module-level
  (`get_config()`, `get_store()`), so a fourth is the shape authors know.

**What would still be green if the wrong thing were built?** A test asserting
`run_context()` returns a dict, called from pytest's own thread — it would pass
against a run that supplied nothing. So the demonstration below builds a real
package with a real `tools/` folder, loads it with the real `load_workflow`,
runs it, and asserts the supplied value in the tool's **output** and in the
answer that came back. The inverses are the load-bearing half.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openstategraph import load_workflow, run_context

#: Obvious placeholders. A feature about tenants and support handles is exactly
#: where a real-looking identity slips into a repository.
TENANT = "tenant-placeholder"
HANDLE = "handle-placeholder"

DECLARATION = [
    {"key": "tenant", "type": "string", "label": "Tenant", "required": True},
    {"key": "supportHandle", "type": "string", "label": "Support handle", "default": ""},
]

TOOL_MODULE = '''
"""A workflow-scoped tool that answers out of the run's context."""

from openstategraph import run_context
from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult


class ProbeTool(BaseTool):
    name = "probe_tenant"
    description = "Report which tenant this run is for."
    node_type = "tool.tenant-probe"
    Args = NoArgs

    def _execute(self, args):
        context = run_context()
        return ToolResult(
            content="tenant={} handle={}".format(
                context.get("tenant", "-"), context.get("supportHandle", "-")
            )
        )
'''


class EchoingModel(GenericFakeChatModel):
    """Calls the tool once, then answers with what the tool said.

    Two jobs, and the second is why it is not `ScriptedModel`: `calls` records
    every message list handed to the provider, which is how `52ff8e0` and
    `4df17c4` proved what did and did not reach a model. The final answer is
    *derived from the tool's result* rather than scripted, so an answer
    carrying the tenant is evidence the value travelled the whole way.
    """

    calls: list[list[Any]] = []
    i: int = 0

    def __init__(self) -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "i", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
        self.calls.append(list(messages))
        object.__setattr__(self, "i", self.i + 1)
        tool_said = [
            str(m.content) for m in messages if m.__class__.__name__ == "ToolMessage"
        ]
        if tool_said:
            message = AIMessage(content=tool_said[-1])
        elif self.i == 1:
            message = AIMessage(
                content="",
                tool_calls=[{"name": "probe_tenant", "args": {}, "id": "call-1"}],
            )
        else:
            message = AIMessage(content="no tool was called")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001, ANN202
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)

    def everything_sent(self) -> str:
        return "\n".join(str(m.content) for call in self.calls for m in call)


def _document(context: Any, rules: str = "Answer with what the tool told you.") -> dict[str, Any]:
    document: dict[str, Any] = {
        "version": 1,
        "name": "tenant probe",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "agent1",
                "type": "agent.llm",
                "position": {"x": 200, "y": 0},
                "data": {"role": "Support", "systemPrompt": rules},
            },
            {
                "id": "tool1",
                "type": "tool.tenant-probe",
                "position": {"x": 200, "y": 200},
                "data": {},
            },
            {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "agent1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "tool1", "portId": "tool"},
                "target": {"nodeId": "agent1", "portId": "tools"},
            },
            {
                "source": {"nodeId": "agent1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }
    if context is not None:
        document["settings"] = {"context": context}
    return document


def _package(tmp_path: Path, document: dict[str, Any]) -> Path:
    directory = tmp_path / "tenant-probe"
    (directory / "tools").mkdir(parents=True)
    (directory / "tools" / "__init__.py").write_text("")
    (directory / "tools" / "probe.py").write_text(TOOL_MODULE)
    (directory / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "tenant probe",
                "savedAt": "2026-08-22T00:00:00Z",
                "document": document,
                "published": True,
            }
        )
    )
    return directory


def _run(directory: Path, model: EchoingModel, **invoke: Any) -> str:
    compiled = load_workflow(directory, model=model)
    result = compiled.graph.invoke(
        {"messages": [], "question": "who am I?"},
        config={"configurable": {"thread_id": "thread-placeholder"}},
        **invoke,
    )
    return str(result.get("answer") or result.get("outputs", {}).get("out1") or "")


# --------------------------------------------------------------------------- #
# The demonstration.
# --------------------------------------------------------------------------- #


class TestASuppliedValueReachesAToolsOutput:
    def test_the_tool_answers_out_of_the_run_it_is_running_in(self, tmp_path: Path) -> None:
        directory = _package(tmp_path, _document(DECLARATION))
        model = EchoingModel()

        answer = _run(directory, model, context={"tenant": TENANT, "supportHandle": HANDLE})

        assert f"tenant={TENANT}" in answer
        assert f"handle={HANDLE}" in answer

    def test_two_callers_of_one_workflow_get_two_answers(self, tmp_path: Path) -> None:
        """Not provable from one run: a tool that hard-coded anything, or that
        read the *declaration* rather than the run, passes the test above."""
        directory = _package(tmp_path, _document(DECLARATION))

        first = _run(directory, EchoingModel(), context={"tenant": TENANT})
        second = _run(directory, EchoingModel(), context={"tenant": "other-placeholder"})

        assert f"tenant={TENANT}" in first
        assert "tenant=other-placeholder" in second

    def test_a_declared_default_is_what_an_omitting_caller_reads(self, tmp_path: Path) -> None:
        declaration = [
            DECLARATION[0],
            {"key": "supportHandle", "type": "string", "default": "desk-placeholder"},
        ]
        directory = _package(tmp_path, _document(declaration))

        answer = _run(directory, EchoingModel(), context={"tenant": TENANT})

        assert "handle=desk-placeholder" in answer


class TestTheValueReachesTheToolWithoutReachingTheModel:
    """72's opt-in is default-off, and this is the case it exists to enable.

    A tool is not a model. The asymmetry the opt-in rests on — a value sent to
    a provider cannot be un-sent — is about *the provider*, and a tool running
    in this process sends nothing anywhere. So the opt-in governs the prompt
    and only the prompt: it is the gate on the model door, not a gate on the
    value. Anything else would make a declared handle unreadable by the one
    component that has a legitimate use for it, which is the feature.
    """

    def test_an_unopted_value_reaches_the_tool_and_never_the_prompt(
        self, tmp_path: Path
    ) -> None:
        directory = _package(tmp_path, _document(DECLARATION))
        model = EchoingModel()

        answer = _run(directory, model, context={"tenant": TENANT, "supportHandle": HANDLE})

        assert f"handle={HANDLE}" in answer
        first_call = "\n".join(str(m.content) for m in model.calls[0])
        assert HANDLE not in first_call
        assert TENANT not in first_call

    def test_the_tool_result_is_the_only_route_the_value_took(self, tmp_path: Path) -> None:
        """It reaches the model *afterwards*, as the tool's answer — which is
        the author's own decision about what to return, not ours."""
        directory = _package(tmp_path, _document(DECLARATION))
        model = EchoingModel()

        _run(directory, model, context={"tenant": TENANT})

        assert TENANT in model.everything_sent()
        assert TENANT not in "\n".join(str(m.content) for m in model.calls[0])


# --------------------------------------------------------------------------- #
# The inverses.
# --------------------------------------------------------------------------- #


class TestAWorkflowThatDeclaresNothingIsUnchanged:
    def test_the_accessor_is_empty_and_the_run_still_answers(self, tmp_path: Path) -> None:
        directory = _package(tmp_path, _document(None))

        answer = _run(directory, EchoingModel())

        assert "tenant=-" in answer
        assert "handle=-" in answer

    def test_outside_a_run_it_is_empty_rather_than_an_exception(self) -> None:
        """A tool called from a script is a normal thing to do."""
        assert run_context() == {}

    def test_a_declared_key_nobody_supplied_is_empty_not_missing(self, tmp_path: Path) -> None:
        directory = _package(tmp_path, _document(DECLARATION))

        answer = _run(directory, EchoingModel(), context={"tenant": TENANT})

        assert "handle=" in answer


class TestTheAccessorIsAPromisedName:
    """The whole change, from a tool author's side: a Tier 1 import."""

    def test_it_is_importable_from_the_top_level(self) -> None:
        import openstategraph

        assert "run_context" in openstategraph.__all__
        assert openstategraph.run_context is run_context

    def test_it_is_the_one_the_compiler_already_had(self) -> None:
        """Re-exported, never re-implemented — a second reader is a second
        chance to learn a normalisation the first one does not."""
        from openstategraph.compile.run_context import run_context as internal

        assert run_context is internal


class TestTheContractClauseNamesIt:
    def test_the_run_seams_clause_names_the_accessor(self) -> None:
        from openstategraph.generated_module_contract import CLAUSES

        clause = next(c for c in CLAUSES if c.id == "run-seams")

        assert "run_context()" in clause.rule

    def test_every_seam_of_that_clause_resolves_here(self) -> None:
        """The point of `seam`: a clause naming something this installation
        does not have is `ToolRuntime` all over again."""
        from openstategraph.generated_module_contract import CLAUSES, resolve_seam

        clause = next(c for c in CLAUSES if c.id == "run-seams")

        assert "openstategraph:run_context" in clause.seam
        assert all(resolve_seam(symbol) is not None for symbol in clause.seam)

    def test_a_tool_still_cannot_read_graph_state(self) -> None:
        """The half of the clause that did not change, and must not."""
        from openstategraph.generated_module_contract import UNWIRED_SEAMS

        assert "ToolRuntime" in UNWIRED_SEAMS
        assert "get_state" in UNWIRED_SEAMS


class TestASubagentsToolSeesItToo:
    """`a86b4d8` measured this for a LangChain `@tool`; a subagent is invoked
    *as a tool*, so the same must hold for one of ours. A value one node should
    hold and another should not therefore does not belong in run context, and
    the docs a tool author reads say so."""

    def test_our_tool_inside_a_deep_agent_subagent_reads_the_parents_context(
        self,
    ) -> None:
        deepagents = pytest.importorskip("deepagents")
        from dataclasses import dataclass

        from openstategraph.abc.tool import NoArgs, ToolResult
        from openstategraph.abc.tool import BaseTool

        seen: dict[str, Any] = {}

        @dataclass
        class Ctx:
            tenant: str

        class Probe(BaseTool):
            name = "probe_tenant"
            description = "Report the tenant."
            Args = NoArgs

            def _execute(self, args: Any) -> ToolResult:
                seen["subagent_tool"] = run_context()
                return ToolResult(content="probed")

        class Scripted(GenericFakeChatModel):
            script: list[Any] = []
            i: int = 0

            def __init__(self, script: list[Any]) -> None:
                super().__init__(messages=iter([]))
                object.__setattr__(self, "script", script)
                object.__setattr__(self, "i", 0)

            def _generate(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001, ANN202
                step = self.script[min(self.i, len(self.script) - 1)]
                object.__setattr__(self, "i", self.i + 1)
                if isinstance(step, tuple):
                    name, args = step
                    message = AIMessage(
                        content="",
                        tool_calls=[{"name": name, "args": args, "id": f"c-{self.i}"}],
                    )
                else:
                    message = AIMessage(content=str(step))
                return ChatResult(generations=[ChatGeneration(message=message)])

            def bind_tools(self, tools, *, tool_choice=None, **kw):  # noqa: ANN001, ANN202
                return self.bind(tools=tools, tool_choice=tool_choice, **kw)

        agent = deepagents.create_deep_agent(
            model=Scripted(
                [("task", {"description": "do it", "subagent_type": "worker"}), "parent done"]
            ),
            tools=[],
            subagents=[
                {
                    "name": "worker",
                    "description": "a worker",
                    "system_prompt": "you are a worker",
                    "tools": [Probe().as_langchain_tool()],
                    "model": Scripted([("probe_tenant", {}), "subagent done"]),
                }
            ],
            context_schema=Ctx,
        )
        agent.invoke(
            {"messages": [{"role": "user", "content": "go"}]},
            context=Ctx(tenant=TENANT),
        )

        assert seen["subagent_tool"] == {"tenant": TENANT}
