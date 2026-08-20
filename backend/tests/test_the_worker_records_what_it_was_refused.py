"""A worker asked for `web_fetch` and nobody was offered `tool.web-fetch`.

`every-workflow-green` 36, and it is 33's transcript on a different node
family. At `?w=morning-brief`, read out of the DOM:

    web_search  → six results
    web_fetch   → "Error: web_fetch is not a valid tool, try one of [...]"
    card        → absent

Ticket 33 built the deterministic route — read the name out of our own refusal,
look it up, offer the tool — and wired it into `_agent`. `_worker` returned
`worker_results` and `outputs` and nothing else, so a fan-out workflow's
refusals were never written to state and `suggestion_from_rejection` was handed
an empty dict. Both of 33's unit tests were green the whole time, because
neither of them asks a *node* anything.

So the pin here is a **census**, not a second copy of four lines. The worker's
own docstring already records this exact failure once, about `advisor_context`:
*"composed into one factory and not the other."* A capability every
tool-binding node needs belongs at the seam they share, and the next family
that binds tools should go red rather than quietly shut the door.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import openstategraph.abc.agent as agent_module
from openstategraph.compile import node_runtime as node_runtime_module
from openstategraph.compile.node_runtime import NodeRuntime, RunState, RuntimeServices
from openstategraph.compile.workflow_compiler import CompiledPlan, suggestion_from_rejection

from conftest import any_chat_model

REFUSAL = "Error: web_fetch is not a valid tool, try one of [web_search, knowledge_lookup]."


class _StubAgent:
    """The messages a refused loop actually leaves behind.

    The refusal is a `ToolMessage` in the middle; the answer is the last one
    and says nothing about it — which is the whole reason this is read from the
    messages rather than from the answer.
    """

    def invoke(self, _payload):
        from langchain_core.messages import AIMessage, ToolMessage

        return {
            "messages": [
                ToolMessage(content=REFUSAL, tool_call_id="call-1"),
                AIMessage(content="Here are three checklist sites."),
            ]
        }


class _RecordingNode:
    def __init__(self, **kwargs: object) -> None:
        self._kwargs = kwargs

    def build(self):
        return _StubAgent()


def _run_worker(monkeypatch) -> dict:
    monkeypatch.setattr(agent_module, "ReactAgentNode", _RecordingNode)
    runtime = NodeRuntime(services=RuntimeServices(model=any_chat_model()))  # type: ignore[arg-type]
    node = {
        "id": "worker-web",
        "type": "orchestrate.worker",
        "title": "Web researcher",
        "data": {"role": "Searches the open web."},
    }
    run = runtime._worker("worker-web", node, CompiledPlan())
    return run(RunState(task_id="task-1", task_instruction="get me checklists"))  # type: ignore[typeddict-item]


class TestTheWorkerWritesTheRefusalToState:
    def test_it_records_the_name_the_runtime_refused(self, monkeypatch) -> None:
        assert _run_worker(monkeypatch).get("unmet_tools") == {"worker-web": ["web_fetch"]}

    def test_it_still_returns_the_answer_and_the_task_result(self, monkeypatch) -> None:
        """The recording is additive. A refused loop still answered."""
        update = _run_worker(monkeypatch)
        assert update["worker_results"] == {"task-1": "Here are three checklist sites."}
        assert update["outputs"] == {"worker-web#task-1": "Here are three checklist sites."}

    def test_a_clean_run_writes_no_key_at_all(self, monkeypatch) -> None:
        """An empty map would be indistinguishable from a refusal nobody made."""

        class _CleanAgent:
            def invoke(self, _payload):
                from langchain_core.messages import AIMessage

                return {"messages": [AIMessage(content="done")]}

        class _CleanNode(_RecordingNode):
            def build(self):
                return _CleanAgent()

        monkeypatch.setattr(agent_module, "ReactAgentNode", _CleanNode)
        runtime = NodeRuntime(services=RuntimeServices(model=any_chat_model()))  # type: ignore[arg-type]
        run = runtime._worker("worker-web", {"id": "worker-web", "data": {}}, CompiledPlan())
        assert "unmet_tools" not in run(RunState(task_id="t", task_instruction="hi"))  # type: ignore[typeddict-item]


class TestTheDoorItOpens:
    def test_the_recorded_refusal_becomes_the_card_the_user_never_saw(self, monkeypatch) -> None:
        """End of the chain: state → offer, attached to the worker that asked."""
        offer = suggestion_from_rejection(_run_worker(monkeypatch)["unmet_tools"])
        assert offer is not None
        assert offer["nodeType"] == "tool.web-fetch"
        assert offer["attachTo"] == "worker-web"


class TestEveryToolBindingFactoryRecords:
    """The census, and the reason this ticket is not four copied lines.

    A factory that binds tools can be refused one. If it can be refused one it
    must say so, or the deterministic route is shut for that whole family and
    nothing reports it — which is exactly how this survived ticket 33 with two
    green tests.
    """

    def _factories(self) -> dict[str, ast.FunctionDef]:
        source = Path(inspect.getfile(node_runtime_module)).read_text(encoding="utf-8")
        tree = ast.parse(source)
        (cls,) = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == "NodeRuntime"
        ]
        binders = {}
        for member in cls.body:
            if not isinstance(member, ast.FunctionDef):
                continue
            text = ast.unparse(member)
            if "self._bind_tools(" in text:
                binders[member.name] = member
        return binders

    def test_the_census_finds_the_families_it_is_supposed_to(self) -> None:
        """If this goes red, a family appeared or vanished — read the next one."""
        assert set(self._factories()) == {"_agent", "_worker"}

    def test_every_one_of_them_records_what_it_was_refused(self) -> None:
        """Renamed to `tool_report` by `every-workflow-green` 35, which added a
        second fact to the same seam — what the node *used*. One function
        rather than two calls per site, so a family cannot acquire half of it:
        acquiring half is exactly what ticket 36 was."""
        missing = [
            name
            for name, fn in self._factories().items()
            if "tool_report(" not in ast.unparse(fn)
        ]
        assert missing == []
