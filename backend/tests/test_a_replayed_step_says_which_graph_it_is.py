"""Forty rows, five graphs, and `Step 3 · loop` printed five times.

`memory-and-replay` 37, part 1. Read out of the browser at `?w=morning-brief`
→ History → the `example.com` run, counting `.past-runs__step-head`:

    Input · input   ×5
    Step 0 · loop   ×5
    Step 1 · loop   ×5
    Step 2 · loop   ×5
    Step 3 · loop   ×5
    Step 4 · loop   ×4
    Step 5 · loop   ×4      — 40 rows in total

They are not repeats. They are the parent graph and four agent subgraphs, each
numbering its own supersteps from zero, listed interleaved with nothing on the
row to say which is which. The replay panel that already exists is unreadable
for that one reason, and it is a *rendering* gap, not a storage gap: the
checkpointer has kept the namespace all along, and the namespace names the node
and the dispatched instance —

    ''                                          the parent graph
    'worker_web:f8e26037-68ee-0ee9-98c2-…'      one dispatched Web researcher
    'worker_web:1d18fa52-ba8b-c335-8187-…'      the other one

So a step can say what it belongs to with no new storage, no model call and no
schema on the write side. That is the whole of part 1.

`wrote` comes with it because it is free and it is the other half of the
question a person asks of a row: *what happened here?* `updated_channels` is
already on every checkpoint.
"""

from __future__ import annotations

from openstategraph.api import threads as thread_queries


class _Checkpoint:
    def __init__(self, namespace: str = "", updated: list[str] | None = None) -> None:
        self.config = {"configurable": {"thread_id": "run-1", "checkpoint_ns": namespace}}
        self.checkpoint = {
            "id": "cp-1",
            "ts": "2026-08-20T06:33:06+00:00",
            "channel_values": {"answer": "done"},
            "updated_channels": updated if updated is not None else ["answer", "outputs"],
        }
        self.metadata = {"step": 3, "source": "loop", "workflow_slug": "morning-brief"}
        self.pending_writes = ()


WORKER_NS = "worker_web:f8e26037-68ee-0ee9-98c2-2f40934049ee"


class TestWhichGraphAStepBelongsTo:
    def test_the_parent_graph_says_so_by_saying_nothing(self) -> None:
        """`[]`, not `['']` — a level that does not exist is not a blank level."""
        step = thread_queries._step(_Checkpoint(""))
        assert step.namespace == []
        assert step.node == ""

    def test_a_subgraph_step_names_the_node_that_owns_it(self) -> None:
        step = thread_queries._step(_Checkpoint(WORKER_NS))
        assert step.node == "worker_web"

    def test_the_checkpoint_id_is_stripped_from_the_segment(self) -> None:
        """`worker_web:f8e26037-…` is one node plus one run id. Only one of
        those is a name, and the other changes every run."""
        step = thread_queries._step(_Checkpoint(WORKER_NS))
        assert step.namespace == ["worker_web"]

    def test_nesting_is_kept_outermost_first(self) -> None:
        """A mounted workflow's agent is two levels deep, and both are the
        answer to "where am I" — this is the field `path` already is on a live
        frame, and it is read the same way."""
        step = thread_queries._step(_Checkpoint("mount1:abc|worker_web:def"))
        assert step.namespace == ["mount1", "worker_web"]
        assert step.node == "worker_web"

    def test_two_instances_of_one_worker_are_the_same_node(self) -> None:
        """The instance id distinguishes rows; it must not split the node.

        `morning-brief` dispatches `worker_web` twice and the two land in
        different namespaces. A panel grouping by `node` should show one
        worker that ran twice, not two workers.
        """
        first = thread_queries._step(_Checkpoint("worker_web:f8e26037-68ee"))
        second = thread_queries._step(_Checkpoint("worker_web:1d18fa52-ba8b"))
        assert first.node == second.node == "worker_web"


class TestWhatTheStepDid:
    def test_it_names_the_channels_this_superstep_wrote(self) -> None:
        step = thread_queries._step(
            _Checkpoint(updated=["answer", "outputs", "worker_results"])
        )
        assert step.wrote == ["answer", "outputs", "worker_results"]

    def test_the_schedulers_bookkeeping_is_left_out(self) -> None:
        """Same rule `values` already obeys, and the same reason: `branch:to:`
        and `__pregel_tasks` are how the scheduler talks to itself, not what
        the run did."""
        step = thread_queries._step(
            _Checkpoint(updated=["answer", "branch:to:out1", "__pregel_tasks", "__start__"])
        )
        assert step.wrote == ["answer"]

    def test_a_checkpoint_that_recorded_none_says_none(self) -> None:
        step = thread_queries._step(_Checkpoint(updated=[]))
        assert step.wrote == []


class TestTheContractIsPublished:
    """A field the frontend cannot see is a field that does not exist."""

    def test_the_generated_openapi_carries_the_three_new_fields(self) -> None:
        import json
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        published = json.loads((repo / "docs" / "openapi.json").read_text())
        properties = published["components"]["schemas"]["ThreadStep"]["properties"]
        assert {"namespace", "node", "wrote"} <= set(properties)
