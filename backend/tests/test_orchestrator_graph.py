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

from dyflow.compile.node_runtime import NodeRuntime, RunState
from dyflow.compile.workflow_compiler import WorkflowCompiler


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
            node("node:function.format_report-1", "function.format_report", title="Genre report"),
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


# --------------------------------------------------------------------------- #
# LOOP + GRAPH TOGETHER: a revise edge re-enters the fan-out/join subgraph.
# --------------------------------------------------------------------------- #


class TestReviseReEntersTheFanOut:
    def test_a_rejected_report_causes_a_real_replan_not_a_retry_of_one_task(
        self,
    ) -> None:
        """The harder case this file exists to prove.

        The instruction ("top genre by revenue") has no separator a
        deterministic splitter can see, so the first pass plans exactly **one**
        subtask — not because of a cap, but because that is genuinely all the
        instruction asks for. The grader rejects the report as incomplete. The
        orchestrator consumes that feedback **as a new semicolon-joined
        clause**, which is what lets a second, genuinely new subtask exist at
        all — see the comment in `_orchestrator` on why prose feedback alone
        cannot do this. The second worker dispatch is for a task the first
        pass never ran, not a retry of the same one.
        """
        is_grader = lambda c: "You are a grader" in c  # noqa: E731
        model = RespondingModel(
            [
                # The grader call comes first, so it takes precedence over the
                # worker routes below — necessary because the grader's prompt
                # legitimately echoes the original question verbatim.
                (
                    # The feedback text is itself the next subtask, verbatim —
                    # honest about what a deterministic orchestrator can do
                    # with it: it has no NLP, so it can only ever fold prior
                    # feedback in as a literal new clause, never paraphrase it.
                    #
                    # Counts report sections rather than checking for a literal
                    # "task-2" substring: ids carry a generation prefix
                    # (`task-1-2`, not `task-2`) precisely so a replan's ids
                    # never collide with the rejected attempt's, which means
                    # the *label* changes across attempts even though the
                    # *count* is still the signal that matters here.
                    lambda c: is_grader(c) and c.count("### task-") == 1,
                    "FAIL\nAlso report the top artist by revenue.",
                ),
                (lambda c: "top genre by revenue" in c, "Rock"),
                (lambda c: "top artist by revenue" in c, "AC/DC"),
            ],
        )

        document = orchestrator_graph_document(max_subtasks=8)
        final = run(document, "top genre by revenue", model)

        assert final["attempts"] == 2, "expected exactly one replan"
        assert final["decisions"]["node:route.grader-1"] == "pass"
        # The final report has both sections — the replan genuinely added a
        # subtask the first pass never ran, it did not just repeat task-1.
        assert "Rock" in final["answer"]
        assert "AC/DC" in final["answer"]

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
            "node:orchestrate.supervisor-1": "node:orchestrate.worker-1",
        }
        assert plan.conditional["node:route.grader-1"] == {
            "pass": "node:output.formatted-1",
            "revise": "node:orchestrate.supervisor-1",
        }
        # The worker has no static incoming edge — it exists only to be
        # dispatched — so it must not appear as a graph entry point.
        assert "node:orchestrate.worker-1" not in plan.entry
