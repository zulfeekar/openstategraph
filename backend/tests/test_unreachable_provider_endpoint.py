"""A configured Ollama host with nothing listening — providers-and-credentials 08.

Ticket 03's matrix has three credential shapes per provider: absent, wrong,
valid. There is a fourth, and it is Ollama's alone because Ollama is the one
provider whose address is a variable a developer sets: `OLLAMA_HOST` **set**,
pointing at a daemon that is not running.

Reproduced before anything was written, at both layers a developer meets:

    httpx.ConnectError: [Errno 61] Connection refused
    error: Node "agent1" failed and produced no result.
           ConnectError: [Errno 61] Connection refused

Neither names `OLLAMA_HOST`. Neither says the address was read and the
connection refused. `credential_error_from` explicitly returns `None` for an
`httpx.ConnectError` — correctly, since no credential was rejected — so the
failure fell through every translation this project owns and arrived verbatim.

These tests drive a **real run** against a port nothing is listening on. That
is deliberate rather than convenient: a helper returning the right sentence
proves nothing about whether a person ever reads it, and the last thing this
map's tests got wrong was being green at the wrong layer.

The host below is a loopback port in the ephemeral range, so this makes no
network call off the machine and takes milliseconds. It is not a credential
and could not be one — which is the property that makes this shape testable
here at all, where the other three are not.
"""

from __future__ import annotations

import socket

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app

CREDENTIALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")


def _closed_port() -> int:
    """A loopback port nothing is listening on, chosen by binding and closing.

    A hard-coded number is a flake waiting for the machine that happens to be
    using it; the ticket that filed this one was itself a misread port.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


DEAD_HOST = f"http://127.0.0.1:{_closed_port()}"

DOCUMENT = {
    "version": 2,
    "name": "unreachable-host",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "hi"}},
        {
            "id": "a1",
            "type": "agent.llm",
            "position": {"x": 200, "y": 0},
            # Named explicitly rather than elected: this test is about Ollama,
            # and the instance default is whatever this machine has installed.
            "data": {"rules": "Answer the question.", "model": "ollama/gpt-oss:120b-cloud"},
        },
        {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "a1", "portId": "prompt"}},
        {"source": {"nodeId": "a1", "portId": "result"}, "target": {"nodeId": "out1", "portId": "result"}},
    ],
}


@pytest.fixture()
def _host_that_is_not_listening(monkeypatch: pytest.MonkeyPatch) -> str:
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    # The whole shape: an address is configured, and no key is needed for a
    # daemon you run yourself — `is_configured` takes *any* of `env_vars`.
    monkeypatch.setenv("OLLAMA_HOST", DEAD_HOST)
    return DEAD_HOST


def _warnings(question: str = "what is 2+2?") -> list[str]:
    response = TestClient(create_app()).post(
        "/api/runs",
        json={"workflow": DOCUMENT, "question": question, "audience": "developer"},
    )
    assert response.status_code == 200, response.text
    return list(response.json()["developer"]["warnings"])


class TestTheDeveloperIsToldTheDaemonIsNotListening:
    def test_the_variable_they_actually_set_is_named(
        self, _host_that_is_not_listening: str
    ) -> None:
        """`OLLAMA_HOST` is the one thing the developer typed. It was absent.

        This is the ticket in one assertion, and the rule `CLAUDE.md` states
        for this provider: never reach a vendor without naming a variable
        someone can set, see and revoke.
        """
        text = " ".join(_warnings())
        assert "OLLAMA_HOST" in text, text

    def test_the_address_is_shown(self, _host_that_is_not_listening: str) -> None:
        """A developer with two hosts configured needs to know which one."""
        assert any(_host_that_is_not_listening in warning for warning in _warnings())

    def test_it_is_not_reported_as_a_missing_or_wrong_credential(
        self, _host_that_is_not_listening: str
    ) -> None:
        """The distinction the whole `CredentialError` family exists for.

        Absent, refused and unreachable need three different actions, and the
        previous behaviour gave this one none of the three.
        """
        text = " ".join(_warnings()).lower()
        assert "credential" not in text or "not a missing" in text or "rather than" in text
        assert "refused the credential" not in text

    def test_the_raw_transport_error_is_gone(self, _host_that_is_not_listening: str) -> None:
        """What a developer read before: `ConnectError: [Errno 61] …`."""
        text = " ".join(_warnings())
        assert "ConnectError" not in text
        assert "Errno" not in text

    def test_it_names_the_node_and_carries_no_traceback(
        self, _host_that_is_not_listening: str
    ) -> None:
        warnings = _warnings()
        assert any("a1" in warning for warning in warnings)
        text = " ".join(warnings)
        assert "Traceback" not in text
        assert ".py" not in text

    def test_a_customer_does_not_receive_it(self, _host_that_is_not_listening: str) -> None:
        response = TestClient(create_app()).post(
            "/api/runs",
            json={"workflow": DOCUMENT, "question": "hi", "audience": "customer"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body.get("developer") is None
        assert "OLLAMA_HOST" not in response.text

    def test_print_the_copy(
        self, _host_that_is_not_listening: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Not an assertion — copy is judged by reading it. `-s` to see it."""
        with capsys.disabled():
            for warning in _warnings():
                print("  warning  :", warning)


