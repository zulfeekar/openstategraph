"""A mount declares how long its child's own state lives.

`organisms-first-class` 30.

**Measured first, before anything changed.** A parent whose one real step
mounts a child, invoked **twice on one `thread_id`** through a real
`WorkflowCompiler` with an `InMemorySaver`, spying on what the mount closure
actually hands the child:

| call | messages the child receives | messages it ends with |
| --- | --- | --- |
| 1 | 1 (a copy of the parent's) | 2 |
| 2 | 3 (a copy of the parent's) | 4 |

The child was compiled with **no `checkpointer` argument at all**, so it was
per-invocation in every document this product has ever saved, and the only
thing crossing the boundary was the `messages` copy. Everything the child
itself wrote on call 1 — the twenty keys `RunState` carries back, `answer`,
`outputs`, `decisions`, `attempts`, `routes`, `verdicts`, `revisions`,
`feedback`, `subtasks`, `worker_results`, `tool_use`, `unmet_tools`, `retries`,
`redactions`, `forced`, `unrouted`, `budget_stops`, `nested_outputs` — was
discarded, and call 2 began from `{"question", "messages", "attempts": 0,
"decisions": {}, "outputs": {}}`.

**What `docs-langchain` says (installed 1.2.10,
`langgraph/use-subgraphs.mdx`, "Subgraph persistence"):** the `checkpointer`
parameter on `.compile()` is a tri-state — `None` (per-invocation, inherits the
parent's checkpointer so interrupts and durable execution work within one
call), `True` (per-thread, "the subagent's conversation history and data
accumulate across calls on the same thread"), `False` (stateless, "cannot
pause/resume"). The same page carries the warning this field must not be
offered without: stateful subgraphs **conflict under parallel calls to the same
subgraph**, because those calls write to one checkpoint namespace.

**Is this the isolation `3f688e5` protected?** No, and the difference is the
whole judgement. That commit refused a *shared decrementing allowance* because
it would make a package answer differently by **position** — nobody asked for
it, and `CLAUDE.md`'s "one isolated step — task in, answer out" is the promise
a mount makes by default. Per-thread memory makes a mount answer differently by
**history**, and only when a developer wrote it on that mount's card. The
default is untouched and is pinned below to be byte-identical.

**It does not overlap `memory.py`.** That is a `Store` — `save_memory`, the
`user` and `workflow` namespaces, a fact an agent deliberately writes, durable
across threads and across runs. This is the child's own graph checkpoint on one
thread. Different lifetime, different writer, different reader; the mount
already isolates the Store namespace and still does.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from conftest import RespondingModel
from openstategraph.compile.mount_persistence import (
    MOUNT_PERSISTENCE_MODES,
    carries_the_parents_dialogue,
    mount_checkpointer,
    mount_persistence,
)
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

CHILD: dict[str, Any] = {
    "version": 3,
    "name": "child",
    "nodes": [
        {"id": "c-in", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "c-out", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "c-in", "portId": "text"},
            "target": {"nodeId": "c-out", "portId": "result"},
        }
    ],
}


def _parent(mode: str | None) -> dict[str, Any]:
    """Input → mount → output. `None` is a document saved before this ticket."""
    data: dict[str, Any] = {"workflow": "child-flow"}
    if mode is not None:
        data["persistence"] = mode
    return {
        "version": 3,
        "name": "parent",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "mount1",
                "type": "workflow.subgraph",
                "position": {"x": 200, "y": 0},
                "data": data,
            },
            {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "mount1", "portId": "input"},
            },
            {
                "source": {"nodeId": "mount1", "portId": "output"},
                "target": {"nodeId": "out1", "portId": "input"},
            },
        ],
    }


class _Turns:
    """What the mount closure handed the child, and what the child ended with.

    Asked of the child's own `invoke`, which is the only place the answer
    exists: the mount is a **closure**, so nothing LangGraph exposes can say
    what state crossed it.
    """

    def __init__(self, mode: str | None) -> None:
        document = _parent(mode)
        runtime = NodeRuntime(
            document_loader={"child-flow": CHILD}.__getitem__,
            model=RespondingModel(rules=[]),
        )
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        self.child = runtime.mounted_graphs[safe_name("mount1")].graph
        real = self.child.invoke
        self.received: list[int] = []
        self.ended_with: list[int] = []

        self.finals: list[dict[str, Any]] = []

        def spy(state: dict[str, Any], config: Any = None, **kwargs: Any) -> Any:
            final = real(state, config, **kwargs)
            self.received.append(len(state.get("messages") or []))
            self.ended_with.append(len(final.get("messages") or []))
            self.finals.append(dict(final))
            return final

        self.child.invoke = spy  # type: ignore[method-assign]
        config = {"configurable": {"thread_id": "one-thread", "workflow_slug": "parent-flow"}}
        for question in ("What did we conclude?", "And now?"):
            graph.invoke(
                {"question": question, "attempts": 0, "decisions": {}, "outputs": {}}, config
            )


@pytest.fixture(scope="module")
def default_mount() -> _Turns:
    """A document with no `persistence` key — every document saved before 30."""
    return _Turns(None)


@pytest.fixture(scope="module")
def per_thread_mount() -> _Turns:
    return _Turns("per-thread")


@pytest.fixture(scope="module")
def stateless_mount() -> _Turns:
    return _Turns("stateless")


class TestTheDefaultMountIsByteIdentical:
    """The inverse that would go red if opting in were not required.

    This is the isolation regression `3f688e5` refused in its own shape: a
    mount nobody opted in must answer the same wherever it sits and whatever
    ran before it.
    """

    def test_it_compiles_with_no_checkpointer_argument(self, default_mount: _Turns) -> None:
        """`None` is what omitting the argument always meant, and the doc's
        per-invocation mode — the child still inherits the parent's
        checkpointer, which is what keeps `interrupt()` working inside a call."""
        assert default_mount.child.checkpointer is None

    def test_it_still_receives_the_parents_dialogue(self, default_mount: _Turns) -> None:
        """The measurement at the top of this file, unchanged: 1 then 3."""
        assert default_mount.received == [1, 3]

    def test_and_an_explicit_per_invocation_says_the_same_thing(self) -> None:
        explicit = _Turns("per-invocation")
        assert explicit.child.checkpointer is None
        assert explicit.received == [1, 3]

    def test_an_invented_mode_is_resolved_to_the_default(self) -> None:
        """Strict in trusting: a hand-edited value is not acted on."""
        invented = _Turns("remembers-everything-forever")
        assert invented.child.checkpointer is None
        assert invented.received == [1, 3]


class TestAPerThreadMountRemembersItsOwnTurn:
    """The capability the ticket says is inexpressible."""

    def test_the_child_compiles_per_thread(self, per_thread_mount: _Turns) -> None:
        assert per_thread_mount.child.checkpointer is True

    def test_its_own_history_accumulates_across_the_two_calls(
        self, per_thread_mount: _Turns
    ) -> None:
        """Call 1 leaves the child holding two messages; call 2 ends with four,
        which it can only do by having started from its own checkpoint."""
        assert per_thread_mount.ended_with == [2, 4]

    def test_and_it_is_told_none_of_the_parents_dialogue(
        self, per_thread_mount: _Turns
    ) -> None:
        """Measured before this was written: copying the parent's messages on
        top of the child's own checkpoint left five where four had been said.
        A per-thread child owns its history — nobody hands it one."""
        assert per_thread_mount.received == [0, 0]

    def test_which_is_the_only_mode_that_withholds_it(self) -> None:
        assert [m for m in MOUNT_PERSISTENCE_MODES if not carries_the_parents_dialogue(m)] == [
            "per-thread"
        ]


class TestAStatelessMountKeepsNoCheckpoint:
    def test_it_compiles_stateless(self, stateless_mount: _Turns) -> None:
        assert stateless_mount.child.checkpointer is False

    def test_and_the_dialogue_copy_is_its_only_continuity(
        self, stateless_mount: _Turns
    ) -> None:
        """It has no history of its own to keep, so the copy is unchanged —
        withholding it here would take away the one thing it had."""
        assert stateless_mount.received == [1, 3]


class TestTheTriStateIsTheDocsTriState:
    """Three modes, mapping onto the three values `.compile()` accepts."""

    def test_every_mode_maps_to_one_checkpointer_argument(self) -> None:
        assert [mount_checkpointer(mode) for mode in MOUNT_PERSISTENCE_MODES] == [
            None,
            True,
            False,
        ]

    def test_absence_is_the_default_rather_than_an_error(self) -> None:
        assert mount_persistence(None) == "per-invocation"
        assert mount_persistence("") == "per-invocation"
        assert mount_persistence(7) == "per-invocation"


class TestWhatPerThreadDoesNotCarry:
    """The limit on the claim, measured rather than assumed.

    A child's own `_input` node writes a `RESET` over the per-turn scratch on
    **every** invoke — `answer`, `feedback`, `attempts`, `subtasks`,
    `worker_results` and `revisions` — and that runs inside a per-thread child
    exactly as it runs inside a per-invocation one. So per-thread does not mean
    "the whole of last turn's state is still here". It means the child's own
    **history** and its **merge-reduced** records survive: `messages`, and the
    node-keyed dicts (`outputs`, `decisions`, `routes`, `verdicts`, `tool_use`,
    `unmet_tools`, `retries`, `redactions`, `forced`, `unrouted`,
    `budget_stops`, `nested_outputs`).

    That RESET is the reason this field is safe to ship rather than a defect it
    hides: `workflow-gallery` 21 put it there because "a checkpointed thread
    that carried a spent budget forward would hand turn two a grader with no
    laps left", and a per-thread mount is exactly the checkpointed thread it
    was written for.
    """

    def test_a_per_thread_child_starts_turn_two_with_a_full_revision_budget(
        self, per_thread_mount: _Turns
    ) -> None:
        assert per_thread_mount.finals[1].get("revisions") == {}
        assert per_thread_mount.finals[1].get("attempts") == 0

    def test_and_does_not_answer_turn_two_with_turn_ones_answer(
        self, per_thread_mount: _Turns
    ) -> None:
        assert per_thread_mount.finals[0].get("answer") == "What did we conclude?"
        assert per_thread_mount.finals[1].get("answer") == "And now?"

    def test_the_per_invocation_child_reads_identically_on_both_counts(
        self, default_mount: _Turns
    ) -> None:
        """Which is the point: the difference per-thread buys is the history,
        not the scratch — so a claim that a mount "remembers what it concluded"
        is true of the conversation and not of the conclusion."""
        assert default_mount.finals[1].get("revisions") == {}
        assert default_mount.finals[1].get("answer") == "And now?"
