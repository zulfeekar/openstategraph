"""A resumed run's `done` frame is the *run's* result, not the segment's.

`workflow-gallery` 25. `/api/runs/resume` streams through the same
`_stream_run` as a fresh run, and the fold builds its terminal frame out of
accumulators initialised empty at the top of the call — filled only from the
`update` frames of *that* call. A resume is a new call, so everything that
happened before the pause was missing from the frame that is documented as the
run's result:

    done:  attempts 0, outputs {gate1, out1}
    state: attempts 2, outputs {in1, draft1, gate1, out1}

`attempts: 0` is not partial, it is wrong. And `/api/runs` builds its
`RunResponse` from `graph.invoke`'s **final state**, so the two doors
disagreed about the same run.

**The distinction the fix turns on.** Streaming *frames* are legitimately
per-segment: a client watching a resumed run must not be re-sent the first
half's tokens. The `done` frame is a different kind of thing — it reports the
run, so it is seeded from what the thread already holds.

The assertions here compare the terminal frame against
`graph.get_state(config).values` — the checkpointer, which is also what
`openstategraph threads show` reads — rather than against literals. A test
that restated the expected keys would pass against a fix that seeded the wrong
map.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from openstategraph.api.streaming import _stream_run
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

from test_human_approval import _fake_model, approval_document

FIRST_INPUT: dict[str, Any] = {
    "question": "draft something",
    "attempts": 0,
    "decisions": {},
    "outputs": {},
}


def _pausing_graph(thread_id: str) -> tuple[Any, Any, dict[str, str], Any, dict[str, Any]]:
    document = approval_document()
    runtime = NodeRuntime(model=_fake_model("Draft answer"))
    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    graph = compiler.build(
        document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
    )
    node_ids_by_name = {safe_name(n): n for n in plan.nodes}
    config = {"configurable": {"thread_id": thread_id}}
    return graph, plan, node_ids_by_name, runtime, config


def _frames(graph, graph_input, config, plan, node_ids_by_name, runtime, thread_id):
    return list(
        _stream_run(graph, graph_input, config, plan, node_ids_by_name, runtime, thread_id)
    )


def _terminal(frames: list[str]) -> tuple[str, dict[str, Any]]:
    last = frames[-1]
    event = last.split("event: ", 1)[1].split("\n", 1)[0]
    return event, json.loads(last.split("data: ", 1)[1])


class TestAResumedRun:
    """Pause at the approval, resume it, read the frame that says how it went."""

    def test_the_done_frame_reports_what_the_checkpointer_holds(self) -> None:
        thread_id = "t-resume-whole-run"
        graph, plan, node_ids, runtime, config = _pausing_graph(thread_id)

        paused = _frames(graph, FIRST_INPUT, config, plan, node_ids, runtime, thread_id)
        assert _terminal(paused)[0] == "interrupt"

        resumed = _frames(
            graph,
            Command(resume={"decision": "approve"}),
            config,
            plan,
            node_ids,
            runtime,
            thread_id,
        )
        event, done = _terminal(resumed)
        assert event == "done"

        state = graph.get_state(config).values

        # All four fields the ticket names, against the checkpointer.
        assert done["attempts"] == state["attempts"]
        assert done["decisions"] == {k: str(v) for k, v in state["decisions"].items()}
        assert sorted(done["outputs"]) == sorted(state["outputs"])
        assert done["answer"] == state["answer"]

    def test_the_first_half_of_the_run_is_in_it(self) -> None:
        """The concrete loss: the node that wrote the text being approved.

        Named explicitly as well as compared to state, because "both maps are
        equally empty" would satisfy the comparison above and is exactly the
        failure this ticket is about.
        """
        thread_id = "t-resume-first-half"
        graph, plan, node_ids, runtime, config = _pausing_graph(thread_id)
        _frames(graph, FIRST_INPUT, config, plan, node_ids, runtime, thread_id)

        _, done = _terminal(
            _frames(
                graph,
                Command(resume={"decision": "approve"}),
                config,
                plan,
                node_ids,
                runtime,
                thread_id,
            )
        )

        assert "node:agent.llm-1" in done["outputs"]
        assert "node:input.text-1" in done["outputs"]
        # And the agent invocation that happened before the pause is counted.
        assert done["attempts"] >= 1


class TestAFreshRun:
    """The overwhelmingly common case, and its frame is correct today.

    Proved rather than assumed: the seeding is gated on a resume, so a first
    call into a brand-new thread must fold exactly what it folded before.
    """

    def test_a_run_that_never_paused_reports_only_its_own_run(self) -> None:
        document = approval_document()
        # Drop the approval node's branches by approving nothing: instead use a
        # document with no pause at all — input -> agent -> output.
        document["nodes"] = [n for n in document["nodes"] if "approval" not in n["id"]]
        document["edges"] = [
            {
                "source": {"nodeId": "node:input.text-1", "portId": "text"},
                "target": {"nodeId": "node:agent.llm-1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "node:agent.llm-1", "portId": "result"},
                "target": {"nodeId": "node:output.formatted-1", "portId": "result"},
            },
        ]
        document["nodes"] = [
            n for n in document["nodes"] if n["id"] != "node:output.formatted-2"
        ]
        runtime = NodeRuntime(model=_fake_model("Draft answer"))
        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        graph = compiler.build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        node_ids = {safe_name(n): n for n in plan.nodes}
        config = {"configurable": {"thread_id": "t-fresh"}}

        _, done = _terminal(
            _frames(graph, FIRST_INPUT, config, plan, node_ids, runtime, "t-fresh")
        )
        assert done["answer"] == "Draft answer"
        assert sorted(done["outputs"]) == [
            "node:agent.llm-1",
            "node:input.text-1",
            "node:output.formatted-1",
        ]


class TestTheSeedCannotFallBehind:
    """`run_health`'s sources are the ones that went missing one at a time.

    `workflow-gallery` 49 made `run_health_from_state` derive its sources from
    `run_health`'s own signature, because every door that listed them locally
    fell behind. The resume seed is a list, so it can fall behind the same way
    — this is what stops it: a new health source that nobody seeds is a red
    test rather than another half-empty terminal frame.
    """

    def test_every_health_source_is_seeded_on_a_resume(self) -> None:
        from openstategraph.api.streaming import RESUME_SEEDED_KEYS
        from openstategraph.compile.workflow_compiler import _HEALTH_SOURCES

        missing = set(_HEALTH_SOURCES) - set(RESUME_SEEDED_KEYS)
        assert not missing, f"health sources not seeded on resume: {sorted(missing)}"


class TestWhichCallsAreSeeded:
    def test_a_command_is_a_resume_and_a_state_dict_is_not(self) -> None:
        from openstategraph.api.streaming import _resumes_a_paused_run

        assert _resumes_a_paused_run(Command(resume={"decision": "approve"})) is True
        assert _resumes_a_paused_run(FIRST_INPUT) is False
