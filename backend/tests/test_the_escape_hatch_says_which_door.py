"""`async-first/13` — the escape hatch keeps a loop per node call.

`12` gave the four **doors** one loop per run (`run_doors.invoke_run`). The
fifth way in is not a door:

    workflow = load_workflow("workflows/morning-brief")
    workflow.graph.invoke({...})      # still one private loop per node call

`CompiledWorkflow.graph` is documented as complete — "everything LangGraph can
do, you can do" — so a caller may drive it synchronously, reach
`compile/node_doors.both_doors`' sync door, and get one `asyncio.run` per node
call. A resource a body leaves bound to the first loop is then dead by the
second, which is `RuntimeError: Event loop is closed` out of somebody else's
library naming nothing of ours.

## The decision, and the two measurements that made it

The ticket offered three shapes. This file is the argument.

**Shape 3 — a run-scoped loop for the node door — stays rejected, and the
reason is stronger than "nothing supplies a run boundary today".** Measured on
the installed `langgraph 1.2.10`: a node body's `ensure_config()` carries no
`run_id` at all (it is `None`), and `checkpoint_ns` is *per node*, so no two
nodes in one run share it. `thread_id` is readable when a checkpointer is
configured, and is the same string across two separate `invoke` calls — it is
a **conversation** boundary, not a run one. And even a perfect run id would
not be enough: a loop needs a **close**, and a node call can observe a run
starting but never a run ending. There is no end signal, so there is no owner.

**Shape 2 — refuse at compile time — is wrong as written, and the second test
below is why.** A graph with two migrated bodies is not a graph that fails:
two `async def` nodes with nothing loop-bound in them complete through
`.invoke()` perfectly well, and so does a pair sharing a pooled
`httpx.AsyncClient`. The failure needs a resource that reaches back at the
*first* loop, which the compiler cannot see. Refusing every graph with more
than one `INTERRUPTIBLE` node would refuse working code — and `.graph` is
documented as unwrapped precisely because wrapping it is where the execution
engine this project refuses to write would begin.

**What shipped is shape 2's goal at shape 1's cost: the sentence, raised at
the failure rather than at compile.** Nothing that works today stops working;
the run that was already dead now says which door to use instead of naming a
closed loop. The documentation in `docs/what-is-this.md` stays exactly where
it is — at the point the hatch is offered — because a caller who reads it
never meets this exception at all.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from typing_extensions import TypedDict  # noqa: E402

from openstategraph.compile.node_doors import with_both_doors  # noqa: E402


class _State(TypedDict):
    trail: str


def _graph(first: Any, second: Any) -> Any:
    builder: Any = StateGraph(_State)
    builder.add_node("a", with_both_doors(first))
    builder.add_node("b", with_both_doors(second))
    builder.add_edge(START, "a")
    builder.add_edge("a", "b")
    builder.add_edge("b", END)
    return builder.compile()


class _LoopBound:
    """A body pair sharing one resource bound to the loop that first used it.

    The narrowest honest stand-in for a model client's pooled socket, and the
    same shape `tests/test_a_fan_out_answers_the_blocking_door.py` uses for
    `12`. Nothing else about it is a fake of anything.
    """

    def __init__(self) -> None:
        self.loop: Any = None

    async def _touch(self, mark: str) -> str:
        if self.loop is None:
            self.loop = asyncio.get_running_loop()
        await asyncio.sleep(0.01)
        # What a pooled connection does when it is used again: reach the loop
        # it was opened on.
        self.loop.call_soon(lambda: None)
        return mark

    async def a(self, state: _State) -> dict[str, str]:
        return {"trail": state["trail"] + await self._touch("a")}

    async def b(self, state: _State) -> dict[str, str]:
        return {"trail": state["trail"] + await self._touch("b")}


class TestTheFailureNamesTheFix:
    def test_the_sentence_names_the_async_api(self) -> None:
        """The whole of what this ticket ships.

        Before: `RuntimeError: Event loop is closed`, raised by `asyncio` out
        of somebody's connection pool, naming nothing a reader can act on.
        """
        bound = _LoopBound()

        with pytest.raises(RuntimeError) as caught:
            _graph(bound.a, bound.b).invoke({"trail": ""})

        message = str(caught.value)
        assert "ainvoke" in message
        assert "astream" in message
        assert "one event loop per node call" in message

    def test_the_original_is_still_attached(self) -> None:
        """Chained, never replaced.

        A diagnosis is a guess about somebody else's traceback, and a guess
        that eats the evidence is worse than no guess. The day a body raises
        this for a reason of its own, `__cause__` is what says so.
        """
        bound = _LoopBound()

        with pytest.raises(RuntimeError) as caught:
            _graph(bound.a, bound.b).invoke({"trail": ""})

        assert isinstance(caught.value.__cause__, RuntimeError)
        assert "Event loop is closed" in str(caught.value.__cause__)


class TestNothingThatWorkedStoppedWorking:
    """The test that rules shape 2 out, kept as a test rather than a paragraph."""

    def test_two_migrated_bodies_with_nothing_loop_bound_still_answer(self) -> None:
        """Two `INTERRUPTIBLE` nodes, driven synchronously, fine.

        So "more than one migrated body" is **not** a predicate for failure,
        and a compiler that refused on it would refuse this.
        """

        async def a(state: _State) -> dict[str, str]:
            await asyncio.sleep(0.01)
            return {"trail": state["trail"] + "a"}

        async def b(state: _State) -> dict[str, str]:
            await asyncio.sleep(0.01)
            return {"trail": state["trail"] + "b"}

        assert _graph(a, b).invoke({"trail": ""}) == {"trail": "ab"}

    def test_an_unrelated_runtime_error_is_passed_through_untouched(self) -> None:
        """Only the one message is diagnosed. Everything else is the body's."""

        async def a(state: _State) -> dict[str, str]:
            raise RuntimeError("the model refused")

        async def b(state: _State) -> dict[str, str]:  # pragma: no cover
            return state  # type: ignore[return-value]

        with pytest.raises(RuntimeError) as caught:
            _graph(a, b).invoke({"trail": ""})

        assert str(caught.value).startswith("the model refused")


