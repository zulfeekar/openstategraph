"""An empty member of a fan-out report says which member, that it ran, and that
its model returned nothing.

`workflow-gallery` 52. The live symptom, on
`archetype-orchestrator-report` against `ollama:gpt-oss:120b-cloud`:

    ### task-1
    _(this member produced no result)_

with `warnings` carrying, at best,

    Node "worker-research#task-1" produced no output. The run continued with
    the previous answer, so what you are reading came from an earlier step.

Three separate defects in those two sentences, and none of them is in
extraction:

1. **The report line answers none of a reader's questions.** Did the member
   run? Did its loop work? Did the model say nothing, or did we lose the text?
   `production-ready` 96 settled the mechanism by tapping the raw Ollama wire
   underneath `ChatOllama` — `content=''`, `thinking=None`, `tool_calls=None`,
   `done_reason='stop'` — so the model genuinely stopped and there is no text
   to recover. What is left is saying so.

2. **96's split never reached a worker.** `silent_node_warnings` reads
   `tool_use[node]["ran"]`, and a worker writes its output under the composite
   key `<node>#<task>` while `tool_report` keys by node id alone. The lookup
   therefore missed on every dispatched member, so the sentence 96 built for
   "the loop worked and then went quiet" was unreachable from `_worker` — the
   exact `_agent`-only wiring `skills/ticket-loop` warns about, found again.

3. **"The run continued with the previous answer" is false for a member.** A
   worker's empty result does not leave a stale `answer` standing; it renders
   as a gap in one section of the report. Telling a reader they are looking at
   an earlier step's answer sends them to the wrong place entirely.

Deliberately not done here, both for the reasons 96 recorded: nothing retries
the empty lap (retry is a graph-assembly parameter in this project, never a
node concern) and nothing widens extraction (there is nothing on the wire to
widen towards).

One caveat is load-bearing and is why the report line names no tools: every
dispatched instance shares one node id, so `tool_use` is per **node**, not per
member. Naming a tool inside a member's section would attribute to that subtask
a call that may have belonged to its sibling. The node-level warning says "the
node called X during this run", which is what is actually known.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import (
    NO_MODEL_MARKER,
    WorkflowCompiler,
    run_health,
    run_health_from_state,
    silent_node_warnings,
)

from conftest import RespondingModel

PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "openstategraph/examples/archetype-orchestrator-report/workflow.json"
)


class TestTheWarningNamesTheMemberAndWhatItDid:
    def test_a_silent_member_is_not_reported_as_a_node_that_never_ran(self) -> None:
        (warning,) = silent_node_warnings({"worker-research#task-2": ""})
        assert 'Member "task-2" of node "worker-research"' in warning
        assert "ran and its model ended the turn without writing anything" in warning
        assert "that section of the report is empty" in warning
        # The false half of the old sentence must not survive: a member's
        # silence leaves a gap in the report, not a stale answer downstream.
        assert "came from an earlier step" not in warning

    def test_the_tool_lookup_finds_the_node_behind_the_member(self) -> None:
        """96's split, reaching `_worker` for the first time."""
        tool_use = {"worker-research": {"bound": ["search"], "ran": ["search"]}}
        (warning,) = silent_node_warnings({"worker-research#task-2": ""}, tool_use)
        assert "The node called search during this run." in warning

    def test_bound_but_never_run_does_not_borrow_the_sentence(self) -> None:
        tool_use = {"worker-research": {"bound": ["search"], "ran": []}}
        (warning,) = silent_node_warnings({"worker-research#task-2": ""}, tool_use)
        # Not `"search" not in warning` — the node is called "worker-research".
        assert "The node called" not in warning

    def test_a_member_with_no_model_keeps_the_no_model_sentence(self) -> None:
        """`_worker`'s other empty branch. It never called a model at all, so
        it must not be told its model returned nothing."""
        (warning,) = silent_node_warnings({"worker-research#task-2": NO_MODEL_MARKER})
        assert "had no model configured" in warning
        assert "ended the turn" not in warning

    def test_a_plain_node_that_never_ran_keeps_the_sentence_it_had(self) -> None:
        assert silent_node_warnings({"a1": ""}) == [
            'Node "a1" produced no output. The run continued with the previous '
            "answer, so what you are reading came from an earlier step."
        ]

    def test_a_member_that_answered_stays_silent(self) -> None:
        assert silent_node_warnings({"worker-research#task-1": "an answer"}) == []


