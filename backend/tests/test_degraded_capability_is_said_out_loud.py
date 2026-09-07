"""A capability that did not reach the run says so on **every** door — ticket 51.

The gap, exactly as the user seat found it. A workflow whose agent binds an MCP
server that has gone away:

    $ openstategraph run workflows/bad-mcp "What is create_agent? Use your tools."
    warning: MCP server "…" could not be reached at …. None of its tools are
             available for this run.

…and over HTTP, for the audience a paying customer actually is:

    POST /api/runs/stream   (same document, same question)
    frames mentioning "warning": 0
    final frame keys: threadId, answer, decisions, outputs, nested, attempts, mermaid

The answer the customer read was *"I don't have any stored information about
create_agent…"* — plausible, confident, and wrong. The tool was there
yesterday. Nothing on the page suggested today was different, so the only
explanation available to the reader was that the product does not know things.

## The audience decision, recorded here because it is the substance

A developer and a customer need opposite things from the same fact, and this is
the file where that is settled:

| | Gets | Why |
| --- | --- | --- |
| **developer** | the sentences verbatim, on `done.developer.warnings` | they name the server, the row and the node id — which is what makes them actionable, and unreadable to anyone else |
| **customer** | one softened sentence, **inside `answer`** | they cannot act on a URL, but they must not read a degraded answer as a confident one |

### Why the customer's half rides `answer` and not a new field

Three reasons, and the first is a hard constraint rather than a preference:

1. **`done` may not grow a `warnings` key on a customer run.** That is already
   an asserted boundary — `test_audience_boundary.py::
   test_a_customer_done_frame_carries_no_developer_channel_at_all` requires the
   key to be *absent*, not empty, so a client cannot read "there were no
   findings" out of a frame never entitled to carry any. Adding the field back
   would trade this ticket for that one.
2. **A field only helps a client that grows a branch for it.** `answer` is the
   one field every customer surface already renders, so the notice arrives on
   `/chat`, on `minimal-client.html` and on whatever anyone writes next,
   without a coordinated release. `chat.html` sets
   `answer.innerHTML = md(d.answer)` on `done`, so it lands as prose.
3. **A new frame kind would be a four-surface change** — `RUN_EVENTS`,
   `docs/api.md`, `docs/openapi.json` and *every* client the drift pin
   discovers — for a signal that has to end up in the reply anyway.

The precedent is `RUN_FAILED_ANSWER`, which already writes into `answer` on the
customer surface for the neighbouring case of a step that failed outright.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from openstategraph.api.audience import CAPABILITY_NOTICE, Audience, capability_notice
from openstategraph.api.main import create_app

UNREACHABLE = "https://qa-not-a-real-host-98765.example.com/mcp"


def _node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _degraded_doc() -> dict[str, Any]:
    """Input → output, plus one node whose capability nothing can bind.

    Deliberately **not** an agent: an agent needs a model, and a test that
    needs a credential is a test that does not run. What is being asserted is
    the transport — that a capability warning raised at bind time reaches the
    reader — and `function.nowhere` raises one through the very same
    `CompileDiagnostics` channel the MCP failure does (`Finding.
    UNRESOLVED_FUNCTION` beside `Finding.CAPABILITY_FAILED`). The MCP
    sentence's own wording is pinned in `test_prebuilt_mcp.py`.
    """
    return {
        "version": 1,
        "name": "degraded",
        "nodes": [
            _node("node:input.text-1", "input.text"),
            _node("node:function.nowhere-1", "function.nowhere"),
            _node("node:output.formatted-1", "output.formatted"),
        ],
        "edges": [
            _edge("node:input.text-1", "text", "node:function.nowhere-1", "text"),
            _edge("node:function.nowhere-1", "text", "node:output.formatted-1", "result"),
        ],
    }


def _healthy_doc() -> dict[str, Any]:
    return {
        "version": 1,
        "name": "healthy",
        "nodes": [
            _node("node:input.text-1", "input.text"),
            _node("node:output.formatted-1", "output.formatted"),
        ],
        "edges": [_edge("node:input.text-1", "text", "node:output.formatted-1", "result")],
    }


def _body(question: str, document: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow": {"document": document},
        "question": question,
        "workflow_slug": None,
        "thread_id": "t51",
        "session_id": "s1",
    }


def _done(text: str) -> dict[str, Any]:
    for line in text.splitlines():
        if line.startswith("data: "):
            data = json.loads(line[len("data: ") :])
            if "answer" in data and "mermaid" in data:
                return data
    raise AssertionError("no done frame in the stream")


class TestTheCustomerIsToldSomething:
    """The ticket's bar: *"`/chat` shows at least one of my tools was
    unavailable for this answer"*."""

    def test_a_degraded_run_says_so_in_the_answer(self) -> None:
        client = TestClient(create_app())
        done = _done(
            client.post("/api/runs/stream", json=_body("hello", _degraded_doc())).text
        )

        assert CAPABILITY_NOTICE in done["answer"]

    def test_the_answer_itself_still_arrives_ahead_of_the_notice(self) -> None:
        """A notice that replaced the answer would be a worse bug than the one
        being fixed. It is an aside, appended, and the reply comes first."""
        client = TestClient(create_app())
        done = _done(
            client.post("/api/runs/stream", json=_body("hello", _degraded_doc())).text
        )

        assert done["answer"].startswith("hello")
        assert done["answer"].index("hello") < done["answer"].index(CAPABILITY_NOTICE)

    def test_a_healthy_run_says_nothing(self) -> None:
        """The notice must stay rare enough to mean something. A run that lost
        no capability reads exactly as it did before this ticket."""
        client = TestClient(create_app())
        done = _done(
            client.post("/api/runs/stream", json=_body("hello", _healthy_doc())).text
        )

        assert done["answer"] == "hello"
        assert CAPABILITY_NOTICE not in done["answer"]

    def test_the_sentences_themselves_still_never_reach_a_customer(self) -> None:
        """The softening is the whole point. A customer gets *that* something
        was missing, never *what* — the raw sentence names a node id, a server
        row and a URL, which is why `/chat` stopped printing them (ticket 04).
        """
        client = TestClient(create_app())
        response = client.post("/api/runs/stream", json=_body("hi", _degraded_doc()))

        assert "No function found for" not in response.text
        assert "function.nowhere" not in _done(response.text)["answer"]
        # …and the boundary that made a new `warnings` field impossible is
        # still exactly where it was.
        assert "warnings" not in _done(response.text)
        assert "developer" not in _done(response.text)

    def test_the_blocking_door_is_not_the_way_around(self) -> None:
        """`/api/runs` and `/api/runs/stream` are two doors on one seam. A
        customer who posts to the quiet one must not get the confident answer
        the noisy one refuses to give."""
        client = TestClient(create_app())
        response = client.post("/api/runs", json=_body("hello", _degraded_doc()))

        assert response.status_code == 200
        assert CAPABILITY_NOTICE in response.json()["answer"]