class TestTheRunBoundaryIsNotThere:
    """Shape 3's premise, measured rather than assumed."""

    def test_a_node_body_has_no_run_id(self) -> None:
        from langchain_core.runnables.config import ensure_config

        seen: list[Any] = []

        async def a(state: _State) -> dict[str, str]:
            config = ensure_config()
            seen.append(
                (config.get("run_id"), (config.get("configurable") or {}).get("checkpoint_ns"))
            )
            return {"trail": "a"}

        async def b(state: _State) -> dict[str, str]:
            config = ensure_config()
            seen.append(
                (config.get("run_id"), (config.get("configurable") or {}).get("checkpoint_ns"))
            )
            return {"trail": "b"}

        _graph(a, b).invoke({"trail": ""})

        assert [run_id for run_id, _ in seen] == [None, None]
        namespaces = [ns for _, ns in seen]
        assert namespaces[0] != namespaces[1], "checkpoint_ns is per node, not per run"

    def test_thread_id_is_a_conversation_and_not_a_run(self) -> None:
        """The near-miss, ruled out: it is stable *across* runs.

        Which is correct — CLAUDE.md's vocabulary says a thread is the
        conversation — and is exactly why it cannot scope a loop. Two runs
        would share one, and neither would ever be told to close it.
        """
        from langchain_core.runnables.config import ensure_config
        from langgraph.checkpoint.memory import InMemorySaver

        seen: list[Any] = []

        async def a(state: _State) -> dict[str, str]:
            seen.append((ensure_config().get("configurable") or {}).get("thread_id"))
            return {"trail": "a"}

        builder: Any = StateGraph(_State)
        builder.add_node("a", with_both_doors(a))
        builder.add_edge(START, "a")
        builder.add_edge("a", END)
        graph = builder.compile(checkpointer=InMemorySaver())

        config = {"configurable": {"thread_id": "T1"}}
        graph.invoke({"trail": ""}, config)
        graph.invoke({"trail": ""}, config)

        assert seen == ["T1", "T1"]
