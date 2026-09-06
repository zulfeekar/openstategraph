"""launch-readiness/16, providers-and-credentials/15 — the chat turns the
best error message into a 500.

Measured twice on 2026-08-23: once on a fresh wheel install with no provider
configured (providers-and-credentials 14's measurement, editor), and once by
a stranger on the published `0.3.0rc2` (`/chat`, launch-readiness 12). Both
traced the same route in the browser to the same cause:

    POST /api/runs/stream -> 500 Internal Server Error

    File ".../api/routes/runs.py", line 409, in run_workflow_stream
        resolve_model(request.model or workflow_default_model(document))
    openstategraph.errors.NoProviderInstalled: no model provider integration
    is installed, so every run will fail — pip install 'openstategraph[anthropic]', ...

`resolve_model` raises before any `try` in `run_workflow`, `run_workflow_stream`
and `resume_workflow_stream` reaches it, so FastAPI's default handler turned an
exception carrying the exact sentence `openstategraph serve` and
`openstategraph providers` already print into a bare, bodyless 500.

One defect, two tickets: 15 found it in the editor, 16 found it again in
`/chat` on the published rc and confirmed the customer surface says something
*worse* than the editor's toast (`"Runtime error (500)"` names HTTP, not the
product). Both close with this fix.

These tests run all three routes with every provider credential unset, so
`resolve_model` is guaranteed to reach `NoProviderInstalled` — see
`test_run_readiness_is_one_sentence.py` for the same pattern.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.providers import ProviderSpec, provider_catalogue, reset_provider_catalogue

# `osg-agent-experience/79`: the remedy is composed for the installation it is
# printed on — `uv tool install --force` repairs a tool install, and a
# pre-release carries index flags — so every assertion below reaches it through
# `install_hint` rather than transcribing it. A literal here would pin one
# machine's answer and be wrong on every other; the command itself is asserted
# where it is composed, `test_the_install_hint_can_be_carried_out.py`.
from openstategraph.install_hint import install_hint

CREDENTIALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")

MINIMAL_DOCUMENT = {
    "version": 2,
    "name": "no-provider-test",
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

#: This checkout has every LangChain integration package installed — the
#: no-key case, not the no-integration case `NoProviderInstalled` guards.
#: `test_run_readiness_is_one_sentence.py` hits the real zero-provider state
#: the same way: register one provider whose integration module cannot
#: import, and nothing else — `provider_catalogue().elected_default()` then
#: has no candidate at all, which is the state a bare `pip install
#: openstategraph` (or the published rc a stranger installed) actually leaves.
GHOST = ProviderSpec(
    name="ghost",
    default_model="spook-1",
    extra="ghost",
    integration_module="langchain_ghost_which_is_not_installed",
)


@pytest.fixture(autouse=True)
def _no_provider_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OPENSTATEGRAPH_OLLAMA_MODEL", raising=False)
    monkeypatch.setattr("openstategraph.providers.builtin_specs", lambda: (GHOST,))
    reset_provider_catalogue()
    yield
    reset_provider_catalogue()


def _client() -> TestClient:
    return TestClient(create_app())


def _expected_sentence() -> str:
    """The one shared sentence — `ProviderCatalogue.elected_default().reason`,
    the same object `GET /api/providers`'s `run_readiness` publishes."""
    return provider_catalogue().elected_default().reason


def _run_body() -> dict[str, Any]:
    return {"workflow": MINIMAL_DOCUMENT, "question": "how many customers?"}


class TestRunNeverAnswers500:
    def test_run_workflow_is_a_legible_4xx_not_a_bare_500(self) -> None:
        response = _client().post("/api/runs", json=_run_body())
        assert response.status_code == 503, response.text
        assert response.json()["detail"] == _expected_sentence()

    def test_run_workflow_stream_is_a_legible_4xx_not_a_bare_500(self) -> None:
        response = _client().post("/api/runs/stream", json=_run_body())
        assert response.status_code == 503, response.text
        assert response.json()["detail"] == _expected_sentence()

    def test_resume_workflow_stream_is_a_legible_4xx_not_a_bare_500(self) -> None:
        response = _client().post(
            "/api/runs/resume",
            json={
                "thread_id": "no-such-thread",
                "workflow": MINIMAL_DOCUMENT,
                "decision": "approve",
            },
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"] == _expected_sentence()


class TestTheSentenceIsTheOneEverySurfaceAlreadyPrints:
    def test_it_names_the_pip_install_line(self) -> None:
        response = _client().post("/api/runs", json=_run_body())
        assert install_hint("ghost") in response.json()["detail"]

    def test_it_is_not_a_second_copy(self) -> None:
        """Not a new sentence written for this route — the exact string
        `resolve_model` raised, which is `elected_default().reason`."""
        from openstategraph.errors import NoProviderInstalled

        response = _client().post("/api/runs", json=_run_body())
        assert response.json()["detail"] == str(NoProviderInstalled(_expected_sentence()))


class TestBothAudiencesSeeTheSameSentence:
    """`api/audience.py` splits *content the graph produced* — capability
    suggestions, node-naming diagnostics — because a customer cannot act on
    those. This fires before the graph is built and names no node, no
    document and nothing the customer path should hide; the customer default
    (`OpenStateGraphError.customer_message()`'s "Try again") would be actively
    wrong here, since retrying can never fix a missing provider. So both
    audiences get the operator-actionable sentence, not a generic one."""

    def test_customer_audience_gets_the_same_sentence_as_developer(self) -> None:
        developer = _client().post(
            "/api/runs", json={**_run_body(), "audience": "developer"}
        )
        customer = _client().post(
            "/api/runs", json={**_run_body(), "audience": "customer"}
        )
        assert developer.json()["detail"] == customer.json()["detail"] == _expected_sentence()


class TestChatRendersTheSentenceNotTheStatusLine:
    """`/chat`'s own `stream()` used to render a non-ok response as
    `Runtime error (${resp.status}): ${await resp.text()}` — which, for a
    FastAPI `HTTPException`, is `Runtime error (503): {"detail": "no model
    provider integration is installed, ..."}`. That is worse than the editor's
    toast, launch-readiness 16 found: it names HTTP rather than the product,
    and buries the one sentence in a JSON blob a customer will not parse.

    Source assertions, for the reason `test_the_chat_page_says_what_it_does.py`
    records: `chat.html` is a dependency-free page with no JS test harness in
    this repository, and the alternative to pinning it here is pinning it
    nowhere.
    """

    def test_a_non_ok_response_is_parsed_for_its_detail(self) -> None:
        from openstategraph.api.chat_page import chat_page_html

        page = chat_page_html()
        assert "JSON.parse(raw)" in page
        assert "parsed.detail" in page

    def test_the_status_line_wrapper_is_gone(self) -> None:
        """The literal bug report's own text — `Runtime error (500): Internal
        Server Error` — must not be constructible any more: no more
        unconditional `Runtime error (${resp.status})` prefix on a parsed
        `.detail`."""
        from openstategraph.api.chat_page import chat_page_html

        page = chat_page_html()
        assert "Runtime error (${resp.status})" not in page