def _run_the_shipped_package(second_member_answer: str) -> dict[str, Any]:
    """The real shipped document, a real compiled graph, a scripted model.

    Nothing here asks `silent_node_warnings` anything — a fix wired into the
    wrong function cannot stay green.
    """
    document = json.loads(PACKAGE.read_text())["document"]
    # Every predicate is anchored on "Your role on this team", the marker only a
    # worker's own prompt carries. Without it the planner's and the supervisor's
    # calls — which echo the brief verbatim — match a worker rule first, and the
    # fan-out never happens. The planner itself is left to the `""` default on
    # purpose: that is the semicolon fallback, which splits this brief into the
    # two subtasks the live run produced.
    def _member(needle: str):
        return lambda c: "Your role on this team" in c and needle in c

    model = RespondingModel(
        [
            (_member("access on day one"), "Badge, laptop, VPN, repo access."),
            (_member("onboarding agenda"), second_member_answer),
        ],
        default="",
    )
    runtime = NodeRuntime(model=model)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {
            "question": (
                "Research what a new engineer needs access on day one; "
                "write a 30-minute onboarding agenda for them."
            ),
            "attempts": 0,
            "decisions": {},
            "outputs": {},
        },
        {"recursion_limit": 60},
    )


class TestTheReportAReaderSees:
    def test_the_premise_holds(self) -> None:
        """Measured rather than assumed — if the fan-out did not produce one
        answered member and one empty one, everything below is asserting about
        the wrong situation."""
        state = _run_the_shipped_package("")
        assert state["worker_results"]["task-1"] == "Badge, laptop, VPN, repo access."
        assert state["worker_results"]["task-2"] == ""
        assert state["outputs"]["worker-research#task-2"] == ""

    def test_the_empty_section_says_what_happened(self) -> None:
        answer = _run_the_shipped_package("")["answer"]
        assert "_(this member produced no result)_" not in answer
        assert (
            "### task-2\n_(`worker-research` ran this subtask and its model "
            "returned no text, so it is unanswered.)_" in answer
        )

    def test_the_member_that_answered_is_untouched(self) -> None:
        answer = _run_the_shipped_package("Agenda: 09:00 intro, 09:30 repo tour.")["answer"]
        assert "### task-1\nBadge, laptop, VPN, repo access." in answer
        assert "### task-2\nAgenda: 09:00 intro, 09:30 repo tour." in answer
        assert "unanswered" not in answer

    def test_a_member_with_no_model_says_that_instead(self) -> None:
        """`_worker`'s other empty branch, at the surface a reader reads. It
        never called a model, so the section must not tell anyone a model
        returned nothing."""
        from openstategraph.compile.node_runtime import _silent_member_note

        note = _silent_member_note(
            "task-2", {"outputs": {"worker-research#task-2": NO_MODEL_MARKER}}
        )
        assert "no model was configured for `worker-research`" in note
        assert "returned no text" not in note

    def test_a_task_with_no_output_row_keeps_the_old_line(self) -> None:
        """There is no node to name and nothing measured to say."""
        from openstategraph.compile.node_runtime import _silent_member_note

        assert (
            _silent_member_note("task-9", {"outputs": {}})
            == "_(this member produced no result)_"
        )

    def test_a_fully_answered_run_reports_no_silence_at_all(self) -> None:
        state = _run_the_shipped_package("Agenda: 09:00 intro, 09:30 repo tour.")
        assert run_health_from_state(state).silent == []


class TestEveryDoorAgrees:
    def test_the_library_door_carries_it(self) -> None:
        state = _run_the_shipped_package("")
        (warning,) = run_health_from_state(state).silent
        assert 'Member "task-2" of node "worker-research"' in warning
        assert run_health_from_state(state).failures == []

    def test_run_health_and_the_state_door_produce_the_same_sentence(self) -> None:
        state = _run_the_shipped_package("")
        assembled = run_health(
            state["outputs"], {}, {}, {}, None, state.get("tool_use")
        )
        assert assembled.silent == run_health_from_state(state).silent

    def test_the_streaming_door_folds_the_sources_this_needs(self) -> None:
        """The door both shipped UIs read. It lists its sources by hand, so it
        is the one that can silently fall behind."""
        from test_the_streaming_door_reports_a_recovered_retry import (
            TestTheDoorCannotFallBehind,
        )

        folded = TestTheDoorCannotFallBehind()._folded_keys()
        assert "outputs" in folded and "tool_use" in folded
