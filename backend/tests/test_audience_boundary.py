"""Developer guidance cannot reach a customer — proved over the real endpoint.

The rule is the owner's: *"the suggestion of tool or methods should only be
visible to workflow edit users, not customer facing"*, enforced **at the
runtime seam** rather than left a frontend convention.

Before `api/audience.py` the convention was all there was, and the raw payload
said so. `chinook-assistant`, asked through the customer surface's own request
shape with one boolean added, answered:

    event: done
    data: {"answer": "... I'm unable to generate a chart ... \\n\\n
           ```suggestion\\n{\\"nodeType\\": \\"tool.email-send\\",
           \\"attachTo\\": \\"agent-web\\", ...}\\n```", "warnings": [], ...}

The developer-only text was in `answer` — the one field every customer surface
renders — and `advisor` was an ungated field on the very endpoint `/chat`
posts to.

So these tests are deliberately **not** unit tests on a parser. Each drives
`create_app()` over `POST /api/runs/stream` with the exact body
`api/static/chat.html` sends, and asserts against the raw SSE bytes. A parser
test would have passed happily throughout the period the boundary did not
exist.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.audience import (
    AUDIENCE_ENV,
    Audience,
    DeveloperChannel,
    resolve,
    split_suggestion,
)
from openstategraph.developer_channel import ProseGuard
from openstategraph.api.main import create_app
from openstategraph.api.schemas import ResumeRequest, RunRequest

#: A suggestion fence exactly as `advisor_context` asks an agent to emit one.
FENCE = (
    "```suggestion\n"
    '{"nodeType": "tool.email-send", "attachTo": "agent-web", "port": "tools",'
    ' "label": "Email", "reason": "no email capability"}\n'
    "```"
)


def _node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _echo_doc() -> dict[str, Any]:
    """Input straight to output — the question comes back as the answer.

    No model is involved, which is what makes this the sharpest possible test
    of the transport half: whatever a run puts in `answer` is exactly what the
    customer would read, with nothing in between to soften it.
    """
    return {
        "version": 1,
        "name": "echo",
        "nodes": [
            _node("node:input.text-1", "input.text"),
            _node("node:output.formatted-1", "output.formatted"),
        ],
        "edges": [_edge("node:input.text-1", "text", "node:output.formatted-1", "result")],
    }


def _broken_doc() -> dict[str, Any]:
    """Same shape with a function node nothing can bind — one runtime warning.

    `function.nowhere` is not in any registry, so `NodeRuntime` records it in
    `UNRESOLVED_FUNCTION` and `runtime_warnings()` turns it into a sentence
    naming the missing capability. Exactly the kind of authoring diagnostic
    `/chat` used to print to a customer in red.
    """
    return {
        "version": 1,
        "name": "broken",
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


def _chat_body(question: str, document: dict[str, Any]) -> dict[str, Any]:
    """The body `api/static/chat.html` posts, field for field.

    Copied from the page rather than minimised, because the claim being tested
    is about *that* request and not about a convenient subset of it.
    """
    return {
        "workflow": {"document": document},
        "question": question,
        "workflow_slug": None,
        "thread_id": "audience-test",
        "session_id": "s1",
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


class TestACustomerCannotReceiveDeveloperGuidance:
    """The ticket's bar, over the real `/chat` path."""

    def test_a_suggestion_fence_cannot_survive_into_a_customer_answer(self) -> None:
        """The question itself carries the fence, so the run's answer would
        contain one unless something removes it — which is also the injection
        case in its strongest form: content the *customer* supplied, arriving
        in the field the customer's client renders."""
        client = TestClient(create_app())
        response = client.post(
            "/api/runs/stream",
            json=_chat_body(f"how do I email this?\n\n{FENCE}", _echo_doc()),
        )

        assert response.status_code == 200
        # The whole stream, not only the parsed answer: `data:` lines carry
        # every frame this endpoint can emit, and a leak anywhere in the body
        # is a leak a customer can read in DevTools.
        assert "```suggestion" not in response.text
        assert "tool.email-send" not in response.text

        done = _done(response.text)
        assert "suggestion" not in done["answer"]
        assert done["answer"].startswith("how do I email this?")

    def test_a_customer_done_frame_carries_no_developer_channel_at_all(self) -> None:
        client = TestClient(create_app())
        response = client.post("/api/runs/stream", json=_chat_body("hello", _echo_doc()))

        done = _done(response.text)
        # Absent, not empty: a client must not be able to read "there were no
        # findings" out of a frame that was never entitled to carry any.
        assert "developer" not in done
        assert "warnings" not in done

    def test_authoring_warnings_do_not_reach_a_customer(self) -> None:
        """`/chat` used to print these to the customer in red — sentences like
        *"No function found for function.nowhere — the step passed its input
        through unchanged"*, which nobody outside the editor can act on.

        Asserted on the **sentence**, not on the node type: `node:function.
        nowhere-1` is the document's own topology and rides every `update`
        frame, exactly as it rides the `mermaid` the customer's flow diagram
        is drawn from. That is deliberate (see the table in `api/audience.py`)
        — the diagnostic is the developer-only part, not the node id.
        """
        client = TestClient(create_app())
        response = client.post("/api/runs/stream", json=_chat_body("hi", _broken_doc()))

        assert "No function found for" not in response.text
        assert "developer" not in _done(response.text)

    def test_the_customer_still_gets_the_answer_and_the_run(self) -> None:
        """The boundary must not be bought by making `/chat` useless — the
        page draws its flow diagram from `mermaid` and its trace from the
        per-node fields."""
        client = TestClient(create_app())
        done = _done(
            client.post("/api/runs/stream", json=_chat_body("hello", _echo_doc())).text
        )

        assert done["answer"] == "hello"
        assert "node_input_text_1" in done["mermaid"]
        assert "node:input.text-1" in done["outputs"]


class TestADeveloperGetsItOnTheChannelInstead:
    def test_the_suggestion_arrives_structured_and_never_in_the_prose(self) -> None:
        client = TestClient(create_app())
        body = _chat_body(f"how do I email this?\n\n{FENCE}", _echo_doc())
        body["audience"] = "developer"
        response = client.post("/api/runs/stream", json=body)

        done = _done(response.text)
        # Same rule as for a customer — the fence leaves the prose on *every*
        # run. What a developer gets extra is the parsed object beside it.
        assert "```suggestion" not in done["answer"]
        assert done["developer"]["suggestion"]["nodeType"] == "tool.email-send"
        assert done["developer"]["suggestion"]["attachTo"] == "agent-web"

    def test_authoring_warnings_arrive_on_the_channel(self) -> None:
        client = TestClient(create_app())
        body = _chat_body("hi", _broken_doc())
        body["audience"] = "developer"
        done = _done(client.post("/api/runs/stream", json=body).text)

        assert any("function.nowhere" in w for w in done["developer"]["warnings"])

    def test_a_developer_channel_is_present_even_with_nothing_to_report(self) -> None:
        """So a developer client never has to tell "no findings" apart from
        "an older backend that does not send this"."""
        client = TestClient(create_app())
        body = _chat_body("hello", _echo_doc())
        body["audience"] = "developer"
        done = _done(client.post("/api/runs/stream", json=body).text)

        assert done["developer"] == {"warnings": [], "suggestion": None, "redactions": []}


class TestTheBlockingEndpointIsNotTheWayAround:
    """`/api/runs` shares the seam, or it is simply a second door."""

    def test_a_customer_run_returns_no_developer_channel(self) -> None:
        client = TestClient(create_app())
        body = client.post(
            "/api/runs", json={"workflow": _broken_doc(), "question": f"hi {FENCE}"}
        ).json()

        assert body["developer"] is None
        assert "```suggestion" not in body["answer"]

    def test_a_developer_run_returns_one(self) -> None:
        client = TestClient(create_app())
        body = client.post(
            "/api/runs",
            json={
                "workflow": _broken_doc(),
                "question": f"hi {FENCE}",
                "audience": "developer",
            },
        ).json()

        assert any("function.nowhere" in w for w in body["developer"]["warnings"])
        assert body["developer"]["suggestion"]["nodeType"] == "tool.email-send"

    def test_the_per_node_outputs_map_is_cleaned_too(self) -> None:
        """`answer` was split here; `outputs` was not — found under ticket 15.

        Every surface renders `outputs` per node (the editor's sidebar,
        `/chat`'s trace), so a fence surviving there is the same leak one field
        along. Reproduced live before it was fixed, on `chinook-assistant` over
        this endpoint: `answer` came back clean while `outputs["agent-sql"]`,
        `outputs["grader-sql"]` and `outputs["out1"]` each carried the whole
        fence to a `customer` run.
        """
        client = TestClient(create_app())
        body = client.post(
            "/api/runs", json={"workflow": _echo_doc(), "question": f"hi {FENCE}"}
        ).json()

        assert "```suggestion" not in body["answer"]
        assert body["outputs"], "the echo document produces per-node outputs"
        for node_id, text in body["outputs"].items():
            assert "```suggestion" not in text, f"fence survived in outputs[{node_id}]"

    def test_both_endpoints_expose_the_same_absence(self) -> None:
        """Parity, not two independent assertions.

        The streaming endpoint held this from the start and the blocking one
        did not, which is precisely the shape of defect a per-endpoint test
        cannot see: each door was tested against its own idea of the rule.
        """
        client = TestClient(create_app())
        blocking = client.post(
            "/api/runs", json={"workflow": _echo_doc(), "question": f"hi {FENCE}"}
        ).json()
        streamed = _done(
            client.post("/api/runs/stream", json=_chat_body(f"hi {FENCE}", _echo_doc())).text
        )

        assert set(blocking["outputs"]) == set(streamed["outputs"])
        assert blocking["outputs"] == streamed["outputs"]


