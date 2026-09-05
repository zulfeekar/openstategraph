"""A refusal for want of a credential says what to do instead.

`docs-onramp/09`. On a fresh install, the whole of it:

    $ openstategraph run workflows/starter "hello"
    error: the only provider integration installed; set OLLAMA_API_KEY or
    OLLAMA_HOST to use it

True, short, and the point at which install-to-first-answer stops. Two commands
would have finished the job and neither was named: `openstategraph providers`
prints every provider, the variable each reads and whether it is set;
`openstategraph env-example` prints the block to paste. Both excellent, neither
discoverable at the moment of failure.

This repository already has the rule, in `docs/declaring-a-next-step.md`: *"a
model told to change its approach, with no destination in the message, has the
same wrong moves available to it — so it makes them again."* It was written for
somebody else's MCP server. Its own CLI did not obey it.

## One sentence, three doors

The next step is composed in `model_readiness.unmet_model_requirement` — the
function `providers-and-credentials/14` already made the single owner of this
wording after the CLI and the editor's banner were caught disagreeing. So the
CLI's `error:` line, the HTTP 503 body and the MCP `error`/`findings` pair all
carry it, and three spellings of one sentence remain impossible.

**What deliberately does not gain it:** `elected_default().reason` itself, which
is what `openstategraph providers` prints as its own header and what
`GET /api/providers` publishes as `run_readiness`. Telling a reader of
`providers` to run `providers` is the noise this rule warns about, and the
editor's banner has its own *Show me where* button rather than a sentence.

## The exit code does not move

A next step is not a status change. `docs/cli.md` promises exit 1 for a run that
cannot start, and the refusal is still that.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.model_readiness import unmet_model_requirement
from openstategraph.providers import provider_catalogue, reset_provider_catalogue

CREDENTIALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")

AGENT_DOCUMENT: dict[str, Any] = {
    "version": 1,
    "name": "one-agent",
    "nodes": [
        {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
        {"id": "agent1", "type": "agent.llm", "data": {}, "position": {"x": 0, "y": 0}},
        {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 0, "y": 0}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "agent1", "portId": "prompt"},
        },
        {
            "source": {"nodeId": "agent1", "portId": "result"},
            "target": {"nodeId": "out1", "portId": "result"},
        },
    ],
}


@pytest.fixture
def no_credential(monkeypatch: pytest.MonkeyPatch):
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    reset_provider_catalogue()
    yield
    reset_provider_catalogue()


def _assert_declares_a_next_step(text: str) -> None:
    """The shape `docs/declaring-a-next-step.md` prescribes: a destination.

    Named commands and the file to put the value in — not "configure a
    provider", which leaves every wrong move available.
    """
    assert "openstategraph providers" in text, text
    assert "openstategraph env-example" in text, text
    assert ".env" in text, text


class TestTheSentenceItself:
    def test_the_refusal_carries_the_readiness_sentence_and_a_next_step(
        self, no_credential: None
    ) -> None:
        refusal = unmet_model_requirement(no_model=True)
        assert refusal is not None
        assert provider_catalogue().elected_default().reason in refusal
        _assert_declares_a_next_step(refusal)

    def test_a_run_that_can_proceed_is_told_nothing(self, no_credential: None) -> None:
        assert unmet_model_requirement(no_model=False) is None

    def test_the_providers_header_does_not_tell_you_to_run_providers(
        self, no_credential: None
    ) -> None:
        """The single-owner rule cuts both ways: the reason stays a reason.

        `openstategraph providers` and `GET /api/providers`' `run_readiness`
        publish `elected_default().reason` directly. A next step composed into
        *that* would route a reader of the providers table back to the
        providers table.
        """
        assert "openstategraph providers" not in provider_catalogue().elected_default().reason


class TestTheCliDoor:
    def test_run_names_the_next_step_and_still_exits_one(
        self, no_credential: None, monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
    ) -> None:
        from openstategraph import cli
        from openstategraph.loader import CompiledWorkflow

        package = tmp_path / "one-agent"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps(AGENT_DOCUMENT))

        def never(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("a node ran — the door was supposed to refuse")

        monkeypatch.setattr(CompiledWorkflow, "ask", never)

        code = cli.main(["run", str(package), "hi"])

        assert code == 1
        _assert_declares_a_next_step(capsys.readouterr().err)


class TestTheHttpDoor:
    def test_the_503_body_names_the_next_step(
        self, no_credential: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import openstategraph.api.routes.runs as runs_route

        def never(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("a node ran — the door was supposed to refuse")

        monkeypatch.setattr(runs_route, "invoke_run", never)

        response = TestClient(create_app()).post(
            "/api/runs", json={"workflow": AGENT_DOCUMENT, "question": "hi"}
        )

        assert response.status_code == 503, response.text
        _assert_declares_a_next_step(response.json()["detail"])
