"""A reply a grader has still to judge is marked as one, on the wire.

`every-workflow-green/45`. A grader-checked run puts its first attempt on
screen as soon as the model types it. On the run that produced the ticket that
attempt read *"total sales of $96,699.19"* — forty times the revenue the whole
database holds — and thirteen seconds later the grader rejected it and the
settled answer said **$826.65**. Three wrong figures reached careful readers by
that route in one day; each named the right genre, which is what makes the
money read as checked.

The claim under test is the ticket's own: **an unsettled answer does not go out
looking like a settled one.** It is asserted over
`data/recorded_concierge_customer_run.json` — a real 38-second run that goes
round the revision loop three times, `agent_sql` and `grader_sql` each landing
three `update` frames — rather than over this package's node ids, so it is a
claim about the mechanism and not about `chinook-assistant`.

Two properties matter as much as the marking itself, and both have a class
here:

- **A workflow with no grader gains nothing.** Most runs pass first time, and a
  label that appears and vanishes on every ordinary answer is noise that makes
  the feature worse than nothing. Absence of the flag is how a client tells
  *no grader is downstream* from *checked*.
- **The mark survives a mount.** The reply on the recording streams from
  `model`, inside `agent_sql`, inside a mounted `chinook-assistant`, judged by
  that child's `grader-sql`. No surface above the mount has heard of any of
  those names.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from conftest import ScriptedGraph, drive_fold  # noqa: E402

from openstategraph.api.audience import Audience
from openstategraph.api.streaming import _stream_run
from openstategraph.compile.checked_nodes import nodes_a_grader_checks
from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.compile.workflow_compiler import WorkflowCompiler

#: The graph names of the recording's machinery, as `test_customer_token_stream`
#: records them.
MACHINERY = frozenset({"in1", "router1", "grader_sql", "in_sql"})

#: What the composition's compile declares about that recording: the mounted
#: child's SQL agent, in both spellings. Deliberately the smallest true set —
#: the child's own output node runs after its grader's verdict and is not in
#: it, which is what gives the two classes below something to disagree about.
#: Recorded here as the *expected* value; production computes it from the plan.
CHECKED = frozenset({"agent_sql", "agent-sql"})


def _recorded() -> dict[str, Any]:
    path = Path(__file__).parent / "data" / "recorded_concierge_customer_run.json"
    return json.loads(path.read_text())


def _chunks() -> list[tuple[tuple[str, ...], str, Any]]:
    out: list[tuple[tuple[str, ...], str, Any]] = []
    for chunk in _recorded()["chunks"]:
        namespace = tuple(chunk["ns"])
        if chunk["mode"] == "updates":
            out.append((namespace, "updates", {chunk["node"]: {}}))
        else:
            message = SimpleNamespace(
                content=chunk["content"],
                type=chunk["type"],
                name=chunk["name"],
                tool_call_id="",
            )
            out.append(
                (namespace, "messages", (message, {"langgraph_node": chunk["node"]}))
            )
    return out


def _replay(audience: Audience, checked: frozenset[str]) -> list[tuple[str, dict[str, Any]]]:
    recorded = _recorded()

    class _Graph:
        def stream(self, *_args: Any, **_kwargs: Any) -> Any:
            return iter(_chunks())

        def get_state(self, _config: Any) -> Any:
            return SimpleNamespace(next=(), tasks=())

        def get_graph(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(draw_mermaid=lambda: "graph TD;")

    runtime = SimpleNamespace(
        diagnostics=CompileDiagnostics(),
        machinery_nodes=set(MACHINERY),
        checked_nodes=set(checked),
    )
    events: list[tuple[str, dict[str, Any]]] = []
    for frame in drive_fold(_stream_run(
        ScriptedGraph(_Graph()),
        {},
        {},
        SimpleNamespace(warnings=[]),
        recorded["nodeIdsByName"],
        runtime,
        "t1",
        audience,
    )):
        name = frame.split("\n")[0][len("event: ") :]
        events.append((name, json.loads(frame.split("\n")[1][len("data: ") :])))
    return events


def _reply_frames(events: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Token frames a client would actually print — content, not emptiness."""
    return [d for name, d in events if name == "token" and str(d.get("content") or "")]


