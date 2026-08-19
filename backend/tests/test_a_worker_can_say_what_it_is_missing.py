"""A worker with no tools narrated instead of saying it was stuck.

`every-workflow-green` 19. `archetype-orchestrator-report` wires no tool nodes
at all. Its Researcher, whose role is "Gathers and states the facts", published
this as the report:

    We need to find best practice sources. Let's search.Let's actually run the
    search.Search.Let's run.I need to actually invoke browser.search.Okay.

An **agent** in the same position behaves correctly — `classifier-router-qa`'s
`agent-world` answered "I don't have a tool that can retrieve real-time
information" and emitted a capability suggestion, which the editor turned into
an "Add & re-run" card.

The difference was not the model and not the prompt author. `advisor_context`
was composed into `_agent` and never into `_worker`, so a worker had no way to
say it was missing something. It flailed in prose instead, and the flailing was
the deliverable.
"""

from __future__ import annotations

import openstategraph.abc.agent as agent_module
from openstategraph.compile.node_runtime import NodeRuntime, RunState, RuntimeServices
from openstategraph.compile.workflow_compiler import CompiledPlan

from conftest import any_chat_model


class _RecordingNode:
    """Records construction instead of building — no model, no network."""

    built: list["_RecordingNode"] = []

    def __init__(self, **kwargs: object) -> None:
        self._kwargs = kwargs

    def resolve_prompt(self) -> str:
        """The composed prompt, as `SystemPrompt` would order it."""
        parts = [self._kwargs.get("context") or "", self._kwargs.get("default_rules") or ""]
        return "\n\n".join(str(p) for p in parts if p)

    def build(self):
        _RecordingNode.built.append(self)
        return _StubAgent()


class _StubAgent:
    """Stands in for the compiled agent — the worker invokes what `build`
    returns, unlike `_agent`, which hands the compiled object back."""

    def invoke(self, _payload):
        from langchain_core.messages import AIMessage

        return {"messages": [AIMessage(content="done")]}


def _worker_prompt(**services_kwargs: object) -> str:
    _RecordingNode.built.clear()
    runtime = NodeRuntime(services=RuntimeServices(model=any_chat_model(), **services_kwargs))  # type: ignore[arg-type]
    node = {
        "id": "worker-research",
        "type": "orchestrate.worker",
        "title": "Researcher",
        "data": {"role": "Gathers and states the facts."},
    }
    run = runtime._worker("worker-research", node, CompiledPlan())
    run(RunState(task_id="task-1", task_instruction="Find best practices"))  # type: ignore[typeddict-item]
    (built,) = _RecordingNode.built
    return built.resolve_prompt() or ""


class TestTheWorkerIsToldHowToAskForACapability:
    def test_with_a_catalogue_it_can_suggest(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_module, "ReactAgentNode", _RecordingNode)
        prompt = _worker_prompt(advisor_catalog="- tool.web-search — searches the web")
        assert "```suggestion" in prompt

    def test_attach_to_is_prefilled_with_this_workers_own_node_id(self, monkeypatch) -> None:
        """The card can only be applied if it names a node on the canvas."""
        monkeypatch.setattr(agent_module, "ReactAgentNode", _RecordingNode)
        prompt = _worker_prompt(advisor_catalog="- tool.web-search — searches the web")
        assert "worker-research" in prompt

    def test_without_a_catalogue_nothing_is_composed(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_module, "ReactAgentNode", _RecordingNode)
        assert "```suggestion" not in _worker_prompt()

    def test_the_role_still_comes_first(self, monkeypatch) -> None:
        """The advisor is machinery. It must not displace what this worker is."""
        monkeypatch.setattr(agent_module, "ReactAgentNode", _RecordingNode)
        prompt = _worker_prompt(advisor_catalog="- tool.web-search — searches the web")
        assert prompt.index("Gathers and states the facts.") < prompt.index("```suggestion")
