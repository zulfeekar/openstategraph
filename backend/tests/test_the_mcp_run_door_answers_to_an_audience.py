"""`the-boundary-nobody-checked/08` — the MCP run door is a run door.

## The contradiction this settles

`mcp_server.py` said two things about `run_workflow` that cannot both be true:
it is *"the one a customer's own model calls"* (the run-journal note), and *"an
MCP client is composing a document, so it gets the compiler's own names"* (the
`mermaid` note) — an authoring transport. The payload believed the second.
Driven for real, with a model that emits a capability fence and a mount that
cannot resolve, the door answered a caller with no audience at all:

    answer:   "The first artist is AC/DC.\n\n```suggestion\n{…}\n```"
    outputs:  the same fence again, under every node
    warnings: ['The workflow node mounting "somewhere-else" …',
               'Node "sub1" produced no output. …']

The first sentence is the one that survives. Two things already in the tree
say so, and neither was written for this ticket: `WorkflowServices.runtime_for`
already names MCP among the transports that get the **customer** generation
half — *"only one of them may ever propose edits to the canvas"* — and
`docs/adoption.md` already declares advisor mode *"editor-only … and it must
never be reachable from `/chat` or MCP"*. The door was declared a customer
surface on the generation side and published authoring diagnostics on the
transport side.

## Where the audience comes from, and why it is not a tool argument

The MCP client is a **model** filling in a field. An audience a model can name
is `advisor` respelled — the request flag `api/audience.py` exists because of,
where a boolean on the customer's own endpoint put the boundary one DevTools
edit away. So the declaration is the **deployment's**: `OPENSTATEGRAPH_AUDIENCE`,
read through `audience.deployment_audience()`, which is `ceiling()` with the
safe floor under it. Unset — every default install — is `customer`, because for
a door whose caller cannot name an audience, the absence of a permission is not
a permission. An MCP deployment that is an authoring workbench says so once, in
its environment, where a person can see and change it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph.api.audience import Audience
from openstategraph.api.services import WorkflowServices
from openstategraph.mcp_server import EXPOSED_TOOLS, WorkflowRuns

from conftest import RespondingModel

FENCE = (
    "The first artist is AC/DC.\n\n"
    '```suggestion\n{"nodeType": "tool.email-send", "attachTo": "agent1", '
    '"reason": "so it can send the report"}\n```'
)

NODE_IDS = ("in1", "sub1", "agent1", "out1")


def _n(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "data": data, "position": {"x": 0, "y": 0}}


def _document() -> dict[str, Any]:
    """A real graph that produces both halves of the leak at once.

    `sub1` mounts a package that is not there, which is what earns the two
    authoring warnings naming a node id; `agent1` answers with a capability
    fence welded onto its prose, which is what earns the suggestion.
    """
    return {
        "version": 2,
        "name": "mcp-door",
        "nodes": [
            _n("in1", "input.text"),
            _n("sub1", "workflow.subgraph", workflow="somewhere-else"),
            _n("agent1", "agent.llm", instruction="Answer the question."),
            _n("out1", "output.formatted"),
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "sub1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "sub1", "portId": "result"},
                "target": {"nodeId": "agent1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "agent1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


@pytest.fixture()
def services(tmp_path: Path) -> WorkflowServices:
    root = tmp_path / "workflows"
    root.mkdir()
    return WorkflowServices(workflows_root=root)


@pytest.fixture()
def fenced_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import openstategraph.chat_model as chat_model

    model = RespondingModel([], default=FENCE)
    monkeypatch.setattr(chat_model, "build_chat_model", lambda *a, **k: model)


@pytest.mark.usefixtures("fenced_model")
class TestACustomerOverMcp:
    """The shape `tests/test_a_stored_run_answers_to_an_audience.py` uses."""

    def test_the_answer_carries_no_fence(self, services: WorkflowServices) -> None:
        result = WorkflowRuns(services).run(
            question="Who is the first artist?",
            document=_document(),
            audience=Audience.CUSTOMER,
        )

        assert result["error"] is None, result
        assert "```suggestion" not in result["answer"], result["answer"]
        assert "tool.email-send" not in result["answer"], result["answer"]
        assert "The first artist is AC/DC." in result["answer"]

    def test_no_node_output_carries_the_fence_either(
        self, services: WorkflowServices
    ) -> None:
        """Ticket 15's finding, on this door: `answer` was never the whole seam."""
        result = WorkflowRuns(services).run(
            question="Who is the first artist?",
            document=_document(),
            audience=Audience.CUSTOMER,
        )

        for node, value in result["outputs"].items():
            assert "```suggestion" not in value, (node, value)

    def test_authoring_warnings_are_absent_not_empty(
        self, services: WorkflowServices
    ) -> None:
        """Absent, exactly as `DeveloperChannel.payload` makes them absent.

        Empty would let a client read "there were no findings" out of a payload
        that was never entitled to carry any.
        """
        result = WorkflowRuns(services).run(
            question="Who is the first artist?",
            document=_document(),
            audience=Audience.CUSTOMER,
        )

        assert "warnings" not in result, result.get("warnings")
        assert "suggestion" not in result

    def test_no_node_id_reaches_the_customer_outside_the_outputs_keys(
        self, services: WorkflowServices
    ) -> None:
        """Over the whole payload, because the same sentence rode two fields.

        `outputs` is keyed by node id on every run door, for a customer too —
        that is the map's contract and `/api/runs` publishes it identically.
        What must not survive is a node id inside a *sentence*.
        """
        result = WorkflowRuns(services).run(
            question="Who is the first artist?",
            document=_document(),
            audience=Audience.CUSTOMER,
        )

        prose = json.dumps(
            {k: v for k, v in result.items() if k not in ("outputs", "mermaid")}
        )
        for node_id in NODE_IDS:
            assert f'"{node_id}"' not in prose, (node_id, prose)
        assert "somewhere-else" not in prose, prose

    def test_the_customer_is_still_told_the_run_was_degraded(
        self, services: WorkflowServices
    ) -> None:
        """Ticket 51's rule: the list stays developer-only, the *fact* cannot.

        Withholding the warnings without this leaves a customer reading a
        degraded answer as a confident one — which is a worse door than the
        one this ticket opened with.
        """
        result = WorkflowRuns(services).run(
            question="Who is the first artist?",
            document=_document(),
            audience=Audience.CUSTOMER,
        )

        assert "Note:" in result["answer"], result["answer"]


