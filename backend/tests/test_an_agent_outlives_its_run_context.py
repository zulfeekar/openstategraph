"""One compiled graph, many runs, one agent — `launch-readiness/182`.

`organisms-first-class/72` put the rendered run-context block into the agent
memo's key so the second caller could not be handed the first caller's tenant.
That was the right fix for the wrong lifetime: the memo *outlives every run*
(its own comment said so) and the key is a **per-run value**, so a workflow
declaring `caseId` built and kept one fully-assembled agent per run and never
evicted any of them. Measured before this file existed: 100 runs of one graph
against a fake model built 99 agents, retained ~6 MiB and ~1050 live objects
per run, and paid ~15 ms of rebuild — a floor, with no tools, rubric or
summarization wired.

**Where a user meets it.** Not `POST /api/runs`, which compiles a fresh graph
per request and throws the dict away with it. `CompiledWorkflow.ask` — the
library door `CLAUDE.md` advertises, *"a standard Python object that runs
anywhere Python runs"* — holds `graph` as a frozen field and re-invokes it
forever, as does any mount under a long-lived parent. The symptom is an
overnight OOM with every answer correct the whole way.

**What would still be green if the wrong thing were built?** A unit test of
`agent_for` — it would pass against a memo that merely looks tidy, and against
a per-run cache that rebuilds constantly. So every claim here is made against a
real `WorkflowCompiler().build(...)` graph invoked in a loop, counting the
library's own `create_agent` and censusing live objects, exactly as the probe
that found this did.

The isolation half is the one that outranks the leak, and it is asserted here
as well as in `test_context_reaches_a_prompt.py`: the fix removes `run_ctx`
from the key, so a test proving two run contexts cannot reach each other has to
sit beside the change that could break it.
"""

from __future__ import annotations

import gc
from typing import Any

import langchain.agents as lc_agents
import pytest

from openstategraph.abc.run_context_prompt import MARKER as RUN_CONTEXT_MARKER
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

from test_orchestrator_graph import RespondingModel, edge, node

#: Opted in, so the value reaches the prompt — which is the whole reason the
#: rendered block was ever in the memo key.
CASE_FIELD = {"key": "caseId", "type": "string", "label": "Case", "prompt": True}

#: Enough laps that "one per run" and "one, ever" cannot be confused, and few
#: enough that the suite does not slow down for it.
RUNS = 40


def _document(*, declares_context: bool = True, tier: str = "") -> dict[str, Any]:
    document: dict[str, Any] = {
        "version": 1,
        "name": "an-agent-outlives-its-run-context",
        "nodes": [
            node("in1", "input.text", prompt="hello"),
            node("a1", "agent.llm", systemPrompt="- Be brief.", **({"tier": tier} if tier else {})),
            node("out1", "output.formatted"),
        ],
        "edges": [
            edge("in1", "text", "a1", "prompt"),
            edge("a1", "result", "out1", "result"),
        ],
    }
    if declares_context:
        document["settings"] = {"context": [dict(CASE_FIELD)]}
    return document


def _graph(document: dict[str, Any], model: Any) -> Any:
    runtime = NodeRuntime(model=model)
    return WorkflowCompiler().build(document, RunState, runtime.factory(document))