class TestTheRecordedRevisionLoop:
    @pytest.fixture(scope="class")
    def frames(self) -> list[dict[str, Any]]:
        return _reply_frames(_replay(Audience.CUSTOMER, CHECKED))

    def test_the_run_really_goes_round_the_loop(self) -> None:
        """The fixture's own premise, held open.

        A recording that stopped looping would make every assertion below pass
        while testing nothing — the failure mode a fixture cannot report about
        itself.
        """
        laps = [
            c for c in _recorded()["chunks"]
            if c["mode"] == "updates" and c["node"] == "grader_sql"
        ]
        assert len(laps) >= 2

    def test_the_reply_in_flight_says_it_is_a_draft(
        self, frames: list[dict[str, Any]]
    ) -> None:
        drafts = [f for f in frames if f.get("draft")]
        assert drafts, "the streamed answer went out with nothing marking it unsettled"
        # Every one of them is the reply, streaming out of the mounted agent.
        assert {f["node"] for f in drafts} == {"model"}

    def test_the_marked_text_was_on_screen_before_the_verdict(self) -> None:
        """The damage, stated as an ordering fact about the recording.

        Every frame carrying the reply arrives before the grader update that
        judges it — which is the whole defect: complete, confident prose, on
        screen, with the verdict still to come. If a recording ever put the
        verdict first this assertion would fail, and the mark would be a lie
        rather than a warning.
        """
        chunks = _recorded()["chunks"]
        last_reply = max(
            i for i, c in enumerate(chunks)
            if c["mode"] == "messages" and c["node"] == "model" and c["content"]
        )
        last_verdict = max(
            i for i, c in enumerate(chunks)
            if c["mode"] == "updates" and c["node"] == "grader_sql"
        )
        assert last_reply < last_verdict

    def test_the_graders_own_verdict_is_never_a_draft(
        self, frames: list[dict[str, Any]]
    ) -> None:
        """Both clauses of `is_draft`, and this is the second one.

        A revision loop makes the grader reachable from itself, so plain
        reachability would put the mark on `FAIL Include the SQL SELECT
        statement...`. That text is not an answer at all, and a surface that
        labelled it *"draft"* would be promising to replace it with a better
        one.
        """
        del frames
        verdicts = [
            d
            for name, d in _replay(Audience.DEVELOPER, CHECKED)
            if name == "token" and d["node"] == "grader_sql" and d.get("content")
        ]
        assert any("FAIL" in str(d["content"]) for d in verdicts)
        assert not any(d.get("draft") for d in verdicts)
    def test_the_flag_is_absent_rather_than_false(
        self, frames: list[dict[str, Any]]
    ) -> None:
        """True-only, like `withheld`.

        A client that has never heard of the field must render what it always
        rendered, and `absent` must keep meaning *no grader is downstream* —
        the property the no-flicker rule rests on.
        """
        assert all(f["draft"] is True for f in frames if "draft" in f)

    def test_a_customer_is_told_too(self) -> None:
        """Not a developer-only fact — see the table in `api/audience.py`."""
        for audience in (Audience.CUSTOMER, Audience.DEVELOPER):
            frames = _reply_frames(_replay(audience, CHECKED))
            assert any(f.get("draft") for f in frames), audience


class TestAWorkflowWithNoGraderGainsNothing:
    def test_not_one_frame_is_marked(self) -> None:
        frames = _reply_frames(_replay(Audience.CUSTOMER, frozenset()))
        assert frames
        assert not any("draft" in f for f in frames)


class TestWhichNodesAGraderChecks:
    """The compiler half, over documents built here rather than shipped ones."""

    @staticmethod
    def _checked(document: dict[str, Any]) -> set[str]:
        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        types = {n["id"]: n["type"] for n in document["nodes"]}
        return nodes_a_grader_checks(plan, types)

    @staticmethod
    def _graded_document() -> dict[str, Any]:
        return {
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}},
                {"id": "writer", "type": "agent.llm", "data": {}},
                {"id": "judge", "type": "route.grader", "data": {}},
                {"id": "out1", "type": "output.formatted", "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"},
                 "target": {"nodeId": "writer", "portId": "prompt"}},
                {"source": {"nodeId": "writer", "portId": "result"},
                 "target": {"nodeId": "judge", "portId": "candidate"}},
                {"source": {"nodeId": "judge", "portId": "pass"},
                 "target": {"nodeId": "out1", "portId": "result"}},
                {"source": {"nodeId": "judge", "portId": "revise"},
                 "target": {"nodeId": "writer", "portId": "feedback"}},
            ],
        }

    def test_the_node_a_grader_judges_is_checked(self) -> None:
        assert "writer" in self._checked(self._graded_document())

    def test_the_node_after_the_verdict_is_not(self) -> None:
        """`out1` renders what the grader already passed.

        Marking it would put "not checked yet" on the settled answer itself,
        which is the defect inverted rather than fixed.
        """
        assert "out1" not in self._checked(self._graded_document())

    def test_a_document_with_no_grader_checks_nothing(self) -> None:
        document = self._graded_document()
        document["nodes"] = [n for n in document["nodes"] if n["id"] != "judge"]
        document["edges"] = [
            e
            for e in document["edges"]
            if "judge" not in (e["source"]["nodeId"], e["target"]["nodeId"])
        ] + [
            {"source": {"nodeId": "writer", "portId": "result"},
             "target": {"nodeId": "out1", "portId": "result"}}
        ]
        assert self._checked(document) == set()
