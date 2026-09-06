"""`route.check`'s fallback is a port, and an unwired one is a finding.

`osg-agent-experience/60`. The `check` field's help said a verdict naming no
branch "takes the fallback", and `route.check` has no `fallback` field — the
fields are `check`, `branches`, `maxRetries`, `timeoutSeconds`,
`cacheTtlSeconds`. The fallback is an out-**port**, wired like any other edge.
An agent reading that sentence beside `route.classifier`, which *does* have a
`fallback` field and is the node next to it in every document that uses this
one, writes `"fallback": "route"` into the data — caught, and it costs a round
trip.

The half that was not caught at all is the one that matters: a `route.check`
whose `fallback` port is unwired has nowhere to send an unrecognised verdict.
`_router_for` falls through to whichever destination happens to be first,
because a stall there would be a hang rather than an error, and the run ends
with no word about it. Nothing warned, because an unwired optional out-port is
ordinary everywhere else — and on this node type it is not: `fallback` is where
the check's *own* failure goes, since `call_check` renders a raised exception
as an empty answer.
"""

from __future__ import annotations

import json
from pathlib import Path

from openstategraph.document_checks import FindingClass, document_findings

SPECS = json.loads(
    (Path(__file__).resolve().parents[1] / "openstategraph" / "compile" / "port_specs.json")
    .read_text(encoding="utf-8")
)
ROUTE_CHECK = next(n for n in SPECS["node_types"] if n["type"] == "route.check")


def _hint(field_key: str) -> str:
    return str(
        next(f for f in ROUTE_CHECK["fields"] if f["key"] == field_key).get("hint") or ""
    )


class TestTheDocumentedFieldsAreTheDeclaredFields:
    def test_the_type_declares_no_fallback_field(self) -> None:
        assert "fallback" not in set(ROUTE_CHECK["field_keys"])

    def test_it_declares_a_fallback_port(self) -> None:
        assert any(
            port["id"] == "fallback" and port["direction"] == "out"
            for port in ROUTE_CHECK["ports"]
        )

    def test_the_help_calls_the_fallback_a_port(self) -> None:
        hint = _hint("check")
        assert "fallback" in hint
        # The word that separates the two readings. A reader who has just
        # configured `route.classifier` needs it in this sentence, not in a
        # different document.
        assert "port" in hint, hint

    def test_the_help_says_what_an_unwired_one_costs(self) -> None:
        assert "unwired" in _hint("check").lower(), _hint("check")


def _document(edges: list[dict]) -> dict:
    return {
        "nodes": [
            {
                "id": "fork1",
                "type": "route.check",
                "data": {"check": "needs_a_date_range", "branches": [{"id": "ask", "name": "ask"}]},
            },
            {"id": "out1", "type": "io.output", "data": {}},
        ],
        "edges": edges,
    }


BRANCH_EDGE = {
    "id": "e1",
    "source": {"nodeId": "fork1", "portId": "branch:ask"},
    "target": {"nodeId": "out1", "portId": "text"},
}
FALLBACK_EDGE = {
    "id": "e2",
    "source": {"nodeId": "fork1", "portId": "fallback"},
    "target": {"nodeId": "out1", "portId": "text"},
}


class TestAnUnwiredFallbackIsReported:
    def test_it_is_a_finding(self) -> None:
        findings = [
            f
            for f in document_findings(_document([BRANCH_EDGE]))
            if f.kind is FindingClass.UNWIRED_FALLBACK
        ]
        assert findings, "an unrecognised verdict with nowhere to go must not be silent"
        assert findings[0].subject == "fork1.fallback"

    def test_the_sentence_says_what_happens_to_such_a_verdict(self) -> None:
        message = next(
            f.message
            for f in document_findings(_document([BRANCH_EDGE]))
            if f.kind is FindingClass.UNWIRED_FALLBACK
        )
        assert "fork1" in message
        assert "fallback" in message

    def test_a_wired_fallback_is_not_a_finding(self) -> None:
        findings = [
            f
            for f in document_findings(_document([BRANCH_EDGE, FALLBACK_EDGE]))
            if f.kind is FindingClass.UNWIRED_FALLBACK
        ]
        assert findings == []

    def test_a_node_of_another_type_is_not_asked(self) -> None:
        document = {
            "nodes": [{"id": "grader1", "type": "route.grader", "data": {}}],
            "edges": [],
        }
        assert [
            f for f in document_findings(document) if f.kind is FindingClass.UNWIRED_FALLBACK
        ] == []