@pytest.fixture()
def constructions(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """How many times the library actually assembled an agent.

    Counted at `langchain.agents.create_agent`, which `AbstractAgentNode.build`
    imports inside its own method — so patching the module attribute catches
    every tier without reaching into ours.
    """
    counted = [0]
    real = lc_agents.create_agent

    def counting(*args: Any, **kwargs: Any) -> Any:
        counted[0] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(lc_agents, "create_agent", counting)
    return counted


class TestOneGraphBuildsOneAgent:
    """The leak itself, at the layer it lives."""

    def test_a_distinct_run_context_value_per_run_still_builds_one_agent(
        self, constructions: list[int]
    ) -> None:
        graph = _graph(_document(), RespondingModel([], default="an answer"))
        graph.invoke({"messages": [], "question": "warm"}, context={"caseId": "warm"})
        constructions[0] = 0
        for i in range(RUNS):
            graph.invoke(
                {"messages": [], "question": f"q{i}"}, context={"caseId": f"case-{i}"}
            )
        assert constructions[0] == 0, (
            f"{constructions[0]} agents built across {RUNS} runs of ONE compiled "
            "graph — the memo is keyed on a per-run value and never evicts"
        )

    def test_what_the_graph_retains_does_not_grow_with_the_number_of_runs(self) -> None:
        """The `Done when` clause, censused rather than counted on a dict.

        A `len(built)` assertion would pass against a fix that swapped the
        dict for a bounded cache of live agents and still leaked the
        middleware behind them. `gc.get_objects()` across the loop asks the
        only question that matters: is anything still reachable afterwards?
        """
        graph = _graph(_document(), RespondingModel([], default="an answer"))
        graph.invoke({"messages": [], "question": "warm"}, context={"caseId": "warm"})
        gc.collect()
        before = len(gc.get_objects())
        for i in range(RUNS):
            graph.invoke(
                {"messages": [], "question": f"q{i}"}, context={"caseId": f"case-{i}"}
            )
        gc.collect()
        per_run = (len(gc.get_objects()) - before) / RUNS
        # Measured at ~1050/run before the fix and under 10 after it. The
        # bound is loose on purpose: this asserts "flat", not a figure.
        assert per_run < 100, f"{per_run:.0f} live objects retained per run"

    def test_the_cases_that_already_worked_still_build_nothing_extra(
        self, constructions: list[int]
    ) -> None:
        """A fix that makes the working case slow is not a fix.

        Recurring tenants — the shape `72` was written for — used to build one
        agent per *new* value. They now build none after the first.
        """
        graph = _graph(_document(), RespondingModel([], default="an answer"))
        graph.invoke({"messages": [], "question": "warm"}, context={"caseId": "t-0"})
        constructions[0] = 0
        for i in range(RUNS):
            graph.invoke(
                {"messages": [], "question": f"q{i}"}, context={"caseId": f"t-{i % 10}"}
            )
        assert constructions[0] == 0

    def test_a_workflow_declaring_no_run_context_is_unchanged(
        self, constructions: list[int]
    ) -> None:
        graph = _graph(
            _document(declares_context=False), RespondingModel([], default="an answer")
        )
        graph.invoke({"messages": [], "question": "warm"})
        constructions[0] = 0
        for i in range(RUNS):
            graph.invoke({"messages": [], "question": f"q{i}"})
        assert constructions[0] == 0


class TestTwoCallersStillCannotSeeEachOther:
    """`organisms-first-class/72`'s guarantee, which outranks the leak."""

    def test_each_run_is_told_its_own_value_and_never_the_previous_one(self) -> None:
        model = RespondingModel([], default="an answer")
        graph = _graph(_document(), model)
        graph.invoke({"messages": [], "question": "first"}, context={"caseId": "AAA"})
        first = "\n".join(model.calls)
        assert "AAA" in first

        object.__setattr__(model, "calls", [])
        graph.invoke({"messages": [], "question": "second"}, context={"caseId": "BBB"})
        second = "\n".join(model.calls)
        assert "BBB" in second, "the second caller was not told its own value"
        assert "AAA" not in second, (
            "the second caller was handed the first caller's run context — this "
            "is the leak `organisms-first-class/72` closed"
        )

    def test_a_run_supplying_nothing_is_told_nothing(self) -> None:
        """The empty section must not leave the marker, or a stale block, behind."""
        model = RespondingModel([], default="an answer")
        graph = _graph(_document(), model)
        graph.invoke({"messages": [], "question": "first"}, context={"caseId": "AAA"})
        object.__setattr__(model, "calls", [])
        graph.invoke({"messages": [], "question": "second"})
        sent = "\n".join(model.calls)
        assert "AAA" not in sent
        assert "Run context" not in sent


class TestBothTiersResolveTheMarker:
    """The delivery is a placeholder, so a tier that skips it is a live defect.

    `create_deep_agent` pre-assembles a middleware stack of its own and the
    slot table flattens into it, so "the react tier works" is not evidence
    about the harness tier. Asserted on both, and the assertion that matters is
    the negative one: a marker reaching a provider is the seam failing loudly
    into a customer's context window.
    """

    def test_neither_tier_ever_shows_a_model_the_marker(self) -> None:
        for tier in ("", "deep"):
            model = RespondingModel([], default="an answer")
            graph = _graph(_document(tier=tier), model)
            graph.invoke({"messages": [], "question": "q"}, context={"caseId": "AAA"})
            sent = "\n".join(model.calls)
            assert sent, tier
            assert "AAA" in sent, f"{tier or 'react'} tier was never told its value"
            assert RUN_CONTEXT_MARKER not in sent, (
                f"{tier or 'react'} tier sent the unresolved marker to a model"
            )

    def test_the_harness_tier_keeps_two_callers_apart_too(self) -> None:
        model = RespondingModel([], default="an answer")
        graph = _graph(_document(tier="deep"), model)
        graph.invoke({"messages": [], "question": "first"}, context={"caseId": "AAA"})
        object.__setattr__(model, "calls", [])
        graph.invoke({"messages": [], "question": "second"}, context={"caseId": "BBB"})
        sent = "\n".join(model.calls)
        assert "BBB" in sent
        assert "AAA" not in sent
