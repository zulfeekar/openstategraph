"""`POST /api/workflows/validate` — the check the editor could not run.

Validation existed only as an MCP tool, so the two clients were not equal: an
LLM client got its document checked before every run and the editor could not
check one at all. That is what let an unregistered node type reach a run and
answer with the user's own question, and the test that pinned the endpoint's
*absence* is deleted with this.

**One validator, three callers.** `mcp_server._validate` carried a comment
saying "No second validator lives here"; that rule now has to hold across a
second transport, so the helper moved to `openstategraph.validation` and both
doors import it. A hand-written HTTP copy would be the same defect the provider
catalogue was built to end.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app

VALID = {
    "version": 2,
    "name": "valid",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "hi"}},
        {"id": "out1", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    ],
}


def _bogus() -> dict:
    document = json.loads(json.dumps(VALID))
    document["nodes"].insert(
        1, {"id": "a1", "type": "totally.bogus", "position": {"x": 100, "y": 0}, "data": {}}
    )
    return document


def _post(document: dict) -> dict:
    response = TestClient(create_app()).post(
        "/api/workflows/validate", json={"workflow": document}
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestItAnswers:
    def test_a_good_document_is_valid_with_no_findings(self) -> None:
        body = _post(VALID)
        assert body["valid"] is True
        assert body["findings"] == []

    def test_an_unknown_node_type_is_a_finding(self) -> None:
        """The case that motivated the endpoint."""
        body = _post(_bogus())
        assert body["valid"] is False
        assert any("totally.bogus" in finding for finding in body["findings"])

    def test_a_finding_names_the_node_not_just_the_type(self) -> None:
        assert any("a1" in finding for finding in _post(_bogus())["findings"])

    def test_findings_are_a_list_of_lines_not_one_blob(self) -> None:
        """The editor renders them; a single string would make it parse."""
        findings = _post(_bogus())["findings"]
        assert isinstance(findings, list)
        assert all(isinstance(finding, str) and "\n" not in finding for finding in findings)


class TestItIsCheapAndSafe:
    def test_it_needs_no_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A developer validates long before they have a key configured."""
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(name, raising=False)
        assert _post(VALID)["valid"] is True

    def test_it_calls_no_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Planning is a compile-check; reaching a provider would be a bug.

        `ValidateWorkflowTool` plans the graph in memory and throws it away.
        """
        import openstategraph.chat_model as chat_model_module

        def explode(_name: str) -> None:
            raise AssertionError("validation must not build a model")

        monkeypatch.setattr(chat_model_module, "build_chat_model", explode)
        assert _post(VALID)["valid"] is True

    def test_a_malformed_document_is_a_finding_not_a_500(self) -> None:
        body = _post({"nodes": "not a list"})
        assert body["valid"] is False
        assert body["findings"]

    def test_an_empty_document_is_a_finding_not_a_500(self) -> None:
        body = _post({})
        assert body["valid"] is False
        assert body["findings"]

    def test_unknown_fields_are_rejected(self) -> None:
        """`extra="forbid"`, like every other request model here."""
        response = TestClient(create_app()).post(
            "/api/workflows/validate", json={"workflow": VALID, "surprise": 1}
        )
        assert response.status_code == 422


class TestOneValidatorNotTwo:
    def test_both_doors_give_the_same_verdict(self) -> None:
        """The rule `mcp_server._validate` stated, now across two transports."""
        from openstategraph.validation import validate_document

        for document in (VALID, _bogus()):
            valid, findings = validate_document(document)
            body = _post(document)
            assert body["valid"] is valid
            assert body["findings"] == findings

    def test_the_mcp_door_uses_the_same_helper(self) -> None:
        """Not a copy that happens to agree today."""
        import inspect

        from openstategraph import mcp_server

        source = inspect.getsource(mcp_server)
        assert "from openstategraph.validation import" in source or (
            "validation.validate_document" in source
        )
