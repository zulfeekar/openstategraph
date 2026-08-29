"""`launch-readiness/175` — the parallel router's second branch reaches a reader.

`matchMode: "all"` runs every desk the question belongs to, and the run
records which ones in `RunState.routes` — *"router node id -> **every** branch
label it matched"*. Until this ticket that channel was written by
`node_runtime._router`, read by the compiler's own conditional edge, and
published by **nobody**: `api/streaming.py` did not contain the word.

What every door published instead is `decisions[router]`, one label. So a
router that matched one branch and a router that matched three were the same
row — measured live on `.scratch/stress-2026-08-29/workflows/stress-parallel-drop`,
where `decisions` read `{"router": "b1"}` while `costdesk`, `riskdesk`, `out1`
and `out2` were all populated, and read `{"router": "b2"}` for the one-desk
question that genuinely only ran one.

The distinguishing test is therefore a *pair*: two runs of one document, and
the published result alone has to tell them apart.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app


def _node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "position": {"x": 0, "y": 0}, "data": data}


def _edge(source: str, source_port: str, target: str, target_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": source, "portId": source_port},
        "target": {"nodeId": target, "portId": target_port},
    }


def two_desk_document() -> dict[str, Any]:
    """`stress-parallel-drop` in miniature: one router in `all` mode, two desks.

    The branch *ids* are deliberately unlike the branch *names* — the model
    classifies by name and the graph dispatches on id, and a published field
    that leaked the name would be reporting something no edge points at.
    """
    return {
        "version": 1,
        "name": "two-desks",
        "nodes": [
            _node("in1", "input.text"),
            _node(
                "router1",
                "route.classifier",
                matchMode="all",
                branches=[{"id": "b-cost", "name": "cost"}, {"id": "b-risk", "name": "risk"}],
                instruction="Pick every desk the question belongs to.",
            ),
            _node("costdesk", "agent.llm"),
            _node("riskdesk", "agent.llm"),
            _node("out1", "output.formatted"),
        ],
        "edges": [
            _edge("in1", "text", "router1", "question"),
            _edge("router1", "branch:b-cost", "costdesk", "prompt"),
            _edge("router1", "branch:b-risk", "riskdesk", "prompt"),
            _edge("costdesk", "result", "out1", "result"),
            _edge("riskdesk", "result", "out1", "result"),
        ],
    }


def _model(classification: str) -> Any:
    """A model that answers the router with `classification` and desks with prose."""
    from conftest import RespondingModel

    return RespondingModel(
        [(lambda content: "router" in content.lower(), classification)],
        default="A desk answered.",
    )


def _client(monkeypatch: pytest.MonkeyPatch, classification: str) -> TestClient:
    from openstategraph import chat_model as chat_model_module

    monkeypatch.setattr(chat_model_module, "build_chat_model", lambda _name: _model(classification))
    return TestClient(create_app())


def _body() -> dict[str, Any]:
    return {
        "workflow": {"document": two_desk_document()},
        "question": "what does it cost and what could go wrong?",
        "workflow_slug": None,
        "thread_id": None,
        "session_id": "routes-test",
    }


def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    name: str | None = None
    for line in text.splitlines():
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: ") and name is not None:
            out.append((name, json.loads(line[len("data: ") :])))
            name = None
    return out


def _done(text: str) -> dict[str, Any]:
    return next(data for event, data in _events(text) if event == "done")


class TestTheLibraryDoor:
    """`RunResult`, which the CLI's `--json` and every script read."""

    def _run(self, monkeypatch: pytest.MonkeyPatch, classification: str) -> Any:
        """A real compiled graph over a real document, never a stubbed final
        state: the channel this ticket is about is written by a node and read
        by the compiler, so a hand-seeded state would prove nothing about
        either."""
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler
        from openstategraph.loader import CompiledWorkflow

        document = two_desk_document()
        runtime = NodeRuntime(model=_model(classification))
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        workflow = CompiledWorkflow(
            graph=graph, document=document, slug="two-desks", package_dir=Path(".")
        )
        return workflow.ask("what does it cost and what could go wrong?")

    def test_two_matched_branches_are_both_published(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._run(monkeypatch, "cost, risk")

        assert result.routes == {"router1": ["b-cost", "b-risk"]}

    def test_one_matched_branch_is_published_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Question 3 of the ticket, decided: **always**, never only when >1.

        Reporting the row only for a parallel match would make an absent key
        mean either "one desk ran" or "this build does not publish routes",
        which is the ambiguity the field exists to remove.
        """
        result = self._run(monkeypatch, "risk")

        assert result.routes == {"router1": ["b-risk"]}

    def test_the_two_runs_are_distinguishable_from_the_result_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ticket's own bar. `decisions` is identical in kind either way."""
        both = self._run(monkeypatch, "cost, risk")
        one = self._run(monkeypatch, "risk")

        assert len(both.routes["router1"]) == 2
        assert len(one.routes["router1"]) == 1

    def test_the_dispatched_label_is_always_one_of_the_published_ones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The invariant that keeps two fields from becoming two stories.

        `decisions[r]` is the label the conditional edge dispatched on;
        `routes[r]` is every label that ran. They are different facts about
        one router, and the only way they can disagree is a bug.
        """
        result = self._run(monkeypatch, "cost, risk")

        assert result.decisions["router1"] in result.routes["router1"]


class TestTheHttpDoors:
    def test_the_run_endpoint_publishes_every_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(monkeypatch, "cost, risk")
        payload = client.post("/api/runs", json=_body()).json()

        assert payload["routes"] == {"router1": ["b-cost", "b-risk"]}

    def test_the_run_endpoint_tells_one_desk_from_two(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(monkeypatch, "risk")
        payload = client.post("/api/runs", json=_body()).json()

        assert payload["routes"] == {"router1": ["b-risk"]}
        assert payload["decisions"] == {"router1": "b-risk"}

    def test_the_stream_publishes_it_on_the_terminal_frame(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The door the ticket measured as carrying the word zero times."""
        client = _client(monkeypatch, "cost, risk")
        response = client.post("/api/runs/stream", json=_body())

        assert _done(response.text)["routes"] == {"router1": ["b-cost", "b-risk"]}

    def test_a_customer_sees_it_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No audience gate: `decisions` has none, and this is the same fact
        about the same router — a node id, never a developer's guidance."""
        client = _client(monkeypatch, "cost, risk")
        body = {**_body(), "audience": "customer"}

        assert client.post("/api/runs", json=body).json()["routes"] == {
            "router1": ["b-cost", "b-risk"]
        }


class TestTheMcpDoor:
    """The door a customer's own LLM calls to run a workflow.

    It is the door most likely to be *composing* the document it just ran, so
    it is the one that most needs telling that `matchMode: "all"` opened two
    desks rather than one.
    """

    def test_run_workflow_publishes_every_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from openstategraph import chat_model as chat_model_module
        from openstategraph.api.services import WorkflowServices
        from openstategraph.mcp_server import WorkflowRuns

        monkeypatch.setattr(
            chat_model_module, "build_chat_model", lambda _name: _model("cost, risk")
        )
        services = WorkflowServices(workflows_root=Path("."))
        result = WorkflowRuns(services).run(
            document=two_desk_document(), question="cost and risk please"
        )

        assert result["error"] is None, result
        assert result["routes"] == {"router1": ["b-cost", "b-risk"]}


class TestNoSecondDoorDerivesItsOwn:
    """One seam, not five doors — `api/diagram.py`'s `workflow_mermaid` and
    `run_journal.run_turn` are the precedents, and `launch-readiness/174`
    measured what the alternative costs: the same run published the cost desk
    on one door and the risk desk on another because two folds raced.

    So `state["routes"]` is read in exactly two places — the compiler's own
    conditional edge, which dispatches on it, and `published_routes`, which is
    the seam every door calls.
    """

    ALLOWED = {
        # Dispatches on it. This is the consumer the channel was built for.
        "compile/workflow_compiler.py",
        # The seam itself.
        "compile/state.py",
        # The one exemption, and it is a fold rather than a publication: the
        # streaming door has no finished state to read, so it accumulates the
        # channel off the update frames going past — exactly as it does for
        # `forced`, `unrouted` and `retries` — and then hands what it gathered
        # to `published_routes` like everybody else. Named here rather than
        # implied, so the day it publishes its own derivation this falls over.
        "api/streaming.py",
    }

    def _modules(self) -> list[Path]:
        root = Path(__file__).resolve().parent.parent / "openstategraph"
        return sorted(root.rglob("*.py"))

    def test_only_the_seam_and_the_dispatcher_read_the_channel(self) -> None:
        root = Path(__file__).resolve().parent.parent / "openstategraph"
        offenders: list[str] = []
        for path in self._modules():
            relative = path.relative_to(root).as_posix()
            if relative in self.ALLOWED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in ast.walk(tree):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if not isinstance(func, ast.Attribute) or func.attr != "get":
                    continue
                if not call.args:
                    continue
                first = call.args[0]
                if isinstance(first, ast.Constant) and first.value == "routes":
                    offenders.append(f"{relative}:{call.lineno}")

        assert offenders == [], (
            "call published_routes() instead of reading the channel: " + ", ".join(offenders)
        )

    def test_the_walk_finds_the_two_it_allows(self) -> None:
        """Anti-vacuity: a parser that matched nothing would make the pin above
        true of an empty search."""
        root = Path(__file__).resolve().parent.parent / "openstategraph"
        found = {
            path.relative_to(root).as_posix()
            for path in self._modules()
            if '"routes"' in path.read_text(encoding="utf-8")
        }

        assert self.ALLOWED <= found
