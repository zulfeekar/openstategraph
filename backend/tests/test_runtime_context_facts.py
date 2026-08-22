"""What `Runtime.context` actually does **in this installation** — organisms-first-class/41.

`docs/decisions/runtime-context.md` is a design, and a design rests on library
facts. This repository has now been burned twice in one week by a documented
claim that was false when run (`5a8016c`'s `checkpointer=False`, `bb8cec4`'s
recursion floor), so every load-bearing sentence of that document that can be
executed is executed here instead of asserted there.

Nothing below builds the feature. These are **pins on LangGraph, LangChain and
deepagents as installed**, so the day one of them changes the design's premises
this file goes red rather than the document going quietly wrong.

The ones that matter most are in `TestWhatTheSchemaDoesAndDoesNotEnforce`.
The docs describe `context_schema` as "the shape of that data", which reads
like validation; what it actually is depends on the kind of class, was not
written down anywhere, and decides the design. A dataclass schema is
*constructed* from the caller's mapping, so it happens to reject an undeclared
or a missing key — as a raw `TypeError` naming a class the workflow author
never wrote. A TypedDict schema checks nothing. Neither checks a value's type.
And a run supplying no context at all fails at whichever node touches
`runtime.context` first, with a bare `AttributeError` naming neither the key
nor the run. That is why the design mints a dataclass *and* still validates at
the door.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, wrap_model_call
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

#: Obvious placeholders. A design about tenants and user ids is exactly where a
#: real-looking identity slips into a repository, so these are unmistakable.
TENANT = "tenant-placeholder"
USER = "user-placeholder"


@dataclass
class Ctx:
    tenant: str
    user_id: str


class Loose(TypedDict):
    tenant: str


class S(TypedDict):
    out: str


def _graph(node: Any, schema: Any) -> Any:
    g = StateGraph(S, context_schema=schema)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile()


class ScriptedModel(GenericFakeChatModel):
    """A model that emits a fixed script of tool calls and then a final answer.

    `RespondingModel` in `conftest` answers by predicate and never calls a
    tool, and the two facts this file needs — that a *tool* and a *subagent's*
    tool see the context — are only reachable by actually calling one.
    """

    script: list[Any] = []
    i: int = 0

    def __init__(self, script: list[Any]) -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "script", script)
        object.__setattr__(self, "i", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
        step = self.script[min(self.i, len(self.script) - 1)]
        object.__setattr__(self, "i", self.i + 1)
        if isinstance(step, tuple):
            name, args = step
            message = AIMessage(
                content="", tool_calls=[{"name": name, "args": args, "id": f"call-{self.i}"}]
            )
        else:
            message = AIMessage(content=str(step))
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001, ANN202
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)


class TestTheThreeReadDoors:
    """A node, a middleware and a tool each reach the same per-run values.

    These are the three read sides the design names, and all three are the
    docs' own claim — confirmed here by running them rather than by citing the
    page they came from.
    """

    def test_a_node_reads_it_from_its_second_parameter(self) -> None:
        def node(state: S, runtime: Runtime[Ctx]) -> S:
            return {"out": f"{runtime.context.tenant}/{runtime.context.user_id}"}

        result = _graph(node, Ctx).invoke({"out": ""}, context=Ctx(tenant=TENANT, user_id=USER))
        assert result["out"] == f"{TENANT}/{USER}"

    def test_a_middleware_and_a_tool_both_read_it(self) -> None:
        seen: dict[str, Any] = {}

        @tool
        def probe(query: str, runtime: ToolRuntime) -> str:
            """Record what the tool could see."""
            seen["tool"] = runtime.context
            return "probed"

        @wrap_model_call
        def spy(request: ModelRequest, handler):  # noqa: ANN001, ANN202
            seen.setdefault("middleware", request.runtime.context)
            return handler(request)

        agent = create_agent(
            model=ScriptedModel([("probe", {"query": "x"}), "done"]),
            tools=[probe],
            middleware=[spy],
            context_schema=Ctx,
        )
        agent.invoke(
            {"messages": [{"role": "user", "content": "go"}]},
            context=Ctx(tenant=TENANT, user_id=USER),
        )

        assert seen["middleware"] == Ctx(tenant=TENANT, user_id=USER)
        assert seen["tool"] == Ctx(tenant=TENANT, user_id=USER)


class TestWhatTheSchemaDoesAndDoesNotEnforce:
    """`context_schema` declares a shape, and how much of it is *enforced*
    depends entirely on which kind of class you declare — which the docs do not
    say, and which decides the design.

    A **dataclass** schema is constructed from whatever the caller passed, so
    key names and required keys are enforced as a side effect of
    `__init__`. A **TypedDict** schema is not constructed at all, so nothing is
    checked. Neither checks *types*, and neither produces an error a workflow
    author could act on.

    Hence two settled decisions in the design: mint a dataclass, and still
    validate at the door.
    """

    def test_a_dataclass_schema_coerces_a_plain_dict(self) -> None:
        def node(state: S, runtime: Runtime[Ctx]) -> S:
            return {"out": repr(runtime.context)}

        result = _graph(node, Ctx).invoke(
            {"out": ""}, context={"tenant": TENANT, "user_id": USER}
        )
        assert result["out"] == repr(Ctx(tenant=TENANT, user_id=USER))

    @pytest.mark.parametrize(
        ("label", "supplied"),
        [
            ("an undeclared key", {"tenant": TENANT, "user_id": USER, "undeclared": 1}),
            ("a missing required key", {"user_id": USER}),
        ],
    )
    def test_a_dataclass_schema_rejects_the_wrong_keys_but_says_so_in_python(
        self, label: str, supplied: dict[str, Any]
    ) -> None:
        def node(state: S, runtime: Runtime[Ctx]) -> S:
            return {"out": repr(runtime.context)}

        with pytest.raises(TypeError) as caught:
            _graph(node, Ctx).invoke({"out": ""}, context=supplied)
        # It refuses — but as `Ctx.__init__()`, naming a class the author never
        # wrote and never saw. Correct behaviour, unusable message.
        assert "__init__()" in str(caught.value), label

    def test_no_schema_checks_the_type_of_a_value(self) -> None:
        def node(state: S, runtime: Runtime[Ctx]) -> S:
            return {"out": repr(runtime.context.tenant)}

        result = _graph(node, Ctx).invoke({"out": ""}, context={"tenant": 123, "user_id": USER})
        assert result["out"] == "123"

    def test_a_typeddict_schema_enforces_nothing_at_all(self) -> None:
        def node(state: S, runtime: Runtime[Loose]) -> S:
            return {"out": str(runtime.context)}

        result = _graph(node, Loose).invoke(
            {"out": ""}, context={"tenant": TENANT, "undeclared": 1}
        )
        assert "undeclared" in result["out"]

    def test_supplying_no_context_fails_at_the_reader_not_at_the_door(self) -> None:
        def node(state: S, runtime: Runtime[Ctx]) -> S:
            return {"out": runtime.context.tenant}

        with pytest.raises(AttributeError) as caught:
            _graph(node, Ctx).invoke({"out": ""})
        # Names neither the key nor the run: the error a person would have to
        # debug if the platform passed this channel through unguarded.
        assert "NoneType" in str(caught.value)


class TestItIsASecondChannelBesideConfigurable:
    """`context` and `configurable` coexist; neither shadows the other.

    This is the fact that lets the design keep identity where `536f495` put it
    — the four keys stay server-determined in `configurable` — instead of
    migrating it into a channel any caller may write.
    """

    def test_both_arrive_on_the_same_run(self) -> None:
        def node(state: S, runtime: Runtime[Loose]) -> S:
            configurable = get_config().get("configurable") or {}
            return {"out": f"{runtime.context['tenant']}|{configurable.get('user_email')}"}

        result = _graph(node, Loose).invoke(
            {"out": ""},
            context={"tenant": TENANT},
            config={"configurable": {"user_email": "someone@example.invalid"}},
        )
        assert result["out"] == f"{TENANT}|someone@example.invalid"


class TestSubagentsAreNotIsolatedFromIt:
    """The deepagents propagation claim, verified rather than inherited.

    `CLAUDE.md` says a subagent "never sees the parent's message history or
    graph state". That remains true and is not what this measures. Runtime
    context is a **third** thing, and it crosses: the parent's values reach a
    tool running inside the subagent unchanged. The design's honest sentence
    depends on this being observed, so it is observed.
    """

    def test_a_parents_context_reaches_a_tool_inside_a_subagent(self) -> None:
        deepagents = pytest.importorskip("deepagents")
        seen: dict[str, Any] = {}

        @tool
        def probe(query: str, runtime: ToolRuntime) -> str:
            """Record what a tool inside the subagent could see."""
            seen["subagent_tool"] = runtime.context
            return "probed"

        agent = deepagents.create_deep_agent(
            model=ScriptedModel(
                [("task", {"description": "do it", "subagent_type": "worker"}), "parent done"]
            ),
            tools=[],
            subagents=[
                {
                    "name": "worker",
                    "description": "a worker",
                    "system_prompt": "you are a worker",
                    "tools": [probe],
                    "model": ScriptedModel([("probe", {"query": "y"}), "subagent done"]),
                }
            ],
            context_schema=Ctx,
        )
        agent.invoke(
            {"messages": [{"role": "user", "content": "go"}]},
            context=Ctx(tenant=TENANT, user_id=USER),
        )

        assert seen["subagent_tool"] == Ctx(tenant=TENANT, user_id=USER)


class TestOnlyTheCompilerDeclaresAContextSchema:
    """The measurement that dated the design, updated the day it stopped holding.

    Until `organisms-first-class/69` this class was `TestNothingHereUsesItYet`
    and asserted that **no** module of `openstategraph/` contained the string
    `context_schema=`. That was the measurement the design rested on, and it is
    now false on purpose: the compiler mints one.

    It is updated rather than deleted because the fact worth pinning was never
    "zero" — it was **where**. `context_schema` is a graph-assembly parameter
    and a LangGraph type name, so it belongs at exactly one seam: the
    `StateGraph(...)` call in the compiler. A second one anywhere would be
    either a node family growing a graph-assembly concern (`CLAUDE.md`:
    `retry_policy`/`timeout`/`cache_policy` live on the workflow) or a
    LangGraph type name leaking towards `workflow.json` and `core/`
    (portability guardrail 4). So the census stays, and it is now a census of
    one.
    """

    #: The one seam. A file added here needs the argument for why a second
    #: place assembles a graph, not just a passing test.
    ALLOWED = {"compile/workflow_compiler.py"}

    def test_only_the_compile_seam_declares_a_context_schema(self) -> None:
        from pathlib import Path

        import openstategraph

        root = Path(openstategraph.__file__).parent
        declaring = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if "context_schema=" in path.read_text(encoding="utf-8")
        }
        assert declaring == self.ALLOWED, (
            "`context_schema=` belongs to graph assembly and to nowhere else. "
            f"Unexpected: {sorted(declaring - self.ALLOWED)}; missing: "
            f"{sorted(self.ALLOWED - declaring)}."
        )

    def test_the_editor_side_still_never_names_it(self) -> None:
        """`core/` sees JSON field descriptors and no LangGraph vocabulary."""
        from pathlib import Path

        import openstategraph

        core = Path(openstategraph.__file__).parents[2] / "src" / "core"
        if not core.is_dir():  # pragma: no cover - a backend-only checkout
            pytest.skip("no src/core in this checkout")
        offenders = [
            path.name
            for path in core.rglob("*.ts")
            if "context_schema" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []
