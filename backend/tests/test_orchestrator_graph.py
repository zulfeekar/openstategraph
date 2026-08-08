"""The proof: fan-out/join (graph engineering) and a bounded revise loop (loop
engineering), combined in one compiled, canvas-shaped graph.

This is the test the architecture doc
(`.scratch/fullstack-langgraph/decisions/loop-graph-harness.md`) calls for: not
two isolated demonstrations, but one graph where a loop's retry re-enters a
fan-out/join subgraph — a strictly harder case than looping over a single agent
node, because the cycle has to redo *branching and joining*, not just one call.

```
question -> orchestrator --Send x N--> worker --> report(function) -> grader
                ^                                                        |
                '-------------------- revise (feedback) -----------------'
                                                                          | pass
                                                                          v
                                                                        output
```

Everything downstream of the model is deterministic (the report is a pure join,
the grader's verdict is scripted), so what is being proven is the **wiring**:
that `Send` really dispatches once per planned subtask, that every dispatched
instance's result really reaches the join, that a revise edge really re-enters
the fan-out step rather than resuming after it, and that the loop is bounded.
"""

from __future__ import annotations

from typing import Any, Callable

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler


RouteRule = tuple[Callable[[str], bool], str]


class RespondingModel(GenericFakeChatModel):
    """Answers by matching a **predicate** over the incoming message, not call order.

    A queue-based fake (`iter(["a", "b"])`) would make the test's correctness
    depend on which of two concurrently dispatched tasks happens to call the
    model first — which `Send` does not guarantee. Matching on content instead
    means the answer is deterministic regardless of dispatch order.

    A predicate rather than a substring, because substring containment cannot
    express what this file actually needs to distinguish: "the report has only
    task-1" is a *negative* condition (task-2 absent), and the grader's own
    prompt legitimately echoes the original question into its context, so a
    short worker-routing string is a genuine, unavoidable substring of the
    grader's call too. A predicate can say exactly what is meant instead of
    fighting string containment to approximate it.
    """

    rules: list[RouteRule] = []
    default: str = "PASS"
    calls: list[str] = []

    def __init__(self, rules: list[RouteRule], default: str = "PASS"):
        super().__init__(messages=iter([]))
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "default", default)
        object.__setattr__(self, "calls", [])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        self.calls.append(content)
        answer = self.default
        for predicate, reply in self.rules:
            if predicate(content):
                answer = reply
                break
        return self._reply(answer)

    def _reply(self, text: str):  # noqa: ANN001
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


def orchestrator_graph_document(max_subtasks: int) -> dict[str, Any]:
    """Canvas-shaped: input -> orchestrator -[fan-out]-> worker -> report -> grader."""
    return {
        "version": 1,
        "name": "orchestrator-graph-proof",
        "nodes": [
            node("node:input.text-1", "input.text"),
            node("node:orchestrate.supervisor-1", "orchestrate.supervisor", maxSubtasks=max_subtasks),
            node("node:orchestrate.worker-1", "orchestrate.worker"),
            node("node:function.format_report-1", "function.format_report", reportTitle="Genre report"),
            node("node:route.grader-1", "route.grader", criteria="", maxAttempts=3),
            node("node:output.formatted-1", "output.formatted"),
        ],
        "edges": [
            edge("node:input.text-1", "text", "node:orchestrate.supervisor-1", "instruction"),
            edge("node:orchestrate.supervisor-1", "workers", "node:orchestrate.worker-1", "dispatch"),
            edge("node:orchestrate.worker-1", "result", "node:function.format_report-1", "candidate"),
            edge("node:function.format_report-1", "report", "node:route.grader-1", "candidate"),
            edge("node:route.grader-1", "pass", "node:output.formatted-1", "result"),
            # The loop: closes back on the orchestrator's feedback port, not the
            # worker's — a revise re-plans, it does not re-run one dispatched task.
            edge("node:route.grader-1", "revise", "node:orchestrate.supervisor-1", "feedback"),
        ],
    }


def run(document: dict[str, Any], question: str, model: Any) -> dict[str, Any]:
    runtime = NodeRuntime(model=model)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 50},
    )


# --------------------------------------------------------------------------- #
# GRAPH ENGINEERING: the fan-out actually fans out, and the join actually joins.
# --------------------------------------------------------------------------- #


class TestFanOutAndJoin:
    def test_the_orchestrator_plans_and_the_worker_is_dispatched_once_per_subtask(
        self,
    ) -> None:
        model = RespondingModel(
            [
            (lambda c: "top genre by revenue" in c, "Rock"),
            (lambda c: "top artist by revenue" in c, "AC/DC"),
        ],
        )
        document = orchestrator_graph_document(max_subtasks=8)

        final = run(
            document, "top genre by revenue; top artist by revenue", model
        )

        # Two subtasks planned...
        subtasks = final["subtasks"]["node:orchestrate.supervisor-1"]
        assert [t["id"] for t in subtasks] == ["task-1", "task-2"]
        # ...and the worker node ran exactly twice — proof of real fan-out, not
        # a single call collapsed to one branch. (A third call is the grader,
        # which always runs once after the join.)
        worker_calls = [c for c in model.calls if "grader" not in c]
        assert len(worker_calls) == 2

    def test_every_dispatched_result_reaches_the_join_by_its_own_task_id(self) -> None:
        model = RespondingModel(
            [
            (lambda c: "top genre by revenue" in c, "Rock"),
            (lambda c: "top artist by revenue" in c, "AC/DC"),
        ],
        )
        document = orchestrator_graph_document(max_subtasks=8)

        final = run(document, "top genre by revenue; top artist by revenue", model)

        # Both results present under distinct keys — nothing overwrote the other,
        # which is exactly the failure mode of keying by node id instead of task id.
        results = final["worker_results"]
        assert results["task-1"] == "Rock"
        assert results["task-2"] == "AC/DC"

    def test_the_report_contains_every_task_in_a_stable_order(self) -> None:
        model = RespondingModel(
            [
            (lambda c: "top genre by revenue" in c, "Rock"),
            (lambda c: "top artist by revenue" in c, "AC/DC"),
        ],
        )
        document = orchestrator_graph_document(max_subtasks=8)

        final = run(document, "top genre by revenue; top artist by revenue", model)

        assert "### task-1\nRock" in final["answer"]
        assert "### task-2\nAC/DC" in final["answer"]
        # Deterministic join order — sorted by task id — so identical inputs
        # always produce byte-identical output, the same requirement ticket 15
        # placed on the code generator.
        assert final["answer"].index("task-1") < final["answer"].index("task-2")

    def test_a_single_unsplittable_instruction_still_fans_out_to_exactly_one(
        self,
    ) -> None:
        model = RespondingModel([(lambda c: "which genre" in c, "Rock")])
        document = orchestrator_graph_document(max_subtasks=8)

        final = run(document, "which genre earned the most?", model)

        worker_calls = [c for c in model.calls if "grader" not in c]
        assert len(worker_calls) == 1
        assert list(final["worker_results"].keys()) == ["task-1"]

    def test_a_worker_cannot_see_the_parents_other_state(self) -> None:
        """The isolation fact worth pinning: `Send` replaces state, not merges it.

        If a worker somehow saw `question` directly instead of only its own
        `task_instruction`, this test's routing (keyed on the *subtask* text,
        never the raw `question`) would never match and every call would fall
        through to the default answer.
        """
        model = RespondingModel(
            [(lambda c: "top genre by revenue" in c, "Rock")], default="WRONG"
        )
        document = orchestrator_graph_document(max_subtasks=8)

        final = run(document, "top genre by revenue", model)

        assert "WRONG" not in final["answer"]
        assert final["worker_results"]["task-1"] == "Rock"

    def test_the_configured_report_title_actually_reaches_the_report(self) -> None:
        """Regression: `reportTitle` (the TS field's real key) vs `title`.

        Found by a TS-schema-vs-Python-factory diff, not live: every real
        canvas-authored document produces `reportTitle` (see
        `FormatReportNode.ts`'s `FIELD_REPORT_TITLE`), but
        `_format_report_function` used to read `data.get("title")` — a key no
        real document ever sets. The field was fully inert; a developer
        could type any title into the Inspector and every report still fell
        back to the literal default `"Report"`. `orchestrator_graph_document`
        already sets `reportTitle="Genre report"`, so this only needed an
        assertion that the title actually shows up.
        """
        model = RespondingModel([(lambda c: "top genre by revenue" in c, "Rock")])
        document = orchestrator_graph_document(max_subtasks=8)

        final = run(document, "top genre by revenue", model)

        assert final["answer"].startswith("# Genre report")


# --------------------------------------------------------------------------- #
# LOOP + GRAPH TOGETHER: a revise edge re-enters the fan-out/join subgraph.
# --------------------------------------------------------------------------- #


class TestReviseReEntersTheFanOut:
    def test_a_rejected_report_replans_with_feedback_folded_into_the_same_subtask(
        self,
    ) -> None:
        """The harder case this file exists to prove — corrected.

        An earlier version of this test pinned the opposite of what should
        happen: it had the orchestrator turn the grader's feedback into a
        **second, independently dispatched subtask**, by joining it onto the
        instruction with a semicolon *before* splitting. That looked
        reasonable in the abstract (a deterministic splitter needs a
        structural separator to "notice" new content) but was wrong in
        practice — found live, not hypothetically, running the actual
        intent-routed demo through the chat panel: a grader's ordinary
        prose critique ("be more decisive") got treated exactly like a
        genuinely separate fact request, so it became its own `Subtask` and
        got dispatched to a worker as if it were a fresh question. The
        worker dutifully "answered" the critique sentence, and the joined
        report read as two disjoint, sometimes contradictory answers to one
        question.

        The instruction here ("top genre by revenue") still has no
        separator, so it still plans exactly **one** subtask. What changed
        is where the feedback goes on a replan: folded into that one
        subtask's own instruction, not split off as a new one. A single
        worker call now sees both the original ask and the rejection
        reason together — which is what `test_worker_by_revenue_and_artist`
        below proves reaches the model — rather than two workers each
        seeing only half the context.
        """
        model = RespondingModel(
            [
                # The grader call comes first, so it takes precedence over
                # the worker route below — necessary because the grader's
                # prompt legitimately echoes the original question verbatim.
                (
                    lambda c: "You are a grader" in c and "### task-1\n" in c,
                    "FAIL\nAlso report the top artist by revenue.",
                ),
                # One worker call now carries both the instruction and the
                # folded-in feedback — scripted to answer both in one reply,
                # the way a real model would.
                (
                    lambda c: "top genre by revenue" in c
                    and "Also report the top artist by revenue" in c,
                    "Rock. Top artist by revenue: AC/DC.",
                ),
            ],
        )

        document = orchestrator_graph_document(max_subtasks=8)
        final = run(document, "top genre by revenue", model)

        assert final["attempts"] == 2, "expected exactly one replan"
        assert final["decisions"]["node:route.grader-1"] == "pass"
        # Still exactly one subtask on the replan — the feedback refined it,
        # it did not fork the plan.
        subtasks = final["subtasks"]["node:orchestrate.supervisor-1"]
        assert len(subtasks) == 1
        # Two worker calls total — one per attempt (the first attempt, one
        # subtask with no feedback yet; the replan, the same one subtask
        # with feedback folded in) — never two *in the same* attempt.
        worker_calls = [c for c in model.calls if "grader" not in c]
        assert len(worker_calls) == 2
        assert "Rock" in final["answer"]
        assert "AC/DC" in final["answer"]

    def test_feedback_that_is_pure_critique_no_longer_forks_into_a_bogus_subtask(
        self,
    ) -> None:
        """Pins the exact live failure this fix closes.

        Real repro from the chat panel: "Who is the best artist of all
        time?" — a single-subtask instruction with no separator. The grader
        rejected the first attempt with ordinary critique prose (not a
        request for any new fact). Under the old semicolon-join behaviour,
        that critique text became its own `Subtask` and got dispatched to a
        second worker, which produced an answer to the *critique sentence*
        rather than to the question — a second, unrelated block in the
        final report. Here, a worker call whose content is anything *other*
        than the one legitimate instruction plus its folded-in feedback
        would mean the bug is back.
        """
        model = RespondingModel(
            [
                (
                    lambda c: "You are a grader" in c and "### task-1\n" in c,
                    "FAIL\nGive a single, decisive answer, not a hedge.",
                ),
                (
                    lambda c: "who is the best artist of all time" in c.lower(),
                    "Leonardo da Vinci.",
                ),
            ],
        )

        document = orchestrator_graph_document(max_subtasks=8)
        final = run(document, "Who is the best artist of all time?", model)

        # Still exactly one subtask on the replan — the critique refined it,
        # it did not fork a second, bogus subtask out of the critique
        # sentence itself (the fixed bug: one attempt legitimately fails
        # and replans once, which is two *sequential* worker calls, not two
        # workers dispatched *in the same attempt* from one instruction).
        subtasks = final["subtasks"]["node:orchestrate.supervisor-1"]
        assert len(subtasks) == 1
        # Every worker call answers the real question (each may also carry
        # the folded-in critique as extra context) — none of them is a
        # worker answering the critique sentence on its own.
        worker_calls = [c for c in model.calls if "grader" not in c]
        assert worker_calls
        for call in worker_calls:
            assert "who is the best artist of all time" in call.lower()
        assert final["answer"].count("### task-") == 1
        assert "Leonardo da Vinci." in final["answer"]

    def test_the_retry_carries_the_reason_into_the_replanned_instruction(self) -> None:
        is_grader = lambda c: "You are a grader" in c  # noqa: E731
        model = RespondingModel(
            [
                (
                    lambda c: is_grader(c) and c.count("### task-") == 1,
                    "FAIL\nMissing the artist figure.",
                ),
                (lambda c: "top genre by revenue" in c, "Rock"),
            ],
        )
        document = orchestrator_graph_document(max_subtasks=8)

        run(document, "top genre by revenue", model)

        # Without the reason reaching the next planning pass, a replan would
        # produce the identical single subtask and loop forever until the
        # attempt cap, having learned nothing.
        assert any("Missing the artist figure." in call for call in model.calls)

    def test_a_persistently_incomplete_report_still_terminates(self) -> None:
        # Always FAIL, regardless of content. The cap must end the loop rather
        # than spin to GraphRecursionError, even while the graph keeps
        # re-entering a multi-node fan-out/join subgraph each attempt.
        model = RespondingModel([], default="FAIL\nstill incomplete")
        document = orchestrator_graph_document(max_subtasks=1)

        final = run(document, "impossible", model)

        assert final["attempts"] == 3
        assert final["decisions"]["node:route.grader-1"] == "pass"

    def test_the_cycle_cannot_run_away_even_with_a_fan_out_inside_it(self) -> None:
        model = RespondingModel([], default="FAIL\nno")
        document = orchestrator_graph_document(max_subtasks=1)

        # Would raise GraphRecursionError if the budget guard were missing —
        # generous on purpose, since each lap now costs more supersteps than a
        # single-agent loop (plan -> dispatch -> join -> grade, not just
        # call -> grade).
        run(document, "impossible", model)

    def test_the_graph_structure_declares_exactly_one_fan_out_and_one_cycle(self) -> None:
        """A structural sanity check independent of any run.

        Verifies the *plan* the compiler produced, not just that execution
        happened to work — the property ticket 15 calls the interpreter's
        contract with a future code generator.
        """
        document = orchestrator_graph_document(max_subtasks=1)
        plan = WorkflowCompiler().plan(document)

        assert plan.fan_out == {
            "node:orchestrate.supervisor-1": ["node:orchestrate.worker-1"],
        }
        assert plan.conditional["node:route.grader-1"] == {
            "pass": "node:output.formatted-1",
            "revise": "node:orchestrate.supervisor-1",
        }
        # The worker has no static incoming edge — it exists only to be
        # dispatched — so it must not appear as a graph entry point.
        assert "node:orchestrate.worker-1" not in plan.entry
