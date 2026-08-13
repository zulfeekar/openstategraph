"""An unknown node type degrades *loudly* — the half that was missing.

`errors.py` states the policy and names this exact case:

    Findings that are *reported* rather than raised — an unknown node type, an
    unresolved tool — stay on `.warnings` and in validation output, because
    raising them would break the "degrade loud, never silent" rule that lets a
    workflow with one bad tool still answer the questions it can.

Both halves of that were true except the loud one. `NodeRuntime._passthrough`
forwarded the input unchanged and recorded nothing, and its docstring claimed
"the gap is visible as an unchanged value" — which is precisely what makes it
invisible. Asked "what is 2+2?", a document containing `totally.bogus`
answered "what is 2+2?", HTTP 200, `developer.warnings == []`.

Found by a typo rather than by a fuzzer: `agent.react` instead of `agent.llm`
behaves the same way, so a plausible near-miss produces a run that looks like
it worked.

The document is **not** refused, deliberately — see the policy above, and
`_passthrough`'s own reasoning that a workflow containing one node this build
does not know should still answer what it can. The MCP door does refuse, via
`ValidateWorkflowTool`; that is a different choice for a different client and
is asserted here too so the divergence is recorded rather than discovered.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app

BOGUS_TYPE = "totally.bogus"

DOCUMENT = {
    "version": 2,
    "name": "unknown-type",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "hi"}},
        {"id": "a1", "type": BOGUS_TYPE, "position": {"x": 200, "y": 0}, "data": {}},
        {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "a1", "portId": "prompt"},
        },
        {
            "source": {"nodeId": "a1", "portId": "result"},
            "target": {"nodeId": "out1", "portId": "result"},
        },
    ],
}


def _run(audience: str = "developer") -> dict:
    response = TestClient(create_app()).post(
        "/api/runs",
        json={"workflow": DOCUMENT, "question": "what is 2+2?", "audience": audience},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestItIsReported:
    def test_the_developer_channel_says_something(self) -> None:
        """The whole defect in one assertion. This was `[]`."""
        assert _run()["developer"]["warnings"], (
            "a document with an unknown node type ran to completion and "
            "reported nothing — the answer was the question, echoed back"
        )

    def test_it_names_the_type_and_the_node(self) -> None:
        text = " ".join(_run()["developer"]["warnings"])
        assert BOGUS_TYPE in text
        assert "a1" in text

    def test_it_says_the_step_was_skipped_not_that_it_worked(self) -> None:
        """The reader's actual question: is this answer trustworthy?"""
        text = " ".join(_run()["developer"]["warnings"]).lower()
        assert "unchanged" in text or "passed" in text or "skipped" in text

    def test_a_near_miss_type_is_reported_the_same_way(self) -> None:
        """`agent.react` is how this was found — the real type is `agent.llm`."""
        document = json.loads(json.dumps(DOCUMENT))
        document["nodes"][1]["type"] = "agent.react"
        body = TestClient(create_app()).post(
            "/api/runs",
            json={"workflow": document, "question": "what is 2+2?", "audience": "developer"},
        ).json()
        assert any("agent.react" in warning for warning in body["developer"]["warnings"])

    def test_the_streaming_door_reports_it_too(self) -> None:
        response = TestClient(create_app()).post(
            "/api/runs/stream",
            json={"workflow": DOCUMENT, "question": "what is 2+2?", "audience": "developer"},
        )
        assert BOGUS_TYPE in response.text


class TestItIsStillNotRefused:
    """"Degrade loud, never silent" — loud, but still a degrade."""

    def test_the_run_still_completes(self) -> None:
        assert _run()["answer"] is not None

    def test_a_known_document_reports_nothing(self) -> None:
        """No false positive on the types the runtime does implement."""
        document = json.loads(json.dumps(DOCUMENT))
        document["nodes"][1]["type"] = "function.format_report"
        body = TestClient(create_app()).post(
            "/api/runs",
            json={"workflow": document, "question": "hi", "audience": "developer"},
        ).json()
        assert not any(BOGUS_TYPE in w for w in body["developer"]["warnings"])
        assert not any("unknown node type" in w for w in body["developer"]["warnings"])

    def test_an_unresolved_function_is_reported_once_not_twice(self) -> None:
        """`_discovered_function` already reports, then delegates to passthrough.

        Both firing would tell a developer two things about one node, and the
        function-specific sentence is the more useful of the two.
        """
        document = json.loads(json.dumps(DOCUMENT))
        document["nodes"][1]["type"] = "function.no_such_function"
        body = TestClient(create_app()).post(
            "/api/runs",
            json={"workflow": document, "question": "hi", "audience": "developer"},
        ).json()
        mentions = [w for w in body["developer"]["warnings"] if "no_such_function" in w]
        assert len(mentions) == 1, mentions


class TestTheOtherDoorRefuses:
    """MCP validates first; HTTP does not. Recorded, not discovered."""

    def test_the_validator_calls_it_a_problem(self) -> None:
        from openstategraph.prebuilt_architect import ValidateWorkflowTool

        result = ValidateWorkflowTool().run(document=json.dumps(DOCUMENT))
        assert result.error is not None
        assert BOGUS_TYPE in result.error

    def test_there_is_still_no_http_validate_endpoint(self) -> None:
        """Why the run path has to carry this itself.

        If one is ever added, this test should be deleted along with the
        reason it exists.
        """
        paths = {getattr(route, "path", "") for route in create_app().routes}
        assert not any("validate" in path for path in paths)


@pytest.mark.parametrize("audience", ["customer", "developer"])
def test_the_answer_is_never_the_question_echoed_without_comment(audience: str) -> None:
    """The shape that makes this dangerous rather than merely untidy.

    A skipped node forwards its input, so the output node publishes the
    question as the answer. For a developer that is now accompanied by a
    warning; for a customer it is not, which is the audience boundary working
    as intended — but it means the developer channel is the only place this
    can be caught, so it has to be there.
    """
    body = _run(audience)
    if audience == "developer":
        assert body["developer"]["warnings"]
    else:
        assert body.get("developer") is None
