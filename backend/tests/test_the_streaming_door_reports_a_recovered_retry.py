"""The door both shipped UIs read says a step had to be retried.

`production-ready` 97. `retry_warnings` (`memory-and-replay` 41) reached
`/api/runs` and the library door and never `/api/runs/stream`, because that
door called `run_health` **positionally** and passed `None` where `retries`
goes — there was no local to pass, since the fold never collected one. Measured
before the fix, same run through two doors:

    /api/runs        ['Node "a1" failed and was retried; attempt 2 …']
    /api/runs/stream []

That is the sixth source to go missing from a door that listed them by hand
(`every-workflow-green` 14 and 16, `workflow-gallery` 49). So the fold now
carries `retries` **and** this door assembles off `run_health`'s own signature
through `run_health_from_state`, like the other two — `TestTheDoorCannotFall
Behind` is what makes a seventh drift a red test rather than a missing
sentence.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from openstategraph.api.audience import Audience
from openstategraph.api.streaming import _stream_run
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import (
    WorkflowCompiler,
    run_health_from_state,
    safe_name,
)

from conftest import RespondingModel, drive_fold

FIRST_INPUT: dict[str, Any] = {
    "question": "hello",
    "attempts": 0,
    "decisions": {},
    "outputs": {},
}


class _FailsOnceThenAnswers(RespondingModel):
    """A transient provider failure, which is what `retry_policy` exists for.

    The compiler gives every node `RetryPolicy(max_attempts=3)`, so the first
    raise is absorbed and the second call answers — a recovered retry, the case
    that leaves a correct answer and a paid-for second run behind it.
    """

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        self.calls.append("\n".join(str(m.content) for m in messages))
        if len(self.calls) == 1:
            raise ConnectionError("transient")
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="the answer"))]
        )


def _document() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "a1", "type": "agent.llm", "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "a1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "a1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


def _built(model: Any) -> tuple[Any, Any, dict[str, str], Any]:
    document = _document()
    runtime = NodeRuntime(model=model)
    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    graph = compiler.build(
        document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
    )
    return graph, plan, {safe_name(n): n for n in plan.nodes}, runtime


def _done_frame(model: Any, thread_id: str) -> dict[str, Any]:
    graph, plan, node_ids, runtime = _built(model)
    frames = list(
        drive_fold(_stream_run(
            graph,
            dict(FIRST_INPUT),
            {"configurable": {"thread_id": thread_id}},
            plan,
            node_ids,
            runtime,
            thread_id,
            Audience.DEVELOPER,
        ))
    )
    last = frames[-1]
    assert last.split("event: ", 1)[1].split("\n", 1)[0] == "done"
    return json.loads(last.split("data: ", 1)[1])


def _library_door(model: Any, thread_id: str) -> list[str]:
    """What `/api/runs` and `CompiledWorkflow.ask()` say about the same run."""
    graph, _plan, _ids, _runtime = _built(model)
    final = graph.invoke(
        dict(FIRST_INPUT),
        {"recursion_limit": 40, "configurable": {"thread_id": thread_id}},
    )
    assert final["retries"] == {"a1": 2}, "the premise: the node really was retried"
    return run_health_from_state(final).silent


class TestTheStreamingDoorSaysAStepWasRetried:
    def test_the_terminal_frame_carries_the_retry(self) -> None:
        done = _done_frame(_FailsOnceThenAnswers([], default=""), "t-97-stream")
        warnings = done["developer"]["warnings"]

        assert done["answer"] == "the answer"
        assert any(
            'Node "a1" failed and was retried' in w and "attempt 2" in w
            for w in warnings
        ), warnings

    def test_the_three_doors_agree_about_the_same_run(self) -> None:
        """Against the other doors rather than against a literal: a test that
        restated the sentence would pass against a door reporting a *different*
        run's health."""
        streamed = _done_frame(_FailsOnceThenAnswers([], default=""), "t-97-agree")
        library = _library_door(_FailsOnceThenAnswers([], default=""), "t-97-lib")

        retries_said = [w for w in library if "was retried" in w]
        assert retries_said, library
        for line in retries_said:
            assert line in streamed["developer"]["warnings"]

    def test_a_run_that_needed_no_retry_says_nothing(self) -> None:
        """Presence is the signal — the half a widening usually breaks."""
        done = _done_frame(RespondingModel([], default="the answer"), "t-97-clean")

        assert not [w for w in done["developer"]["warnings"] if "was retried" in w]


