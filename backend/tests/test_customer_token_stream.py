"""A customer's `token` stream carries the reply, and nothing that produced it.

## The finding

`api/audience.py` closed the boundary on the **settled** answer — the `done`
frame, the `outputs` map, an `interrupt` candidate — and closed one streaming
hole with `ProseGuard`, which strips a ```suggestion fence out of `token`
frames as they are produced.

That left the other half of the streaming path wide open, and QA watched it:
on `/chat`, running `concierge` against a real model, the block that becomes
the answer showed — mid-run, for tens of seconds at a time — a Chinook schema
dump, the router's chosen branch name `music_store`, the mounted router's
`data_query`, and the grader's `FAIL` verdict welded onto the end of a
sentence. Every one of those arrived as a `token` frame, because the fold
emitted **every** message LangGraph produced: a tool's result, a classifier's
one-word decision, a grader's rubric complaint, the input node's echo of the
question.

`ProseGuard` could never have caught any of it. It polices one *marker inside*
model prose; this is text that is not the reply at all.

## The fixture

`data/recorded_concierge_customer_run.json` is one real run of `concierge`
("Which music genre earned the most revenue?", 38 s, `gpt-oss:120b-cloud`),
recorded off `/api/runs/stream` frame by frame with the **content kept** —
which is the point, and the difference from
`recorded_chinook_assistant_run.json`, whose prose was replaced by its length
because that recording is about namespaces rather than about what was said.
Here the bytes ARE the evidence: the assertions below search them for the
exact strings QA read on screen.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.api.audience import AnswerChannel, Audience
from openstategraph.api.streaming import _stream_run

#: What QA saw in the answer area, verbatim from the ticket.
BRANCH_TOKEN = "music_store"
MOUNTED_BRANCH_TOKEN = "data_query"
GRADER_VERDICT = "FAIL"
SCHEMA_DUMP = "| Column | Type | PK |"
QUESTION = "Which music genre earned the most revenue?"

#: The graph node names of `concierge` and the `chinook-assistant` it mounts
#: whose streamed text is machinery. Recorded here as the *expected* value so
#: this test fails loudly if `NodeRuntime` stops declaring one of them; the
#: production value is computed from node types, never hand-listed.
MACHINERY = frozenset({"in1", "router1", "grader_sql", "in_sql"})


def _recorded() -> dict[str, Any]:
    path = Path(__file__).parent / "data" / "recorded_concierge_customer_run.json"
    return json.loads(path.read_text())


def _chunks() -> list[tuple[tuple[str, ...], str, Any]]:
    """The recording, back in the shape `graph.stream()` yields."""
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


def _replay(audience: Audience) -> list[tuple[str, dict[str, Any]]]:
    """The recorded run pushed back through the real fold, for one audience."""
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
    )
    events: list[tuple[str, dict[str, Any]]] = []
    for frame in _stream_run(
        _Graph(),
        {},
        {},
        SimpleNamespace(warnings=[]),
        recorded["nodeIdsByName"],
        runtime,
        "t1",
        audience,
    ):
        name = frame.split("\n")[0][len("event: ") :]
        events.append((name, json.loads(frame.split("\n")[1][len("data: ") :])))
    return events


def _streamed_text(events: list[tuple[str, dict[str, Any]]]) -> str:
    """Everything a client that concatenates `token` frames would display.

    Which is precisely what both surfaces do — `chat.html`'s thinking pane is
    `tokens += d.content`, and `AskPanel` folds the same way.
    """
    return "".join(str(d.get("content") or "") for name, d in events if name == "token")


class TestWhatACustomerWatches:
    """The ticket, string by string."""

    @pytest.fixture(scope="class")
    def streamed(self) -> str:
        return _streamed_text(_replay(Audience.CUSTOMER))

    def test_no_router_branch_name_reaches_the_customer(self, streamed: str) -> None:
        assert BRANCH_TOKEN not in streamed
        assert MOUNTED_BRANCH_TOKEN not in streamed

    def test_no_grader_verdict_reaches_the_customer(self, streamed: str) -> None:
        assert GRADER_VERDICT not in streamed

    def test_no_raw_tool_output_reaches_the_customer(self, streamed: str) -> None:
        assert SCHEMA_DUMP not in streamed
        assert "InvoiceLine" not in streamed

    def test_no_tool_name_reaches_the_customer(self, streamed: str) -> None:
        assert "chinook_execute_sql" not in streamed
        assert "chinook_get_table_schema" not in streamed

    def test_the_question_is_not_echoed_back_as_if_it_were_the_reply(
        self, streamed: str
    ) -> None:
        """`in1` writes the turn's `HumanMessage`, which rode this stream."""
        assert QUESTION not in streamed

    def test_the_reply_itself_still_streams(self, streamed: str) -> None:
        """A boundary, not a mute button: the answer must still arrive live."""
        assert "The Rock genre generated the highest revenue" in streamed
        assert "$826.65" in streamed

    def test_the_run_still_ends_the_way_it_did(self) -> None:
        """A gate on one frame type must not change how a stream finishes.

        (The recording keeps only the *shape* of each `updates` chunk, not the
        state it carried, so what the `done` frame says about `answer` is
        `test_audience_boundary`'s subject and not this one's.)
        """
        events = _replay(Audience.CUSTOMER)
        assert events[-1][0] == "done"

    def test_the_highlight_still_moves_while_a_node_works(self) -> None:
        """`activeNode` (ticket 02) must survive the gate.

        The first cut of this fix *dropped* the frame, and on the live stack
        the customer's ring then sat on `router1` for the eleven seconds the
        mounted analyst worked — ticket 02's bug, reintroduced for the one
        audience with no trace to fall back on. So a withheld frame is emptied
        rather than dropped, and this is the test that says so: the mount must
        light up from a *token* frame, the only kind that arrives mid-node.
        """
        events = _replay(Audience.CUSTOMER)
        assert any(
            name == "token" and d.get("activeNode") == "wf-music" for name, d in events
        )

    def test_a_withheld_frame_says_that_it_is_withheld(self) -> None:
        """Empty content that explains itself, rather than an implied silence."""
        withheld = [
            d for name, d in _replay(Audience.CUSTOMER)
            if name == "token" and d.get("withheld")
        ]
        assert withheld, "the recording contains machinery frames; none were marked"
        assert all(d["content"] == "" for d in withheld)
        assert all(d["tool"]["name"] == "" for d in withheld)

    def test_a_client_that_never_heard_of_the_field_is_still_safe(self) -> None:
        """The property that makes this a boundary rather than a convention.

        `chat.html` before this change was `tokens += d.content`. That exact
        fold, run over the customer stream, must produce a clean string — the
        bytes are not in the browser to be rendered by accident.
        """
        naive = "".join(
            str(d.get("content") or "")
            for name, d in _replay(Audience.CUSTOMER)
            if name == "token"
        )
        for leak in (BRANCH_TOKEN, MOUNTED_BRANCH_TOKEN, GRADER_VERDICT, SCHEMA_DUMP):
            assert leak not in naive


class TestADeveloperStillSeesEverything:
    """The editor's trace tree is built from exactly these frames.

    `AskPanel` sends `audience: "developer"` and folds tool `token` frames into
    its per-call result cards, so gating them for everyone would delete the
    feature rather than move it behind the boundary.
    """

    @pytest.fixture(scope="class")
    def streamed(self) -> str:
        return _streamed_text(_replay(Audience.DEVELOPER))

    def test_the_developer_sees_the_branch_the_router_chose(self, streamed: str) -> None:
        assert BRANCH_TOKEN in streamed
        assert MOUNTED_BRANCH_TOKEN in streamed

    def test_the_developer_sees_the_grader_verdict(self, streamed: str) -> None:
        assert GRADER_VERDICT in streamed

    def test_the_developer_sees_raw_tool_output(self, streamed: str) -> None:
        assert SCHEMA_DUMP in streamed

    def test_nothing_is_marked_withheld_on_a_developer_stream(self) -> None:
        """So "did I get the whole stream" stays answerable from the frames."""
        assert not any(
            d.get("withheld") for name, d in _replay(Audience.DEVELOPER) if name == "token"
        )


class TestTheChannelItself:
    """`AnswerChannel` in isolation — the rule, without a run around it."""

    channel = AnswerChannel(machinery=frozenset({"router1", "grader_sql"}))

    def test_a_tool_result_is_never_the_reply(self) -> None:
        assert not self.channel.carries("agent_sql", "tool")

    def test_a_declared_machinery_node_is_never_the_reply(self) -> None:
        assert not self.channel.carries("router1", "ai")
        assert not self.channel.carries("grader_sql", "ai")

    def test_an_agents_own_model_step_is_the_reply(self) -> None:
        assert self.channel.carries("model", "ai", ("agent_sql:abc",))

    def test_an_output_node_is_the_reply(self) -> None:
        assert self.channel.carries("out1", "ai")

    def test_a_machinery_node_owns_its_inner_steps_too(self) -> None:
        """A `tier: "deep"` router classifies inside a compiled deep agent.

        Its text then arrives as a `model` frame under the *router's* checkpoint
        namespace, so the frame's own name says nothing. Any namespace segment
        naming machinery settles it — otherwise `tier: "deep"` would silently
        reopen the leak this closes.
        """
        assert not self.channel.carries("model", "ai", ("router1:ckpt-1",))
        assert not self.channel.carries(
            "model", "ai", ("wf_music:a", "grader_sql:b")
        )

    def test_a_canvas_id_that_is_not_its_graph_name_is_still_recognised(self) -> None:
        """Node ids carry colons; LangGraph node names may not.

        `node_ids_by_name` maps one to the other, and a `token` frame is
        reported under the canvas id — so a channel that knew only graph names
        would wave every such node through. Both spellings are declared.
        """
        channel = AnswerChannel(machinery=frozenset({"node_router_1", "node:router.1"}))
        assert not channel.carries("node:router.1", "ai")
        assert not channel.carries("model", "ai", ("node_router_1:ckpt",))

    def test_with_nothing_declared_only_tool_output_is_withheld(self) -> None:
        """An ad-hoc caller, or a runtime too old to declare its machinery.

        Fails towards showing prose rather than towards a silent mute: the
        `kind` test needs no cooperation from the compiler and still removes
        the largest leak by volume.
        """
        bare = AnswerChannel()
        assert bare.carries("router1", "ai")
        assert not bare.carries("router1", "tool")


class TestTheRuntimeDeclaresItsOwnMachinery:
    """The set is computed from node types — never hand-listed at the seam."""

    def test_a_runtime_names_every_control_node_in_the_document(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime

        runtime = NodeRuntime(model=None)
        runtime.factory(
            {
                "nodes": [
                    {"id": "node:input.text-1", "type": "input.text"},
                    {"id": "router1", "type": "route.classifier"},
                    {"id": "grader1", "type": "route.grader"},
                    {"id": "agent1", "type": "agent.llm"},
                    {"id": "out1", "type": "output.formatted"},
                ],
                "edges": [],
            }
        )
        assert runtime.machinery_nodes == {
            "node:input.text-1",
            "node_input_text_1",
            "router1",
            "grader1",
        }

    def test_a_mounted_childs_machinery_is_the_parents_too(self, tmp_path: Any) -> None:
        """The leak QA saw most of: `data_query` came from a *child* router.

        A mount compiles a whole second document whose node names the parent
        has never heard of, and those frames ride the parent's one stream. If
        the set stopped at the parent's own nodes, every mounted router and
        grader would stream its decision to the customer — which is exactly
        what happened.
        """
        from openstategraph.compile.node_runtime import NodeRuntime, RuntimeServices

        child = {
            "version": 1,
            "name": "child",
            "nodes": [
                {"id": "in_sql", "type": "input.text", "data": {}},
                {"id": "router_sql", "type": "route.classifier",
                 "data": {"branches": [{"id": "b", "name": "only"}]}},
                {"id": "out_sql", "type": "output.formatted", "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in_sql", "portId": "text"},
                 "target": {"nodeId": "router_sql", "portId": "text"}},
                {"source": {"nodeId": "router_sql", "portId": "branch:b"},
                 "target": {"nodeId": "out_sql", "portId": "result"}},
            ],
        }
        parent = {
            "version": 1,
            "name": "parent",
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}},
                {"id": "mount1", "type": "workflow.subgraph", "data": {"workflow": "child"}},
                {"id": "out1", "type": "output.formatted", "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"},
                 "target": {"nodeId": "mount1", "portId": "text"}},
                {"source": {"nodeId": "mount1", "portId": "result"},
                 "target": {"nodeId": "out1", "portId": "result"}},
            ],
        }
        runtime = NodeRuntime(
            services=RuntimeServices(model=None, document_loader=lambda _slug: child)
        )
        build = runtime.factory(parent)
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        plan = WorkflowCompiler().plan(parent)
        build("mount1", parent["nodes"][1], plan)

        assert {"in_sql", "router_sql"} <= runtime.machinery_nodes
        assert "out_sql" not in runtime.machinery_nodes
