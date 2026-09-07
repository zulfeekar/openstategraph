"""`Data Analyst › 1` — a lane named after a counter.

`memory-and-replay` 40. Read out of the browser at `?w=chinook-assistant` →
History → the `eval-h02` run, counting `.past-runs__lane-head`:

    Data Analyst            8 steps
    Data Analyst · run 2    9 steps
    ...
    Data Analyst › 1       10 steps      <-- these three
    Data Analyst › 2        9 steps
    Data Analyst › 1 · run 2   22 steps

The `›` is `laneTitle` saying *a nested graph, inside Data Analyst, called
`1`*. There is no such graph, and no canvas id mangles to `1`.

**What the segment actually is**, read out of the installed LangGraph rather
than guessed: `PregelLoop.__init__` (`pregel/_loop.py`) asks the task's
`PregelScratchpad.subgraph_counter()` — an atomic counter that returns 0 the
first time — and, when it is non-zero, appends `NS_SEP + str(count)` to
`checkpoint_ns`. So `agent_sql:<task>|1` is *the same task invoking a subgraph
a second time*, and `|2` the third. It is an instance discriminator, exactly
like the `:<task-id>` this module already drops, and for the same reason: two
invocations of one node are one node that ran more than once.

Dropping it is what makes that true on screen — the lanes then key alike,
`lanes()` splits them on the superstep restart each invocation begins with,
and the panel says `· run N`, which is the sentence a reader can act on.

Narrow on purpose. A counter segment is **all digits and carries no
`:`**; a real task segment always carries one (`_algo.py` builds
`f"{ns}{NS_END}{task_id}"` before handing it to the task). Anything else is
left exactly as stored, which is the rule this module was already written to.
"""

from __future__ import annotations

from openstategraph.api import threads as thread_queries


class _Checkpoint:
    def __init__(self, namespace: str) -> None:
        self.config = {"configurable": {"thread_id": "run-1", "checkpoint_ns": namespace}}
        self.checkpoint = {
            "id": "cp-1",
            "ts": "2026-08-20T06:33:06+00:00",
            "channel_values": {"answer": "done"},
            "updated_channels": ["answer"],
        }
        self.metadata = {"step": 3, "source": "loop", "workflow_slug": "chinook-assistant"}
        self.pending_writes = ()


AGENT = "agent_sql:d725d120-517d-3fef-9e22-245a39d70ec4"


class TestTheSeamThisRuleDependsOn:
    """The rule is about a mechanism, so the mechanism is asserted here.

    A test that pins the *wording* of a rule is not a test that the wording is
    true (`every-workflow-green` 34). If LangGraph stops spelling the counter
    this way, this fails first and says so, instead of the fix quietly
    becoming decoration.
    """

    def test_langgraph_still_appends_a_subgraph_counter_to_the_namespace(self) -> None:
        import inspect

        from langgraph._internal._constants import NS_END, NS_SEP
        from langgraph._internal._scratchpad import PregelScratchpad
        from langgraph.pregel import _loop

        assert (NS_SEP, NS_END) == (thread_queries._NS_SEP, thread_queries._NS_END)
        assert "subgraph_counter" in PregelScratchpad.__dataclass_fields__
        source = inspect.getsource(_loop)
        assert "scratchpad.subgraph_counter()" in source


class TestACounterIsNotAGraph:
    def test_the_second_invocation_is_the_same_node(self) -> None:
        step = thread_queries._step(_Checkpoint(f"{AGENT}|1"))
        assert step.namespace == ["agent_sql"]
        assert step.node == "agent_sql"

    def test_and_so_is_the_third(self) -> None:
        step = thread_queries._step(_Checkpoint(f"{AGENT}|2"))
        assert step.namespace == ["agent_sql"]

    def test_a_counter_deep_in_a_mount_leaves_the_path_above_it_alone(self) -> None:
        step = thread_queries._step(_Checkpoint(f"mount1:abc|{AGENT}|1"))
        assert step.namespace == ["mount1", "agent_sql"]
        assert step.node == "agent_sql"


class TestStrictInWhatItDrops:
    def test_a_segment_carrying_a_task_id_is_never_a_counter(self) -> None:
        """`1:abc` is a node called `1` that ran — unlikely, and not ours to
        delete. The `:` is the whole difference and it is the evidence."""
        step = thread_queries._step(_Checkpoint("1:abc"))
        assert step.namespace == ["1"]

    def test_a_bare_segment_that_is_not_a_number_is_left_as_stored(self) -> None:
        step = thread_queries._step(_Checkpoint(f"{AGENT}|tools"))
        assert step.namespace == ["agent_sql", "tools"]

    def test_a_counter_is_not_read_out_of_a_longer_word(self) -> None:
        step = thread_queries._step(_Checkpoint(f"{AGENT}|step1"))
        assert step.namespace == ["agent_sql", "step1"]