class TestTheAudienceRoundTripsOnBothSchemas:
    """Both models forbid extras, so a field the editor sets on a run and not
    on the resume is a 422 on every approval."""

    def test_a_run_request_defaults_to_customer(self) -> None:
        assert RunRequest(workflow={}, question="q").audience == "customer"

    def test_a_resume_request_defaults_to_customer(self) -> None:
        request = ResumeRequest(thread_id="t", workflow={}, decision="approve")
        assert request.audience == "customer"

    def test_both_accept_developer(self) -> None:
        assert RunRequest(workflow={}, question="q", audience="developer").audience == (
            "developer"
        )
        assert ResumeRequest(
            thread_id="t", workflow={}, decision="approve", audience="developer"
        ).audience == "developer"

    def test_an_unknown_audience_is_refused_rather_than_coerced(self) -> None:
        """A typo must not quietly become one of the two real values — which
        one it became would be a security decision made by a typo."""
        with pytest.raises(Exception):
            RunRequest(workflow={}, question="q", audience="admin")


class TestTheDeploymentCeiling:
    def test_a_customer_only_deployment_refuses_to_raise_a_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(AUDIENCE_ENV, "customer")
        client = TestClient(create_app())
        body = _chat_body("hello", _echo_doc())
        body["audience"] = "developer"

        assert "developer" not in _done(client.post("/api/runs/stream", json=body).text)

    def test_an_unrecognised_value_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The only reason to set this variable is to restrict, so a typo caps
        rather than passes."""
        monkeypatch.setenv(AUDIENCE_ENV, "develper")
        assert resolve("developer") is Audience.CUSTOMER

    def test_unset_leaves_the_request_in_charge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(AUDIENCE_ENV, raising=False)
        assert resolve("developer") is Audience.DEVELOPER
        assert resolve(None) is Audience.CUSTOMER


class TestTheSplitItself:
    """The unit level, kept because the endpoint tests cannot reach every
    shape a model can emit — not *instead of* them."""

    def test_prose_without_a_fence_is_returned_unchanged(self) -> None:
        assert split_suggestion("Rock earned the most.") == (
            "Rock earned the most.",
            None,
        )

    def test_the_first_fence_wins(self) -> None:
        second = FENCE.replace("tool.email-send", "tool.web-search")
        prose, suggestion = split_suggestion(f"a\n\n{FENCE}\n\n{second}")
        assert suggestion is not None
        assert suggestion["nodeType"] == "tool.email-send"
        # The loser stays out of the developer channel but is still visible to
        # the developer as prose — a model that ignored "emit exactly one" is
        # something the developer should be able to see it did.
        assert "tool.web-search" in prose

    def test_an_unparseable_fence_is_still_stripped(self) -> None:
        """A half-written fence is machine-facing scaffolding either way, and
        showing it to a customer is the thing this exists to prevent."""
        prose, suggestion = split_suggestion("sorry\n\n```suggestion\n{not json\n```")
        assert suggestion is None
        assert "```suggestion" not in prose and "not json" not in prose

    def test_a_non_object_body_yields_no_suggestion(self) -> None:
        assert split_suggestion("x\n```suggestion\n[]\n```")[1] is None


class TestAFenceOnlyReplyStillSaysSomething:
    """Ticket 22, live on `chinook-assistant` with `audience: "developer"`.

    A blocked agent was asked to *"say so briefly, then emit exactly one fenced
    block"* and emitted only the block. The run succeeded, the grader passed
    it, the suggestion was well-formed and correct — and `answer` was `""`.

    The emptiness is *created here*: `_output` guarantees a non-empty answer
    and this split then deletes the only text there was. So the floor belongs
    beside the deletion, exactly as `_output`'s floor sits beside the place the
    run's answer is defined. Two changes, not one: `advisor_context` also now
    states that the sentence is required (which makes it rare), and this makes
    it impossible — an empty `answer` on a 200 is a broken contract for every
    client, and no prompt makes a model obey without exception.
    """

    def test_a_fence_that_was_the_whole_reply_leaves_a_sentence_behind(self) -> None:
        prose, suggestion = split_suggestion(FENCE)

        assert prose.strip(), "the split must never be what empties an answer"
        assert suggestion is not None
        assert "```" not in prose

    def test_the_sentence_does_not_leak_what_the_fence_carried(self) -> None:
        """It is delivered to customers too, so it may say that nothing could
        be answered — never which node type would have fixed it."""
        prose, _ = split_suggestion(FENCE)

        assert "tool.email-send" not in prose
        assert "agent-web" not in prose

    def test_a_reply_that_carried_prose_is_untouched_by_the_floor(self) -> None:
        prose, _ = split_suggestion(f"I cannot send email.\n\n{FENCE}")

        assert prose == "I cannot send email."

    def test_a_run_that_produces_a_suggestion_also_produces_prose(self) -> None:
        """The contract the ticket asked to be asserted, over the endpoint."""
        client = TestClient(create_app())
        body = client.post(
            "/api/runs",
            json={"workflow": _echo_doc(), "question": FENCE, "audience": "developer"},
        ).json()

        assert body["developer"]["suggestion"]["nodeType"] == "tool.email-send"
        assert body["answer"].strip(), "a 200 with an empty answer is a broken contract"

    def test_the_streaming_endpoint_says_the_same_thing(self) -> None:
        client = TestClient(create_app())
        done = _done(
            client.post("/api/runs/stream", json=_chat_body(FENCE, _echo_doc())).text
        )

        assert done["answer"].strip()
        assert "```suggestion" not in done["answer"]


class TestTheStreamingHalf:
    """`ProseGuard` exists because writing the endpoint test above found the
    leak the `done`-frame fix could not reach: `token` frames carry model text
    as it is produced, so a fence reaches a client character by character long
    before there is a settled answer to clean. `/chat` renders those tokens.
    """

    def test_a_fence_split_across_chunks_still_never_leaves(self) -> None:
        guard = ProseGuard()
        chunks = ["Sorry. ", "``", "`sugg", "estion\n{", '"nodeType": "x"}', "\n``", "`", " done"]
        assert "".join(guard.feed(c) for c in chunks) == "Sorry.  done"

    def test_a_backtick_run_that_is_not_a_fence_survives(self) -> None:
        """The guard must not eat ordinary code formatting — a model that
        answers with `SELECT 1` in backticks is doing its job."""
        guard = ProseGuard()
        assert guard.feed("run ```sql\nSELECT 1\n``` now") == "run ```sql\nSELECT 1\n``` now"

    def test_a_trailing_partial_marker_is_held_rather_than_sent(self) -> None:
        """The tail could still become a marker, so it waits for the next
        chunk instead of being emitted and regretted."""
        guard = ProseGuard()
        assert guard.feed("all done ``") == "all done "

    def test_text_with_no_backticks_passes_through_untouched(self) -> None:
        guard = ProseGuard()
        assert guard.feed("Rock earned the most.") == "Rock earned the most."


class TestTheChannelShape:
    def test_a_customer_payload_is_empty_rather_than_a_channel_of_nulls(self) -> None:
        channel = DeveloperChannel(warnings=["w"], suggestion={"nodeType": "t"})
        assert channel.payload(Audience.CUSTOMER) == {}

    def test_a_developer_payload_names_the_channel(self) -> None:
        channel = DeveloperChannel(warnings=["w"], suggestion=None)
        assert channel.payload(Audience.DEVELOPER) == {
            "developer": {"warnings": ["w"], "suggestion": None, "redactions": []}
        }


class TestNoMachineryNameReachesACustomer:
    """A customer's frames never carry the compiler's own identifiers.

    `/chat` rendered a trace reading `in1 (__turn_reset__)` — the turn-reset
    marker is an internal signal that a new turn began, and it arrived as if
    it were the name of a task the customer's question had spawned
    (reviews-2026-08-14 ticket 04).

    Fixed on the **server**, not in the page, because that is this module's own
    stated rule: a customer's frame carries no developer value "because no
    code path puts one there, not because the customer's client declines to
    look."
    """

    @staticmethod
    def _task_ids(audience: str) -> list[object]:
        from openstategraph.api.streaming import customer_task_id

        from openstategraph.api.audience import Audience

        for_audience = Audience.CUSTOMER if audience == "customer" else Audience.DEVELOPER
        return [
            customer_task_id("__turn_reset__", for_audience),
            customer_task_id("task-1", for_audience),
            customer_task_id(None, for_audience),
        ]

    def test_a_customer_never_sees_an_internal_marker(self) -> None:
        assert self._task_ids("customer") == [None, "task-1", None]

    def test_a_developer_still_sees_everything(self) -> None:
        # The marker is how a developer tells one turn from the next in a
        # thread; removing it from their trace would cost real information.
        assert self._task_ids("developer") == ["__turn_reset__", "task-1", None]