class TestTheDoorCannotFallBehind:
    """The mechanism, not the sentence.

    `run_health_from_state` reads its sources off `run_health`'s signature so
    the library door cannot fall behind. This door could, and did — six times a
    source was added and once it went missing here. It now hands
    `run_health_from_state` a mapping keyed by state key, and these two read
    that mapping out of the source rather than trusting the prose.
    """

    def _folded_keys(self) -> set[str]:
        import openstategraph.api.streaming as streaming

        tree = ast.parse(Path(streaming.__file__).read_text())
        for node in ast.walk(tree):
            target = getattr(node, "target", None)
            if isinstance(node, ast.AnnAssign) and getattr(target, "id", "") == "folded":
                assert isinstance(node.value, ast.Dict)
                return {ast.literal_eval(k) for k in node.value.keys}
        raise AssertionError("the streaming fold no longer names a `folded` mapping")

    def test_every_health_source_is_folded_by_this_door(self) -> None:
        from openstategraph.compile.workflow_compiler import _HEALTH_SOURCES

        missing = set(_HEALTH_SOURCES) - self._folded_keys()
        assert not missing, (
            f"the streaming door does not fold {sorted(missing)}, so that source "
            "is missing from the terminal frame both shipped UIs read"
        )

    def test_it_assembles_off_the_signature_rather_than_positionally(self) -> None:
        import openstategraph.api.streaming as streaming

        source = Path(streaming.__file__).read_text()
        assert "health = run_health_from_state(folded)" in source, (
            "a positional call is how this door fell behind `retries`; the "
            "sources must come off `run_health`'s own signature"
        )


class TestARetryBeforeThePauseSurvivesTheResume:
    """The seed, which is the half option (2) touches.

    `RESUME_SEEDED_KEYS` has named `retries` since `memory-and-replay` 41, and
    the seed did not actually carry it: the resume block listed its targets by
    hand and that list had no `retries` row, so a node retried *before* an
    approval was unreportable twice over. The seed now iterates the same
    `folded` mapping the health report is assembled from, so the two cannot
    disagree.
    """

    def test_a_retry_from_the_first_segment_reaches_the_done_frame(self) -> None:
        from langgraph.types import Command

        from test_a_resumed_runs_done_frame_carries_the_whole_run import (
            FIRST_INPUT as APPROVAL_INPUT,
            _frames,
            _pausing_graph,
            _terminal,
        )

        thread_id = "t-97-resume"
        graph, plan, node_ids, runtime, config = _pausing_graph(thread_id)

        paused = _frames(
            graph, APPROVAL_INPUT, config, plan, node_ids, runtime, thread_id
        )
        assert _terminal(paused)[0] == "interrupt"

        # A recovered retry in the first segment, written where the runtime
        # writes it. The fold of *this* call cannot see it: a resume is a new
        # call, and its frames start after the pause.
        graph.update_state(config, {"retries": {"draft1": 2}})

        resumed = list(
            drive_fold(_stream_run(
                graph,
                Command(resume={"decision": "approve"}),
                config,
                plan,
                node_ids,
                runtime,
                thread_id,
                Audience.DEVELOPER,
            ))
        )
        event, done = _terminal(resumed)

        assert event == "done"
        assert any(
            'Node "draft1" failed and was retried' in w
            for w in done["developer"]["warnings"]
        ), done["developer"]["warnings"]
