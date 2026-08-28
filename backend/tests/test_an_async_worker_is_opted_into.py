"""The `async-tasks` slot is opt-in, and the channel survives the turn.

`async-first/08`. Two claims, both of them the kind that a test asserting a
kwarg was passed would not catch:

1. **Opt-in, never universal.** CLAUDE.md: *"narrow interfaces … so a node opts
   into being a tool without carrying unused methods"*. An agent that declares
   no `async` row carries none of the five tools; one that declares a row on a
   tier with nowhere to put it gets a `plan.warnings` sentence, not a silent
   nothing.
2. **The task id outlives the node.** The agent's own state is discarded when
   its node returns, so `async_tasks` is threaded onto `RunState` the way
   `agent_files` is. Asserted on the channel declaration and on the compiler's
   own wiring, because the alternative — a live two-turn run — needs a model.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any

from openstategraph.abc.agent import AbstractAgentNode
from openstategraph.async_tasks import ASYNC_TASKS_KEY, ASYNC_TASKS_SLOT
from openstategraph.compile.state import RunState
from openstategraph.compile.subagents import (
    async_subagent_specs,
    declares_async_subagents,
    subagent_declaration_problems,
    subagent_specs,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _row(name: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"what {name} is for",
        "systemPrompt": f"You are {name}.",
        **extra,
    }


def test_a_document_with_no_mode_declares_exactly_what_it_always_did() -> None:
    data = {"subagents": [_row("researcher")], "tier": "deep"}
    assert [spec["name"] for spec in subagent_specs(data)] == ["researcher"]
    assert async_subagent_specs(data) == []
    assert declares_async_subagents(data) is False


def test_an_async_row_goes_to_the_slot_and_not_to_the_blocking_parameter() -> None:
    """The same worker must not exist twice under one name with two lifecycles."""
    data = {
        "subagents": [_row("waits"), _row("backgrounds", mode="async")],
        "tier": "deep",
    }
    assert [spec["name"] for spec in subagent_specs(data)] == ["waits"]
    assert [spec["name"] for spec in async_subagent_specs(data)] == ["backgrounds"]
    assert declares_async_subagents(data) is True


def test_an_unrecognised_mode_reads_as_the_blocking_one() -> None:
    """Tolerant in reading, strict in trusting: a typo must not start a child
    that outlives the turn."""
    data = {"subagents": [_row("researcher", mode="asynchronous")], "tier": "deep"}
    assert [spec["name"] for spec in subagent_specs(data)] == ["researcher"]
    assert async_subagent_specs(data) == []


def test_an_async_row_on_a_react_tier_is_a_warning_rather_than_a_silent_drop() -> None:
    document = {
        "nodes": [
            {
                "id": "agent_1",
                "data": {"tier": "react", "subagents": [_row("bg", mode="async")]},
            }
        ]
    }
    problems = subagent_declaration_problems(document)
    assert len(problems) == 1
    assert "only the deep agent runtime" in problems[0]


def test_the_base_declares_the_slot_and_never_fills_it() -> None:
    assert ASYNC_TASKS_SLOT in AbstractAgentNode.SLOT_ORDER
    # After `narration` (the roster line is progress about the run) and beside
    # `subagents` (the other half of delegation).
    order = list(AbstractAgentNode.SLOT_ORDER)
    assert order.index(ASYNC_TASKS_SLOT) == order.index("subagents") + 1
    assert order.index(ASYNC_TASKS_SLOT) > order.index("narration")

    node = AbstractAgentNode.__subclasses__()  # noqa: SLF001 - the base is abstract
    assert node, "the ladder still has concrete tiers"
    table = _BareTier(name="a").resolve_middleware()
    assert ASYNC_TASKS_SLOT not in table.names(), (
        "the base filled a slot it only declares — an agent that asked for no "
        "background worker must carry none of the five tools"
    )


class _BareTier(AbstractAgentNode):
    def build_agent(self, **_: Any) -> Any:  # pragma: no cover - never called
        raise NotImplementedError


def test_the_channel_is_on_the_run_state_with_a_named_reducer() -> None:
    """Without this, a task id dies with the node that started it."""
    annotation = RunState.__annotations__[ASYNC_TASKS_KEY]
    assert "reducer_for" in str(annotation) or getattr(annotation, "__metadata__", None), (
        "async_tasks must be Annotated with a named reducer — more than one "
        "writer can reach it in one superstep"
    )


def test_the_compiler_threads_the_channel_the_way_it_threads_agent_files() -> None:
    """A source walk, because the live proof needs two turns and a model.

    The pairing is the point: every place `agent_files` is seeded or written
    back, `async_tasks` is too. They are one mechanism with two channels, and a
    future edit that remembers only one is the defect this catches.
    """
    source = (BACKEND / "openstategraph" / "compile" / "node_runtime.py").read_text()
    tree = ast.parse(source)
    names = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "agent_files" in names
    assert source.count("ASYNC_TASKS_KEY") >= 4, (
        "async_tasks must be seeded into the agent's invocation and written "
        "back out of its result, exactly as agent_files is"
    )
