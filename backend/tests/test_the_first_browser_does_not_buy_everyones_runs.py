"""A browser's key may configure a laptop. It may not configure a team's server.

`apply_credentials` writes an accepted credential into `os.environ` under the
rule *absent → fill; present → leave alone*, and its docstring argues that rule
is safe because a client's value can only ever lose to the operator's.

**It stops the second client and not the first.** On a deployment where the
operator configured no provider key — which is the entire reason the
credentials dialog exists — the first request to arrive fills `os.environ` and
*becomes* the configuration. Nothing pops it and the process outlives the
request, so from then on "present → leave alone" protects **that browser's
key** from every other caller until restart.

`api/auth.py` names the deployment where that is a boundary crossing rather
than a convenience: *"an MCP server or `openstategraph serve` on a laptop or a
team VM"*. Four teammates, one VM, A opens the editor first — every teammate's
prompts and every customer's question then go to A's vendor account, under A's
logging and A's organisation's data-processing agreement, and nobody is told.

So the accepted set is unchanged and the *deployment* is now the question:
a request credential is taken only from a caller on this machine, on a server
with no shared token and no proxy in front of it. Everywhere else it is
dropped, and the operator's own environment is the only thing that configures
a provider.

Every credential value in this file is fake and asserted absent from the
places a value must never reach; the **names** are what is allowed to appear.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app

#: Obviously fake, and asserted absent from every environment, log and body
#: below. Two of them, because the whole finding is about telling two callers
#: apart.
FIRST_BROWSER_KEY = "fake-key-belonging-to-teammate-a-not-a-real-secret"
SECOND_BROWSER_KEY = "fake-key-belonging-to-teammate-b-not-a-real-secret"

KEY_NAME = "ANTHROPIC_API_KEY"

DOCUMENT: dict[str, Any] = {
    "version": 1,
    "name": "x",
    "nodes": [{"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}}],
    "edges": [],
}


@pytest.fixture(autouse=True)
def unannounced() -> Iterator[None]:
    """The announcement is once per *process*, and the suite is one process.

    Right for a server — a busy one would otherwise repeat itself every run —
    and wrong for a file whose subject is what gets said out loud, so each test
    starts from a process that has said nothing.
    """
    from openstategraph.api import model_resolution

    model_resolution._ANNOUNCED.clear()
    yield
    model_resolution._ANNOUNCED.clear()


@pytest.fixture(autouse=True)
def no_provider_key() -> Iterator[None]:
    """The deployment this ticket is about: the operator configured nothing.

    Restored by hand rather than by `monkeypatch.delenv`, because the defect
    under test is a *write* into the real `os.environ` — a fake key leaking out
    of this module into the rest of the suite is exactly the failure mode the
    file is about.
    """
    saved = {name: os.environ[name] for name in (KEY_NAME,) if name in os.environ}
    os.environ.pop(KEY_NAME, None)
    try:
        yield
    finally:
        os.environ.pop(KEY_NAME, None)
        os.environ.update(saved)


def run(client: TestClient, key: str, **kwargs: Any) -> Any:
    return client.post(
        "/api/runs",
        json={
            "workflow": DOCUMENT,
            "question": "hi",
            "credentials": {KEY_NAME: key},
        },
        **kwargs,
    )


def a_team_vm(tmp_path: Any) -> TestClient:
    """A server with a shared token — the deployment `auth.py` names."""
    return TestClient(
        create_app(workflows_root=tmp_path),
        headers={"Authorization": "Bearer the-teams-token"},
    )


def a_laptop(tmp_path: Any) -> TestClient:
    """One person, on loopback, with no gate — where the dialog is the point."""
    return TestClient(create_app(workflows_root=tmp_path), client=("127.0.0.1", 51234))


class TestTheSharedDeployment:
    def test_a_first_caller_does_not_become_the_configuration(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_API_TOKEN", "the-teams-token")
        client = a_team_vm(tmp_path)

        run(client, FIRST_BROWSER_KEY)

        assert os.environ.get(KEY_NAME) is None

    def test_the_second_caller_is_not_billed_to_the_first(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_API_TOKEN", "the-teams-token")
        client = a_team_vm(tmp_path)

        run(client, FIRST_BROWSER_KEY)
        run(client, SECOND_BROWSER_KEY)

        # B's run authenticated as nobody, which is the correct answer on a
        # server whose operator configured no provider: the run fails with the
        # message that names the variable to set. It did not authenticate as A.
        assert FIRST_BROWSER_KEY not in os.environ.values()

    def test_a_proxied_request_is_shared_even_with_no_token(self, tmp_path: Any) -> None:
        from openstategraph.principal import PROXY_ASSERTION_HEADER

        client = TestClient(
            create_app(workflows_root=tmp_path),
            client=("127.0.0.1", 51234),
            headers={PROXY_ASSERTION_HEADER: "1"},
        )

        run(client, FIRST_BROWSER_KEY)

        assert os.environ.get(KEY_NAME) is None

    def test_a_caller_from_another_machine_is_shared(self, tmp_path: Any) -> None:
        client = TestClient(create_app(workflows_root=tmp_path), client=("10.0.0.7", 51234))

        run(client, FIRST_BROWSER_KEY)

        assert os.environ.get(KEY_NAME) is None

    def test_the_drop_is_said_out_loud_and_says_no_value(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_API_TOKEN", "the-teams-token")
        client = a_team_vm(tmp_path)

        with caplog.at_level(logging.WARNING):
            run(client, FIRST_BROWSER_KEY)

        said = caplog.text
        assert KEY_NAME in said
        assert FIRST_BROWSER_KEY not in said


class TestTheSingleUserLaptop:
    def test_a_pasted_key_still_works(self, tmp_path: Any) -> None:
        run(a_laptop(tmp_path), FIRST_BROWSER_KEY)

        assert os.environ.get(KEY_NAME) == FIRST_BROWSER_KEY

    def test_and_it_says_the_process_now_carries_it(
        self, tmp_path: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            run(a_laptop(tmp_path), FIRST_BROWSER_KEY)

        said = caplog.text
        assert KEY_NAME in said
        assert FIRST_BROWSER_KEY not in said


class TestTheKnowledgeBuildPath:
    """Not a run, and the same door. `knowledge_build` calls the same function."""

    def test_a_shared_deployment_refuses_there_too(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_API_TOKEN", "the-teams-token")
        client = a_team_vm(tmp_path)
        client.post("/api/workflows", json={"name": "kb", "document": DOCUMENT})

        client.post(
            "/api/workflows/kb/knowledge/build",
            json={"credentials": {KEY_NAME: FIRST_BROWSER_KEY}},
        )

        assert os.environ.get(KEY_NAME) is None