@pytest.mark.usefixtures("fenced_model")
class TestADeveloperOverMcp:
    def test_the_warnings_and_the_suggestion_both_arrive(
        self, services: WorkflowServices
    ) -> None:
        result = WorkflowRuns(services).run(
            question="Who is the first artist?",
            document=_document(),
            audience=Audience.DEVELOPER,
        )

        assert any("somewhere-else" in w for w in result["warnings"]), result["warnings"]
        assert result["suggestion"] == {
            "nodeType": "tool.email-send",
            "attachTo": "agent1",
            "reason": "so it can send the report",
        }

    def test_the_fence_still_leaves_the_answer(
        self, services: WorkflowServices
    ) -> None:
        """Split *unconditionally*, before anyone asks who is listening.

        `api/audience.py`'s move 2: a fence cannot appear in an answer because
        no code path puts one there. A developer reads it off `suggestion`.
        """
        result = WorkflowRuns(services).run(
            question="Who is the first artist?",
            document=_document(),
            audience=Audience.DEVELOPER,
        )

        assert "```suggestion" not in result["answer"], result["answer"]


class TestWhereTheAudienceComesFrom:
    def test_the_tool_takes_no_audience_argument(
        self, services: WorkflowServices
    ) -> None:
        """The decision, pinned: a model does not get to name its own audience.

        `run_workflow`'s MCP schema must not grow an `audience` field. If it
        ever does, the boundary is back to being a value the caller supplies —
        which is the `advisor` flag `api/audience.py` was written to delete.
        """
        import asyncio

        from openstategraph.mcp_server import build_mcp_server

        tools = {t.name: t for t in asyncio.run(build_mcp_server(services).list_tools())}

        assert "run_workflow" in tools and "run_workflow" in EXPOSED_TOOLS
        schema = tools["run_workflow"].inputSchema
        assert "audience" not in (schema.get("properties") or {}), schema

    def test_the_keyword_is_required_so_no_caller_inherits_the_refusal(
        self, services: WorkflowServices
    ) -> None:
        """`the-boundary-nobody-checked/02`'s pattern, for 02's reason.

        `read_run_bursts` took a required keyword with no default so the first
        replay door could not inherit the refusal silently. Same here: the
        audience *removes* content callers had, and a default would remove it
        from someone who never knew they were being asked.
        """
        with pytest.raises(TypeError):
            WorkflowRuns(services).run(question="hi", document=_document())  # type: ignore[call-arg]

    def test_an_unset_environment_is_a_customer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.audience import AUDIENCE_ENV, deployment_audience

        monkeypatch.delenv(AUDIENCE_ENV, raising=False)

        assert deployment_audience() is Audience.CUSTOMER

    def test_a_deployment_that_says_developer_gets_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.audience import AUDIENCE_ENV, deployment_audience

        monkeypatch.setenv(AUDIENCE_ENV, "developer")

        assert deployment_audience() is Audience.DEVELOPER

    def test_a_typo_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from openstategraph.api.audience import AUDIENCE_ENV, deployment_audience

        monkeypatch.setenv(AUDIENCE_ENV, "develloper")

        assert deployment_audience() is Audience.CUSTOMER


class TestTheSentenceThatWent:
    def test_the_module_no_longer_calls_this_an_authoring_transport(self) -> None:
        """One of the two sentences is gone, and this is which one.

        A source assertion rather than a behaviour one, because the defect was
        a *claim* — a module that argues it has no audience is a module the
        next reader will believe over the code.
        """
        source = (
            Path(__file__).resolve().parents[1]
            / "openstategraph"
            / "mcp_server.py"
        ).read_text()

        assert "composing a document, so it gets the compiler's own names" not in source
        assert "It is the one a customer's own model calls" in source
