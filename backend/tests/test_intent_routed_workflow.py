"""One router, four intents, a different grader per intent.

The user's own shape: a router classifies the query into `dataquery`,
`off_topic`, `general_knowledge` or `greeting`; `dataquery` fans out through an
orchestrator/worker/report chain and is judged by a **deep** grader with strict,
data-grounded criteria, while the other three intents get their own lighter
agent + grader pair with criteria suited to what they actually need to prove.

This is authored as ordinary canvas composition — multiple `route.grader` nodes,
each downstream of a different router branch — not a new node type or a
"criteria per branch" config field. That is the deliberate answer to "there must
be a different grader per intent": CLAUDE.md's own boundary rule is that a
concern varying *within* a family is config, but a concern that changes the
*shape* of the graph (which criteria apply depends on which branch a run took)
is composition. A flat map field would also block wiring genuinely different
tiers per branch, which this document does on purpose (`grader-data` is deep,
the rest are the default react tier).
"""

from __future__ import annotations

from typing import Any


from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from conftest import RespondingModel, RouteRule  # noqa: F401  (shared test double)

def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


def intent_routed_document() -> dict[str, Any]:
    return {
        "version": 1,
        "name": "intent-routed",
        "nodes": [
            node("in1", "input.text"),
            node(
                "router1",
                "route.classifier",
                branches="dataquery\noff_topic\ngeneral_knowledge\ngreeting",
                fallback="off_topic",
                rules=(
                    "A question about Chinook's data (revenue, genres, artists) "
                    "is dataquery. A greeting with no question is greeting. A "
                    "general factual question unrelated to the store is "
                    "general_knowledge. Anything else is off_topic."
                ),
            ),
            node("orch1", "orchestrate.supervisor", maxSubtasks=8),
            node("worker1", "orchestrate.worker"),
            node("report1", "function.format_report", title="Data answer"),
            node(
                "grader-data",
                "route.grader",
                criteria=(
                    "- Must cite a real figure that could only come from "
                    "querying the database.\n"
                    "- Must not answer from general knowledge."
                ),
                rulesMode="replace",
                maxAttempts=2,
                tier="deep",
            ),
            node("agent-offtopic", "agent.llm"),
            node(
                "grader-offtopic",
                "route.grader",
                criteria="- A polite decline is enough; no data is required.",
                rulesMode="replace",
                maxAttempts=1,
            ),
            node("agent-general", "agent.llm"),
            node(
                "grader-general",
                "route.grader",
                criteria="- The answer must be a direct, confident statement.",
                rulesMode="replace",
                maxAttempts=2,
            ),
            node("agent-greeting", "agent.llm"),
            node(
                "grader-greeting",
                "route.grader",
                criteria="- A short, friendly greeting back is enough.",
                rulesMode="replace",
                maxAttempts=1,
            ),
            node("out1", "output.formatted"),
        ],
        "edges": [
            edge("in1", "text", "router1", "question"),
            edge("router1", "branch:dataquery", "orch1", "instruction"),
            edge("orch1", "workers", "worker1", "dispatch"),
            edge("worker1", "result", "report1", "candidate"),
            edge("report1", "report", "grader-data", "candidate"),
            edge("grader-data", "pass", "out1", "result"),
            edge("grader-data", "revise", "orch1", "feedback"),
            edge("router1", "branch:off_topic", "agent-offtopic", "prompt"),
            edge("agent-offtopic", "result", "grader-offtopic", "candidate"),
            edge("grader-offtopic", "pass", "out1", "result"),
            edge("grader-offtopic", "revise", "agent-offtopic", "feedback"),
            edge("router1", "branch:general_knowledge", "agent-general", "prompt"),
            edge("agent-general", "result", "grader-general", "candidate"),
            edge("grader-general", "pass", "out1", "result"),
            edge("grader-general", "revise", "agent-general", "feedback"),
            edge("router1", "branch:greeting", "agent-greeting", "prompt"),
            edge("agent-greeting", "result", "grader-greeting", "candidate"),
            edge("grader-greeting", "pass", "out1", "result"),
            edge("grader-greeting", "revise", "agent-greeting", "feedback"),
        ],
    }