class TestTheTranslationIsNarrow:
    """Tolerant in reading, strict in trusting — and this is the strict half.

    A translator that answers "unreachable" for any exception with the word
    connection in it would re-label a genuinely missing key, which is the
    single most likely thing a developer hits.
    """

    def _connect_error(self, url: str) -> BaseException:
        import httpx

        return httpx.ConnectError(
            "[Errno 61] Connection refused", request=httpx.Request("POST", url)
        )

    def test_an_address_belonging_to_no_configured_provider_is_left_alone(
        self, _host_that_is_not_listening: str
    ) -> None:
        """A tool calling some unrelated service is not a provider problem."""
        from openstategraph.chat_model import unreachable_endpoint_error_from

        assert unreachable_endpoint_error_from(self._connect_error("http://example.invalid/x")) is None

    def test_a_timeout_at_the_same_address_is_not_a_dead_daemon(
        self, _host_that_is_not_listening: str
    ) -> None:
        """The gate that a mutation showed was untested.

        Removing the exception-type check left every test green, because the
        other narrowness tests carry no address at all. This is the case that
        has one: a daemon at exactly the configured host that **accepted** the
        connection and then took too long. "Nothing is listening there" would
        be a confidently wrong sentence about a service that is running, and
        would send a developer to start something already started.
        """
        import httpx

        from openstategraph.chat_model import unreachable_endpoint_error_from

        timeout = httpx.ReadTimeout(
            "timed out",
            request=httpx.Request("POST", f"{_host_that_is_not_listening}/api/chat"),
        )
        assert unreachable_endpoint_error_from(timeout) is None

    def test_an_unrelated_exception_is_left_alone(
        self, _host_that_is_not_listening: str
    ) -> None:
        from openstategraph.chat_model import unreachable_endpoint_error_from

        assert unreachable_endpoint_error_from(ValueError("connection to the past refused")) is None

    def test_a_refused_credential_still_reads_as_refused(self) -> None:
        """The inverse that matters most: 401 is not a dead daemon."""
        from openstategraph.chat_model import credential_error_from, unreachable_endpoint_error_from
        from openstategraph.errors import ProviderRefusedCredential

        exc = type("AuthenticationError", (Exception,), {"__module__": "openai"})("401")
        assert isinstance(credential_error_from(exc), ProviderRefusedCredential)
        assert unreachable_endpoint_error_from(exc) is None

    def test_a_missing_key_still_raises_missing_provider_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing about this ticket may re-label an absent credential."""
        from openstategraph.chat_model import build_chat_model
        from openstategraph.errors import MissingProviderKey

        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        model = build_chat_model("ollama:gpt-oss:120b-cloud")
        with pytest.raises(MissingProviderKey):
            model.invoke("hi")

    def test_the_cloud_path_is_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key and no host still resolves to the cloud endpoint, unchanged."""
        from openstategraph.chat_model import model_kwargs

        for name in CREDENTIALS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OLLAMA_API_KEY", "not-a-real-key")
        assert model_kwargs("ollama:gpt-oss:120b-cloud") == {"base_url": "https://ollama.com"}
