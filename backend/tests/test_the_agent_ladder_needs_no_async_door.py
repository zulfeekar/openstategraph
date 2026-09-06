"""`async-first/05`, fourth family: the agent ladder needs nothing, and here is
why that is a finding rather than an omission.

The ticket named four ladders. Three of them — router, grader, orchestrator —
call a model themselves and grew an awaitable twin of the verb that does it.
The agent ladder does not call a model at all: `build()` **constructs** a
Runnable and hands it back, and the caller awaits `ainvoke` on the thing it was
given. There is no `self.model.invoke(...)` anywhere in `abc/agent.py` to make
awaitable, and an `abuild()` would have been public surface with nothing behind
it — a second spelling of a construction step that never blocks.

This file is the pin, because "nothing to do here" is the claim most likely to
stop being true quietly. The day the agent ladder grows a model call, the first
test below goes red and whoever wrote it is told what the other three families
already did about it.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from langchain_core.runnables import RunnableLambda

from openstategraph.abc.agent import (
    AbstractAgentNode,
    BaseAgentNode,
    CustomGraphNode,
    DeepAgentNode,
    IAgent,
    ReactAgentNode,
)


def _calls_in(module_source: str) -> set[str]:
    """Every attribute called anywhere in the module, by attribute name."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(module_source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            found.add(node.func.attr)
    return found


class TestTheLadderBuildsAndDoesNotCall:
    def test_nothing_in_the_agent_ladder_invokes_anything(self) -> None:
        import openstategraph.abc.agent as agent_module

        called = _calls_in(inspect.getsource(agent_module))

        assert "invoke" not in called, (
            "the agent ladder grew a model call. It is now the fourth family "
            "on `async-first/05` and wants an awaited twin, the way "
            "`BaseRouter.aclassify`, `BaseGrader.agrade` and "
            "`BaseOrchestrator.aplan` each have one."
        )
        assert "ainvoke" not in called
        assert "stream" not in called and "astream" not in called

    def test_build_hands_back_the_runnable_the_caller_awaits(self) -> None:
        """`CustomGraphNode` is the clearest statement of the whole shape: it
        holds a Runnable and returns it untouched. Awaiting is the caller's,
        and the object it awaits is LangChain's, not ours."""
        runnable = RunnableLambda(lambda payload: payload)

        built = CustomGraphNode(name="custom", runnable=runnable).build()

        assert built is runnable
        assert hasattr(built, "ainvoke")

    def test_no_rung_of_the_ladder_grew_an_a_prefixed_twin(self) -> None:
        """Stated as a set rather than as `not hasattr(cls, "abuild")`, so a
        differently-named door is caught too."""
        for klass in (
            AbstractAgentNode,
            BaseAgentNode,
            ReactAgentNode,
            DeepAgentNode,
            CustomGraphNode,
        ):
            twins = {
                name
                for name in dir(klass)
                if name.startswith("a")
                and not name.startswith("__")
                and name[1:] in dir(klass)
            }
            assert twins == set(), f"{klass.__name__} grew {sorted(twins)}"

    def test_iagent_still_declares_exactly_what_it_did(self) -> None:
        """`IAgent` is `runtime_checkable`, so it is untouched for the reason
        `ITool`, `IRouter`, `IGrader` and `IOrchestrator` are: a member added
        to it un-satisfies every third-party agent at the next `isinstance`,
        in their install, silently."""

        class HandWritten:
            name = "mine"

            def build(self) -> object:
                return RunnableLambda(lambda payload: payload)

        assert isinstance(HandWritten(), IAgent)


class TestTheBuildStepDoesNotBlock:
    def test_resolution_is_arithmetic_on_config_not_io(self) -> None:
        """The reason a construction step needs no thread and no door.

        `build()` is a template method over three resolvers; none of them
        reaches a network, a disk or a model. A door over it would be a thread
        bought for dictionary assembly.
        """
        source = textwrap.dedent(inspect.getsource(BaseAgentNode.build))
        called = _calls_in(source)

        assert called == {"build_agent", "resolve_model", "resolve_middleware", "resolve_prompt", "flatten"}