class TestADeveloperStillGetsTheRealThing:
    def test_the_sentences_arrive_verbatim_on_the_channel(self) -> None:
        client = TestClient(create_app())
        body = _body("hi", _degraded_doc())
        body["audience"] = "developer"
        done = _done(client.post("/api/runs/stream", json=body).text)

        assert any("function.nowhere" in w for w in done["developer"]["warnings"])

    def test_a_developers_answer_is_not_softened(self) -> None:
        """They are reading the warnings list; a vague sentence in the prose
        would be noise on top of the specific one they already have."""
        client = TestClient(create_app())
        body = _body("hello", _degraded_doc())
        body["audience"] = "developer"
        done = _done(client.post("/api/runs/stream", json=body).text)

        assert CAPABILITY_NOTICE not in done["answer"]


class TestTheNoticeItself:
    def test_it_fires_only_for_a_customer_with_something_to_report(self) -> None:
        assert capability_notice(["a warning"], Audience.CUSTOMER) == CAPABILITY_NOTICE
        assert capability_notice([], Audience.CUSTOMER) == ""
        assert capability_notice(["a warning"], Audience.DEVELOPER) == ""

    def test_it_names_no_node_no_server_and_no_url(self) -> None:
        """A sentence a customer can read without meeting our vocabulary."""
        for word in ("node:", "http", "MCP", "function.", "tool."):
            assert word not in CAPABILITY_NOTICE

    def test_it_carries_no_markdown(self) -> None:
        """Found in a browser, not in review, which is why it is pinned.

        The first version was wrapped in `_underscores_` to read as an italic
        aside. `/chat` renders `answer` through its own small `md()`, which
        implements `**bold**`, `` `code` ``, lists, tables and headings — and
        no italics — so the customer read the underscores. A string the server
        writes into `answer` is read by every client that exists and every
        client that will, so it may assume no renderer at all.
        """
        for markup in ("_", "*", "`", "#", "|", "<"):
            assert markup not in CAPABILITY_NOTICE


def _report_only_doc() -> dict[str, Any]:
    """A run that loses no capability and still produces a warning.

    `guard.check` with `revise` wired to nothing records
    `Finding.UNWIRED_REVISE` — advice about the drawing, on `REPORT_ONLY`
    since `workflow-gallery` 31, and a **static property of the document**: it
    cannot be absent on any run of this graph. The check itself is built in,
    so nothing here needs a model or a credential; the graph answers
    correctly, every time, and used to carry the notice anyway.
    """
    return {
        "version": 1,
        "name": "report-only",
        "nodes": [
            _node("node:input.text-1", "input.text"),
            _node("node:guard.check-1", "guard.check", check="numbers_in_prose"),
            _node("node:output.formatted-1", "output.formatted"),
        ],
        "edges": [
            _edge("node:input.text-1", "text", "node:guard.check-1", "candidate"),
            _edge("node:guard.check-1", "pass", "node:output.formatted-1", "result"),
        ],
    }


class TestTheNoticeIsAboutACapabilityAndNotAboutAdvice:
    """`every-workflow-green` 47 — the notice was on for every run there is.

    `CAPABILITY_NOTICE` claims one thing exactly, and every word of it was
    argued: a capability **did not reach this run**. The condition it was
    computed from was `plan.warnings + runtime_warnings(runtime)` — the whole
    developer channel, which carries advice about the drawing and reports
    about what happened alongside the capability losses.

    So `concierge` ended three correct live answers — *59 customers*, *Rock,
    $826.65*, *1,069 tracks* — with "part of this workflow was unavailable".
    Nothing was. Its only warnings were `Finding.UNDECLARED_FALLBACK`, a
    static property of the shipped document, so the sentence could never be
    off. A notice that is always on is a notice nobody reads, and then ticket
    51 — which put the notice there to keep a degraded run from reading as a
    confident one — buys nothing either.

    Reproduced here with the same shape and no model: a warning that is a
    report, a run that answers correctly, and a customer who must be told
    nothing.
    """

    def test_a_report_only_warning_produces_no_notice_on_the_streaming_door(self) -> None:
        client = TestClient(create_app())
        done = _done(
            client.post("/api/runs/stream", json=_body("hello", _report_only_doc())).text
        )

        assert CAPABILITY_NOTICE not in done["answer"]
        assert done["answer"] == "hello"

    def test_a_report_only_warning_produces_no_notice_on_the_blocking_door(self) -> None:
        client = TestClient(create_app())
        body = _body("hello", _report_only_doc())

        assert CAPABILITY_NOTICE not in client.post("/api/runs", json=body).json()["answer"]

    def test_a_report_only_warning_produces_no_notice_on_the_mcp_door(self, tmp_path) -> None:
        """Three doors, not one — ticket 15's rule. A fix at one is a fourth
        spelling waiting."""
        from openstategraph.api.services import WorkflowServices
        from openstategraph.mcp_server import WorkflowRuns

        root = tmp_path / "workflows"
        root.mkdir()
        result = WorkflowRuns(WorkflowServices(workflows_root=root)).run(
            question="hello",
            document=_report_only_doc(),
            audience=Audience.CUSTOMER,
        )

        assert result["error"] is None, result
        assert CAPABILITY_NOTICE not in result["answer"]

    def test_the_warning_still_reaches_the_developer_unchanged(self) -> None:
        """The two lists have different jobs, and this ticket is the evidence
        that one variable cannot hold both. Nothing left the channel."""
        client = TestClient(create_app())
        body = _body("hello", _report_only_doc())
        body["audience"] = "developer"
        done = _done(client.post("/api/runs/stream", json=body).text)

        assert any("revise" in w for w in done["developer"]["warnings"])

    def test_a_genuine_capability_loss_still_says_so_at_every_door(self, tmp_path) -> None:
        """The other half, or the fix is a deletion. Ticket 43's shape."""
        from openstategraph.api.services import WorkflowServices
        from openstategraph.mcp_server import WorkflowRuns

        client = TestClient(create_app())
        streamed = _done(
            client.post("/api/runs/stream", json=_body("hello", _degraded_doc())).text
        )
        blocking = client.post("/api/runs", json=_body("hello", _degraded_doc())).json()
        root = tmp_path / "workflows"
        root.mkdir()
        over_mcp = WorkflowRuns(WorkflowServices(workflows_root=root)).run(
            question="hello",
            document=_degraded_doc(),
            audience=Audience.CUSTOMER,
        )

        assert CAPABILITY_NOTICE in streamed["answer"]
        assert CAPABILITY_NOTICE in blocking["answer"]
        assert CAPABILITY_NOTICE in over_mcp["answer"]

    def test_a_plan_finding_is_not_a_capability_loss_either(self) -> None:
        """`plan.warnings` is `validate`'s PROBLEMS FOUND about the document as
        an artifact — never a claim that a capability was missing. It left the
        notice's condition with the reports."""
        from openstategraph.api.audience import capability_loss_warnings

        class _Diagnostics:
            @staticmethod
            def failure_warnings() -> list[str]:
                return []

        class _Runtime:
            diagnostics = _Diagnostics()

        assert capability_loss_warnings(_Runtime()) == []

    def test_no_door_computes_the_condition_for_itself(self) -> None:
        """The check lives beside `CAPABILITY_NOTICE` so that what the sentence
        claims and what triggers it are one declaration.

        A caller assembling its own list is a caller that will one day compute
        the notice from a different list than the one it reports — which is
        this ticket, at three doors at once. `with_capability_notice` takes the
        **runtime** for that reason, so there is no list left to get wrong, and
        this is what fails on a fourth door that reintroduces one.
        """
        import ast
        from pathlib import Path

        import openstategraph

        root = Path(openstategraph.__file__).parent
        offenders: list[str] = []
        for module in root.rglob("*.py"):
            tree = ast.parse(module.read_text(), filename=str(module))
            for call in ast.walk(tree):
                if not isinstance(call, ast.Call):
                    continue
                name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                if name != "with_capability_notice" or len(call.args) < 2:
                    continue
                second = call.args[1]
                if not (isinstance(second, ast.Name) and second.id == "runtime"):
                    offenders.append(f"{module.relative_to(root)}:{call.lineno}")

        assert offenders == [], offenders