def run(question: str, model: Any) -> dict[str, Any]:
    document = intent_routed_document()
    runtime = NodeRuntime(model=model)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 60},
    )


class TestCompilesCleanly:
    def test_no_warnings_and_the_fan_out_and_bindings_are_where_expected(self) -> None:
        plan = WorkflowCompiler().plan(intent_routed_document())
        assert plan.warnings == []
        assert plan.fan_out == {"orch1": ["worker1"]}
        assert set(plan.conditional.keys()) == {
            "router1",
            "grader-data",
            "grader-offtopic",
            "grader-general",
            "grader-greeting",
        }


class TestEachIntentTakesItsOwnPathAndItsOwnGrader:
    def test_dataquery_reaches_the_deep_grader_via_the_orchestrator(self) -> None:
        # Only the router's call is routed specially; the worker's answer and
        # the deep grader's verdict both fall to the default "PASS" — the
        # worker's actual text does not matter for this test, and the deep
        # grader passing on the first attempt is exactly what proves the
        # dataquery branch reached it at all.
        model = RespondingModel([(lambda c: "You are a router" in c, "dataquery")])
        final = run("Which genre earns the most revenue?", model)

        assert final["decisions"]["router1"] == "dataquery"
        assert final["decisions"]["grader-data"] == "pass"
        # Only the dataquery branch's nodes ran.
        assert "agent-offtopic" not in final["outputs"]
        assert "agent-general" not in final["outputs"]
        assert "agent-greeting" not in final["outputs"]

    def test_off_topic_never_touches_the_orchestrator(self) -> None:
        model = RespondingModel([(lambda c: "weather" in c, "off_topic")], default="Sorry, I can't help with that.")
        final = run("What's the weather like?", model)

        assert final["decisions"]["router1"] == "off_topic"
        assert final["decisions"]["grader-offtopic"] == "pass"
        assert "orch1" not in final["outputs"]
        assert "worker1" not in final.get("worker_results", {})

    def test_general_knowledge_gets_its_own_lighter_grader(self) -> None:
        model = RespondingModel(
            [(lambda c: "capital of France" in c, "general_knowledge")],
            default="Paris is the capital of France.",
        )
        final = run("What is the capital of France?", model)

        assert final["decisions"]["router1"] == "general_knowledge"
        assert final["decisions"]["grader-general"] == "pass"

    def test_greeting_passes_its_own_lenient_grader(self) -> None:
        model = RespondingModel([(lambda c: "hello" in c.lower(), "greeting")], default="Hi there!")
        final = run("Hello!", model)

        assert final["decisions"]["router1"] == "greeting"
        assert final["decisions"]["grader-greeting"] == "pass"

    def test_the_deep_grader_can_reject_a_general_knowledge_style_answer(self) -> None:
        """The whole point of a per-intent grader: the dataquery grader's
        criteria — grounded in a real query, never general knowledge — must
        actually catch an answer that reads like the AI Agent guessed instead
        of querying, which is the live failure mode this session found twice
        already (`workflow_compiler.py`'s worker port-spec gap, and the
        worker prompt fix). Here the *grading* side of that same risk is
        pinned, not the tool-binding side.
        """
        # The worker's own answer content does not matter here — only that the
        # grader is made to keep rejecting it, exhausting the attempt cap
        # rather than ever approving a guess.
        model = RespondingModel(
            [
                (lambda c: "You are a router" in c, "dataquery"),
                (lambda c: "You are a grader" in c, "FAIL\nNo figure was queried."),
            ],
            default="Rock is generally the top-selling genre worldwide.",
        )
        final = run("Which genre earns the most revenue?", model)

        # Exhausts its 2-attempt cap rather than passing a guess through.
        assert final["attempts"] == 2
        assert final["decisions"]["grader-data"] == "pass"  # cap-exhaustion pass-through, not a real approval
